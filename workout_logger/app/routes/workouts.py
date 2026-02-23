from __future__ import annotations

import csv
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

    plan_exercise_ids = []
    if workout.plan:
        plan_exercise_ids = [pe.exercise_id for pe in workout.plan.exercises if pe.exercise]

    return render_template(
        "workouts/detail.html",
        workout=workout,
        exercises=exercises,
        grouped_sets=grouped_sets,
        plan_exercise_ids=plan_exercise_ids,
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
        reps = int(request.form.get("reps") or "")
        weight_kg = float(request.form.get("weight_kg") or "0")
        rpe_raw = (request.form.get("rpe") or "").strip()
        rpe = float(rpe_raw) if rpe_raw else None
    except ValueError:
        flash("Set values are invalid.", "error")
        return redirect(url_for("workouts.view_workout", workout_id=workout.id))

    if set_no < 1 or reps < 0 or weight_kg < 0:
        flash("Set number, reps and weight must be non-negative (set number starts at 1).", "error")
        return redirect(url_for("workouts.view_workout", workout_id=workout.id))

    db.session.add(
        SetEntry(
            user_id=user.id,
            workout_id=workout.id,
            exercise_id=exercise.id,
            set_no=set_no,
            reps=reps,
            weight_kg=weight_kg,
            rpe=rpe,
        )
    )
    db.session.commit()
    flash("Set added.", "success")
    return redirect(url_for("workouts.view_workout", workout_id=workout.id))


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
                row[5],
                row[6],
                row[7] if row[7] is not None else "",
                row[8] or "",
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
            row[8] or "",
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
