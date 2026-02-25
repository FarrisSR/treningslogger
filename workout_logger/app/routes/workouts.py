from __future__ import annotations

import csv
import re
from datetime import date, datetime
from io import BytesIO, StringIO

from flask import (
    Blueprint,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    stream_with_context,
    url_for,
)
from openpyxl import Workbook
from sqlalchemy.orm import joinedload

from .. import db
from ..models import Exercise, SetEntry, Workout, WorkoutExerciseNote, WorkoutPlan
from . import login_required, require_user

bp = Blueprint("workouts", __name__)


def _user_workout_or_404(user_id: int, workout_id: int) -> Workout:
    workout = (
        Workout.query.filter_by(id=workout_id, user_id=user_id)
        .options(
            joinedload(Workout.sets).joinedload(SetEntry.exercise),
            joinedload(Workout.plan).joinedload(WorkoutPlan.exercises),
            joinedload(Workout.exercise_notes).joinedload(WorkoutExerciseNote.exercise),
        )
        .first()
    )
    if workout is None:
        abort(404)
    return workout


def _get_or_create_exercise(user_id: int, name: str) -> Exercise | None:
    cleaned = " ".join((name or "").split())
    if not cleaned:
        return None
    exercise = Exercise.query.filter_by(user_id=user_id, name=cleaned).first()
    if exercise:
        return exercise
    exercise = Exercise(user_id=user_id, name=cleaned)
    db.session.add(exercise)
    db.session.flush()
    return exercise


def _suggest_reps_from_target(target_reps: str | None) -> int | None:
    parsed = _parse_plan_target(target_reps)
    return parsed["suggested_reps"]


def _parse_plan_target(target_reps: str | None) -> dict[str, int | str | None]:
    if not target_reps:
        return {"mode": "reps", "suggested_reps": None, "suggested_duration_seconds": None}

    target = target_reps.strip().lower()
    time_match = re.fullmatch(r"(\d+)\s*(s|sec|secs|second|seconds)", target)
    if time_match:
        return {
            "mode": "duration",
            "suggested_reps": None,
            "suggested_duration_seconds": int(time_match.group(1)),
        }

    minute_match = re.fullmatch(r"(\d+)\s*(m|min|mins|minute|minutes)", target)
    if minute_match:
        return {
            "mode": "duration",
            "suggested_reps": None,
            "suggested_duration_seconds": int(minute_match.group(1)) * 60,
        }

    min_sec_match = re.fullmatch(r"(\d+)\s*m(?:in)?\s*(\d+)\s*s(?:ec)?", target)
    if min_sec_match:
        return {
            "mode": "duration",
            "suggested_reps": None,
            "suggested_duration_seconds": (int(min_sec_match.group(1)) * 60) + int(min_sec_match.group(2)),
        }

    match = re.search(r"(\d+)", target)
    value = int(match.group(1)) if match else None
    return {
        "mode": "reps",
        "suggested_reps": value if value is not None and value >= 0 else None,
        "suggested_duration_seconds": None,
    }


@bp.get("/")
@login_required
def index():
    user = require_user()
    workouts = (
        Workout.query.filter_by(user_id=user.id)
        .order_by(Workout.workout_date.desc(), Workout.created_at.desc())
        .limit(30)
        .all()
    )
    active_plans = (
        WorkoutPlan.query.filter_by(user_id=user.id)
        .order_by(WorkoutPlan.name.asc())
        .all()
    )
    return render_template("workouts/index.html", workouts=workouts, plans=active_plans)


@bp.route("/workouts/new", methods=["GET", "POST"])
@login_required
def create_workout():
    user = require_user()
    plans = WorkoutPlan.query.filter_by(user_id=user.id).order_by(WorkoutPlan.name.asc()).all()
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        if not title:
            flash("Workout title is required.", "error")
            return render_template("workouts/form.html", plans=plans)

        plan_id_raw = request.form.get("plan_id") or ""
        plan = None
        if plan_id_raw:
            if not plan_id_raw.isdigit():
                abort(400)
            plan = WorkoutPlan.query.filter_by(id=int(plan_id_raw), user_id=user.id).first()
            if plan is None:
                abort(404)

        workout_date_str = request.form.get("workout_date") or ""
        try:
            workout_date = datetime.strptime(workout_date_str, "%Y-%m-%d").date() if workout_date_str else date.today()
        except ValueError:
            flash("Invalid workout date.", "error")
            return render_template("workouts/form.html", plans=plans)

        duration_value = (request.form.get("duration_minutes") or "").strip()
        duration_minutes = int(duration_value) if duration_value.isdigit() else None
        notes = (request.form.get("notes") or "").strip() or None

        workout = Workout(
            user_id=user.id,
            plan_id=plan.id if plan else None,
            title=title,
            workout_date=workout_date,
            duration_minutes=duration_minutes,
            notes=notes,
        )
        db.session.add(workout)
        db.session.commit()
        return redirect(url_for("workouts.view_workout", workout_id=workout.id))

    return render_template("workouts/form.html", plans=plans)


@bp.get("/workouts/<int:workout_id>")
@login_required
def view_workout(workout_id: int):
    user = require_user()
    workout = _user_workout_or_404(user.id, workout_id)
    exercises = Exercise.query.filter_by(user_id=user.id).order_by(Exercise.name.asc()).all()

    grouped_sets: dict[int, list[SetEntry]] = {}
    for set_entry in workout.sets:
        grouped_sets.setdefault(set_entry.exercise_id, []).append(set_entry)

    next_set_no_by_exercise: dict[int, int] = {}
    for exercise_id, sets in grouped_sets.items():
        next_set_no_by_exercise[exercise_id] = max((s.set_no or 0) for s in sets) + 1 if sets else 1
    for exercise in exercises:
        next_set_no_by_exercise.setdefault(exercise.id, 1)

    selected_exercise_id = None
    selected_exercise_raw = (request.args.get("exercise_id") or "").strip()
    if selected_exercise_raw.isdigit():
        candidate_id = int(selected_exercise_raw)
        if any(exercise.id == candidate_id for exercise in exercises):
            selected_exercise_id = candidate_id

    plan_exercise_ids = []
    plan_exercise_items = []
    plan_mode_sections = []
    if workout.plan:
        for pe in workout.plan.exercises:
            if pe.exercise is None:
                continue
            plan_exercise_ids.append(pe.exercise_id)
            logged_sets = len(grouped_sets.get(pe.exercise_id, []))
            parsed_target = _parse_plan_target(pe.target_reps)
            suggested_reps = parsed_target["suggested_reps"]
            suggested_duration_seconds = parsed_target["suggested_duration_seconds"]
            target_mode = parsed_target["mode"]
            plan_exercise_items.append(
                {
                    "exercise": pe.exercise,
                    "target_sets": pe.target_sets,
                    "target_reps": pe.target_reps,
                    "logged_sets": logged_sets,
                    "next_set_no": next_set_no_by_exercise.get(pe.exercise_id, 1),
                    "suggested_reps": suggested_reps,
                    "suggested_duration_seconds": suggested_duration_seconds,
                    "target_mode": target_mode,
                }
            )

            planned_rows = []
            if pe.target_sets and pe.target_sets > 0:
                sets_for_exercise = grouped_sets.get(pe.exercise_id, [])
                for planned_set_no in range(1, pe.target_sets + 1):
                    matching_logged = [s for s in sets_for_exercise if s.set_no == planned_set_no]
                    planned_rows.append(
                        {
                            "set_no": planned_set_no,
                            "suggested_reps": suggested_reps,
                            "suggested_duration_seconds": suggested_duration_seconds,
                            "target_mode": target_mode,
                            "logged": matching_logged,
                        }
                    )

                plan_mode_sections.append(
                    {
                        "exercise": pe.exercise,
                        "target_sets": pe.target_sets,
                        "target_reps": pe.target_reps,
                        "rows": planned_rows,
                    }
                )

        if selected_exercise_id is None and plan_exercise_items:
            unfinished = next(
                (
                    item
                    for item in plan_exercise_items
                    if item["target_sets"] and item["logged_sets"] < item["target_sets"]
                ),
                None,
            )
            selected_exercise_id = (unfinished or plan_exercise_items[0])["exercise"].id

    plan_exercise_id_set = set(plan_exercise_ids)
    other_exercises = [exercise for exercise in exercises if exercise.id not in plan_exercise_id_set]
    selected_set_no = next_set_no_by_exercise.get(selected_exercise_id, 1) if selected_exercise_id else 1

    return render_template(
        "workouts/detail.html",
        workout=workout,
        exercises=exercises,
        other_exercises=other_exercises,
        grouped_sets=grouped_sets,
        plan_exercise_ids=plan_exercise_ids,
        plan_exercise_items=plan_exercise_items,
        plan_mode_sections=plan_mode_sections,
        selected_exercise_id=selected_exercise_id,
        next_set_no_by_exercise=next_set_no_by_exercise,
        selected_set_no=selected_set_no,
    )


@bp.post("/workouts/<int:workout_id>/add_set")
@login_required
def add_set(workout_id: int):
    user = require_user()
    workout = _user_workout_or_404(user.id, workout_id)

    exercise_id_raw = request.form.get("exercise_id") or ""
    exercise_name = (request.form.get("exercise_name") or "").strip()

    exercise = None
    if exercise_id_raw.isdigit():
        exercise = Exercise.query.filter_by(id=int(exercise_id_raw), user_id=user.id).first()
    elif exercise_name:
        exercise = _get_or_create_exercise(user.id, exercise_name)

    if exercise is None:
        flash("Select or enter an exercise.", "error")
        return redirect(url_for("workouts.view_workout", workout_id=workout.id))

    try:
        set_no = int(request.form.get("set_no") or "")
        reps_raw = (request.form.get("reps") or "").strip()
        duration_raw = (request.form.get("duration_seconds") or "").strip()
        reps = int(reps_raw) if reps_raw else None
        duration_seconds = int(duration_raw) if duration_raw else None
        weight_kg = float(request.form.get("weight_kg") or "0")
        rpe_raw = (request.form.get("rpe") or "").strip()
        rpe = float(rpe_raw) if rpe_raw else None
    except ValueError:
        flash("Set values are invalid.", "error")
        return redirect(url_for("workouts.view_workout", workout_id=workout.id, exercise_id=exercise.id))

    if set_no < 1 or weight_kg < 0:
        flash("Set number and weight must be non-negative (set number starts at 1).", "error")
        return redirect(url_for("workouts.view_workout", workout_id=workout.id, exercise_id=exercise.id))
    if reps is None and duration_seconds is None:
        flash("Provide either reps or duration.", "error")
        return redirect(url_for("workouts.view_workout", workout_id=workout.id, exercise_id=exercise.id))
    if reps is not None and reps < 0:
        flash("Reps must be 0 or more.", "error")
        return redirect(url_for("workouts.view_workout", workout_id=workout.id, exercise_id=exercise.id))
    if duration_seconds is not None and duration_seconds < 1:
        flash("Duration must be at least 1 second.", "error")
        return redirect(url_for("workouts.view_workout", workout_id=workout.id, exercise_id=exercise.id))
    if reps is not None and duration_seconds is not None:
        flash("Use either reps or duration for a set, not both.", "error")
        return redirect(url_for("workouts.view_workout", workout_id=workout.id, exercise_id=exercise.id))

    db.session.add(
        SetEntry(
            user_id=user.id,
            workout_id=workout.id,
            exercise_id=exercise.id,
            set_no=set_no,
            reps=reps,
            duration_seconds=duration_seconds,
            weight_kg=weight_kg,
            rpe=rpe,
        )
    )
    db.session.commit()
    flash("Set added.", "success")
    return redirect(url_for("workouts.view_workout", workout_id=workout.id, exercise_id=exercise.id))


@bp.post("/workouts/<int:workout_id>/update")
@login_required
def update_workout(workout_id: int):
    user = require_user()
    workout = _user_workout_or_404(user.id, workout_id)

    workout.notes = (request.form.get("notes") or "").strip() or None
    duration_value = (request.form.get("duration_minutes") or "").strip()
    workout.duration_minutes = int(duration_value) if duration_value.isdigit() else None
    db.session.commit()
    flash("Workout details saved.", "success")
    return redirect(url_for("workouts.view_workout", workout_id=workout.id))


@bp.post("/workouts/<int:workout_id>/sets/<int:set_id>/delete")
@login_required
def delete_set(workout_id: int, set_id: int):
    user = require_user()
    workout = _user_workout_or_404(user.id, workout_id)
    set_entry = SetEntry.query.filter_by(id=set_id, workout_id=workout.id, user_id=user.id).first()
    if set_entry is None:
        abort(404)
    db.session.delete(set_entry)
    db.session.commit()
    flash("Set deleted.", "success")
    return redirect(url_for("workouts.view_workout", workout_id=workout.id))


@bp.post("/workouts/<int:workout_id>/delete")
@login_required
def delete_workout(workout_id: int):
    user = require_user()
    workout = _user_workout_or_404(user.id, workout_id)
    db.session.delete(workout)
    db.session.commit()
    flash("Workout deleted.", "success")
    return redirect(url_for("workouts.index"))


def _export_rows(user_id: int):
    return (
        SetEntry.query.join(Workout, SetEntry.workout_id == Workout.id)
        .join(Exercise, SetEntry.exercise_id == Exercise.id)
        .filter(SetEntry.user_id == user_id, Workout.user_id == user_id, Exercise.user_id == user_id)
        .order_by(Workout.workout_date.asc(), Workout.created_at.asc(), Exercise.name.asc(), SetEntry.set_no.asc())
        .with_entities(
            Workout.workout_date,
            Workout.title,
            Workout.duration_minutes,
            Exercise.name,
            SetEntry.set_no,
            SetEntry.reps,
            SetEntry.duration_seconds,
            SetEntry.weight_kg,
            SetEntry.rpe,
            Workout.notes,
        )
    )


@bp.get("/export/sets.csv")
@login_required
def export_sets_csv():
    user = require_user()

    def generate():
        buffer = StringIO()
        writer = csv.writer(buffer)
        writer.writerow([
            "date",
            "workout title",
            "duration",
            "exercise",
            "set_no",
            "reps",
            "duration_seconds",
            "weight_kg",
            "rpe",
            "workout notes",
        ])
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)

        for row in _export_rows(user.id):
            writer.writerow([
                row[0].isoformat() if row[0] else "",
                row[1] or "",
                row[2] if row[2] is not None else "",
                row[3] or "",
                row[4],
                row[5] if row[5] is not None else "",
                row[6] if row[6] is not None else "",
                row[7] if row[7] is not None else "",
                row[8] if row[8] is not None else "",
                row[9] or "",
            ])
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)

    filename = f"workout_sets_{date.today().isoformat()}.csv"
    return Response(
        stream_with_context(generate()),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@bp.get("/export/sets.xlsx")
@login_required
def export_sets_xlsx():
    user = require_user()
    wb = Workbook()
    ws = wb.active
    ws.title = "Sets"
    ws.append([
        "date",
        "workout title",
        "duration",
        "exercise",
        "set_no",
        "reps",
        "duration_seconds",
        "weight_kg",
        "rpe",
        "workout notes",
    ])
    for row in _export_rows(user.id):
        ws.append([
            row[0].isoformat() if row[0] else "",
            row[1] or "",
            row[2],
            row[3] or "",
            row[4],
            row[5],
            row[6],
            row[7],
            row[8],
            row[9] or "",
        ])

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    filename = f"workout_sets_{date.today().isoformat()}.xlsx"
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
