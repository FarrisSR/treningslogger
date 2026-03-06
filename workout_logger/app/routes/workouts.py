from __future__ import annotations

import csv
import json
import re
from datetime import date, datetime
from io import BytesIO, StringIO

from flask import (
    Blueprint,
    Response,
    abort,
    flash,
    jsonify,
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
from ..models import Exercise, PlanExercise, SetEntry, UserProfile, Workout, WorkoutExerciseNote, WorkoutPlan
from ..services.history import get_previous_workout
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


def _normalize_plan_side(side: object) -> str | None:
    if side is None:
        return None
    value = str(side).strip().lower()
    return value if value in {"left", "right", "both"} else None


def _labelize_group_key(group_key: str) -> str:
    text = " ".join(str(group_key).replace("_", " ").replace("-", " ").split())
    return text.title() if text else "Group"


def _parse_set_values_from_mapping(data: object) -> tuple[int, int | None, int | None, float, float | None]:
    get = data.get if hasattr(data, "get") else (lambda _key, default=None: default)
    set_no = int((get("set_no") or "").strip() if isinstance(get("set_no"), str) else (get("set_no") or ""))
    reps_raw = (get("reps") or "").strip() if isinstance(get("reps"), str) else str(get("reps") or "").strip()
    duration_raw = (
        (get("duration_seconds") or "").strip()
        if isinstance(get("duration_seconds"), str)
        else str(get("duration_seconds") or "").strip()
    )
    reps = int(reps_raw) if reps_raw else None
    duration_seconds = int(duration_raw) if duration_raw else None
    weight_raw = (get("weight_kg") or "").strip() if isinstance(get("weight_kg"), str) else str(get("weight_kg") or "").strip()
    if weight_raw:
        weight_kg = float(weight_raw)
    elif duration_seconds is not None and reps is None:
        weight_kg = 1.0
    else:
        weight_kg = 0.0
    rpe_raw = (get("rpe") or "").strip() if isinstance(get("rpe"), str) else str(get("rpe") or "").strip()
    rpe = float(rpe_raw) if rpe_raw else None
    return set_no, reps, duration_seconds, weight_kg, rpe


def _validate_set_values(set_no: int, reps: int | None, duration_seconds: int | None, weight_kg: float) -> str | None:
    if set_no < 1 or weight_kg < 0:
        return "Set number and weight must be non-negative (set number starts at 1)."
    if reps is None and duration_seconds is None:
        return "Provide either reps or duration."
    if reps is not None and reps < 0:
        return "Reps must be 0 or more."
    if duration_seconds is not None and duration_seconds < 1:
        return "Duration must be at least 1 second."
    if reps is not None and duration_seconds is not None:
        return "Use either reps or duration for a set, not both."
    return None


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
    previous_workout = None
    previous_sets_by_exercise_set_no: dict[tuple[int, int], SetEntry] = {}
    previous_last_set_by_exercise: dict[int, SetEntry] = {}
    if workout.plan:
        previous_workout = get_previous_workout(user.id, workout)
        if previous_workout is not None:
            previous_sets = (
                SetEntry.query.filter_by(user_id=user.id, workout_id=previous_workout.id)
                .order_by(SetEntry.exercise_id.asc(), SetEntry.set_no.asc(), SetEntry.id.asc())
                .all()
            )
            for prev_set in previous_sets:
                previous_sets_by_exercise_set_no.setdefault((prev_set.exercise_id, prev_set.set_no), prev_set)
                previous_last_set_by_exercise[prev_set.exercise_id] = prev_set

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
                    "group_key": pe.group_key,
                    "side": pe.side,
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
                    previous_set = previous_sets_by_exercise_set_no.get((pe.exercise_id, planned_set_no))
                    if previous_set is None:
                        previous_set = previous_last_set_by_exercise.get(pe.exercise_id)
                    planned_rows.append(
                        {
                            "plan_exercise_id": pe.id,
                            "set_no": planned_set_no,
                            "suggested_reps": suggested_reps,
                            "suggested_duration_seconds": suggested_duration_seconds,
                            "suggested_weight_kg": previous_set.weight_kg if previous_set is not None else None,
                            "target_mode": target_mode,
                            "side": pe.side,
                            "previous_set": previous_set,
                            "logged": matching_logged,
                        }
                    )

                plan_mode_sections.append(
                    {
                        "plan_exercise_id": pe.id,
                        "exercise": pe.exercise,
                        "target_sets": pe.target_sets,
                        "target_reps": pe.target_reps,
                        "group_key": pe.group_key,
                        "side": pe.side,
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
    workout_view_mode = getattr(getattr(user, "profile", None), "workout_view_mode", None) or "accordion"
    if workout_view_mode not in {"accordion", "tabs", "list"}:
        workout_view_mode = "accordion"
    plan_mode_groups = []
    group_map: dict[str, dict] = {}
    for section in plan_mode_sections:
        group_key = (section.get("group_key") or "").strip() if section.get("group_key") else None
        if group_key:
            map_key = group_key.lower()
            group = group_map.get(map_key)
            if group is None:
                group = {
                    "id": f"plan-group-{len(plan_mode_groups) + 1}",
                    "title": _labelize_group_key(group_key),
                    "group_key": group_key,
                    "members": [],
                }
                group_map[map_key] = group
                plan_mode_groups.append(group)
            group["members"].append(section)
        else:
            plan_mode_groups.append(
                {
                    "id": f"plan-group-{len(plan_mode_groups) + 1}",
                    "title": section["exercise"].name,
                    "group_key": None,
                    "members": [section],
                }
            )

    return render_template(
        "workouts/detail.html",
        workout=workout,
        exercises=exercises,
        other_exercises=other_exercises,
        grouped_sets=grouped_sets,
        plan_exercise_ids=plan_exercise_ids,
        plan_exercise_items=plan_exercise_items,
        plan_mode_sections=plan_mode_sections,
        plan_mode_groups=plan_mode_groups,
        previous_workout=previous_workout,
        workout_view_mode=workout_view_mode,
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
        set_no, reps, duration_seconds, weight_kg, rpe = _parse_set_values_from_mapping(request.form)
    except ValueError:
        flash("Set values are invalid.", "error")
        return redirect(url_for("workouts.view_workout", workout_id=workout.id, exercise_id=exercise.id))

    validation_error = _validate_set_values(set_no, reps, duration_seconds, weight_kg)
    if validation_error:
        flash(validation_error, "error")
        return redirect(url_for("workouts.view_workout", workout_id=workout.id, exercise_id=exercise.id))

    existing_same_set_no = SetEntry.query.filter_by(
        user_id=user.id,
        workout_id=workout.id,
        exercise_id=exercise.id,
        set_no=set_no,
    ).first()
    if existing_same_set_no is not None:
        flash(
            f"Set #{set_no} already exists for {exercise.name}. Delete or renumber the existing set first.",
            "error",
        )
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


@bp.post("/workouts/<int:workout_id>/add_sets_bulk")
@login_required
def add_sets_bulk(workout_id: int):
    user = require_user()
    workout = _user_workout_or_404(user.id, workout_id)
    payload = request.get_json(silent=True) or {}
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return jsonify({"ok": False, "error": "Invalid payload."}), 400

    created = 0
    errors: list[str] = []
    seen_keys: set[tuple[int, int]] = set()
    for idx, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            errors.append(f"Row {idx}: invalid item.")
            continue
        exercise_id = item.get("exercise_id")
        if not isinstance(exercise_id, int):
            errors.append(f"Row {idx}: missing exercise_id.")
            continue
        exercise = Exercise.query.filter_by(id=exercise_id, user_id=user.id).first()
        if exercise is None:
            errors.append(f"Row {idx}: exercise not found.")
            continue
        try:
            set_no, reps, duration_seconds, weight_kg, rpe = _parse_set_values_from_mapping(item)
        except ValueError:
            errors.append(f"Row {idx} ({exercise.name}): invalid values.")
            continue
        validation_error = _validate_set_values(set_no, reps, duration_seconds, weight_kg)
        if validation_error:
            errors.append(f"Row {idx} ({exercise.name}): {validation_error}")
            continue
        key = (exercise.id, set_no)
        if key in seen_keys:
            errors.append(f"Row {idx} ({exercise.name}): duplicate set #{set_no} in this save.")
            continue
        seen_keys.add(key)
        duplicate = SetEntry.query.filter_by(
            user_id=user.id,
            workout_id=workout.id,
            exercise_id=exercise.id,
            set_no=set_no,
        ).first()
        if duplicate is not None:
            errors.append(f"Row {idx} ({exercise.name}): set #{set_no} already exists.")
            continue
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
        created += 1

    if created:
        db.session.commit()
    return jsonify({"ok": True, "created": created, "errors": errors})


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


@bp.post("/preferences/workout-view-mode")
@login_required
def set_workout_view_mode_preference():
    user = require_user()
    mode = (request.form.get("workout_view_mode") or "").strip().lower()
    next_url = request.form.get("next") or url_for("workouts.index")
    if mode not in {"accordion", "tabs", "list"}:
        flash("Invalid view mode.", "error")
        return redirect(next_url)
    profile = user.profile
    if profile is None:
        profile = UserProfile(user_id=user.id, workout_view_mode=mode)
        db.session.add(profile)
    else:
        profile.workout_view_mode = mode
    db.session.commit()
    flash("Visningsmodus lagret.", "success")
    return redirect(next_url)


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


@bp.post("/workouts/<int:workout_id>/sets/<int:set_id>/update")
@login_required
def update_set(workout_id: int, set_id: int):
    user = require_user()
    workout = _user_workout_or_404(user.id, workout_id)
    set_entry = SetEntry.query.filter_by(id=set_id, workout_id=workout.id, user_id=user.id).first()
    if set_entry is None:
        abort(404)

    try:
        set_no, reps, duration_seconds, weight_kg, rpe = _parse_set_values_from_mapping(request.form)
    except ValueError:
        flash("Set values are invalid.", "error")
        return redirect(url_for("workouts.view_workout", workout_id=workout.id, exercise_id=set_entry.exercise_id))

    validation_error = _validate_set_values(set_no, reps, duration_seconds, weight_kg)
    if validation_error:
        flash(validation_error, "error")
        return redirect(url_for("workouts.view_workout", workout_id=workout.id, exercise_id=set_entry.exercise_id))

    duplicate = SetEntry.query.filter(
        SetEntry.user_id == user.id,
        SetEntry.workout_id == workout.id,
        SetEntry.exercise_id == set_entry.exercise_id,
        SetEntry.set_no == set_no,
        SetEntry.id != set_entry.id,
    ).first()
    if duplicate is not None:
        flash(f"Set #{set_no} already exists for this exercise.", "error")
        return redirect(url_for("workouts.view_workout", workout_id=workout.id, exercise_id=set_entry.exercise_id))

    set_entry.set_no = set_no
    set_entry.reps = reps
    set_entry.duration_seconds = duration_seconds
    set_entry.weight_kg = weight_kg
    set_entry.rpe = rpe
    db.session.commit()
    flash("Set updated.", "success")
    return redirect(url_for("workouts.view_workout", workout_id=workout.id, exercise_id=set_entry.exercise_id))


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


def _read_upload_text(file_key: str, text_key: str) -> str:
    text_value = (request.form.get(text_key) or "").strip()
    if text_value:
        return text_value
    uploaded = request.files.get(file_key)
    if uploaded and uploaded.filename:
        return uploaded.read().decode("utf-8")
    return ""


def _parse_optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return None
    return int(text)


def _parse_optional_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    return float(text)


def _normalized_csv_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (key or "").strip().lower()).strip("_")


def _export_workouts_payload(user_id: int) -> dict:
    exercises = Exercise.query.filter_by(user_id=user_id).order_by(Exercise.name.asc()).all()
    plans = (
        WorkoutPlan.query.filter_by(user_id=user_id)
        .options(joinedload(WorkoutPlan.exercises).joinedload(PlanExercise.exercise))
        .order_by(WorkoutPlan.name.asc())
        .all()
    )
    workouts = (
        Workout.query.filter_by(user_id=user_id)
        .options(
            joinedload(Workout.sets).joinedload(SetEntry.exercise),
            joinedload(Workout.exercise_notes).joinedload(WorkoutExerciseNote.exercise),
            joinedload(Workout.plan),
        )
        .order_by(Workout.workout_date.asc(), Workout.created_at.asc())
        .all()
    )

    return {
        "format": "workout_logger_export",
        "version": 1,
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "exercises": [{"name": exercise.name} for exercise in exercises],
        "plans": [
            {
                "name": plan.name,
                "description": plan.description,
                "exercises": [
                    {
                        "exercise": pe.exercise.name if pe.exercise else None,
                        "position": pe.position,
                        "target_sets": pe.target_sets,
                        "target_reps": pe.target_reps,
                        "group_key": pe.group_key,
                        "side": pe.side,
                    }
                    for pe in plan.exercises
                    if pe.exercise is not None
                ],
            }
            for plan in plans
        ],
        "workouts": [
            {
                "title": workout.title,
                "workout_date": workout.workout_date.isoformat(),
                "duration_minutes": workout.duration_minutes,
                "notes": workout.notes,
                "plan": workout.plan.name if workout.plan else None,
                "sets": [
                    {
                        "exercise": s.exercise.name if s.exercise else None,
                        "set_no": s.set_no,
                        "reps": s.reps,
                        "duration_seconds": s.duration_seconds,
                        "weight_kg": s.weight_kg,
                        "rpe": s.rpe,
                    }
                    for s in sorted(workout.sets, key=lambda x: (x.exercise_id or 0, x.set_no or 0, x.id))
                    if s.exercise is not None
                ],
                "exercise_notes": [
                    {
                        "exercise": note.exercise.name if note.exercise else None,
                        "note": note.note,
                    }
                    for note in workout.exercise_notes
                    if note.exercise is not None and note.note
                ],
            }
            for workout in workouts
        ],
    }


def _find_duplicate_workout_for_import(user_id: int, title: str, workout_date: date, plan: WorkoutPlan | None) -> Workout | None:
    return Workout.query.filter_by(
        user_id=user_id,
        workout_date=workout_date,
        title=title,
        plan_id=plan.id if plan else None,
    ).first()


def _find_duplicate_plan_for_import(user_id: int, plan_name: str) -> WorkoutPlan | None:
    return WorkoutPlan.query.filter_by(user_id=user_id, name=plan_name).first()


def _import_workouts_json_payload(
    user_id: int,
    payload: dict,
    default_plan_conflict_strategy: str = "merge",
    plan_strategies: dict[int, str] | None = None,
    default_workout_conflict_strategy: str = "skip",
    workout_strategies: dict[int, str] | None = None,
) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("JSON root must be an object.")
    if default_workout_conflict_strategy not in {"skip", "merge", "replace"}:
        raise ValueError("Invalid default workout conflict strategy.")
    if default_plan_conflict_strategy not in {"skip", "merge", "replace"}:
        raise ValueError("Invalid default plan conflict strategy.")
    workout_strategies = workout_strategies or {}
    plan_strategies = plan_strategies or {}

    summary = {
        "exercises_created": 0,
        "plans_created": 0,
        "plans_skipped": 0,
        "plans_merged": 0,
        "plans_replaced": 0,
        "workouts_created": 0,
        "workouts_skipped": 0,
        "workouts_merged": 0,
        "workouts_replaced": 0,
        "sets_created": 0,
        "sets_updated": 0,
        "exercise_notes_created": 0,
        "exercise_notes_updated": 0,
    }

    exercise_cache: dict[str, Exercise] = {}

    def ensure_exercise(name: str | None) -> Exercise | None:
        if not name:
            return None
        clean = " ".join(str(name).split())
        if not clean:
            return None
        key = clean.lower()
        if key in exercise_cache:
            return exercise_cache[key]
        existing = Exercise.query.filter_by(user_id=user_id, name=clean).first()
        if existing is None:
            existing = Exercise(user_id=user_id, name=clean)
            db.session.add(existing)
            db.session.flush()
            summary["exercises_created"] += 1
        exercise_cache[key] = existing
        return existing

    for ex in payload.get("exercises", []) or []:
        if isinstance(ex, dict):
            ensure_exercise(ex.get("name"))

    plan_cache_by_name: dict[str, WorkoutPlan] = {}
    for plan_index, plan_payload in enumerate(payload.get("plans", []) or []):
        if not isinstance(plan_payload, dict):
            continue
        plan_name = " ".join(str(plan_payload.get("name") or "").split())
        if not plan_name:
            continue
        plan = _find_duplicate_plan_for_import(user_id, plan_name)
        plan_strategy = plan_strategies.get(plan_index, default_plan_conflict_strategy)
        if plan_strategy not in {"skip", "merge", "replace"}:
            plan_strategy = default_plan_conflict_strategy

        if plan is None:
            plan = WorkoutPlan(user_id=user_id, name=plan_name)
            db.session.add(plan)
            db.session.flush()
            summary["plans_created"] += 1
        elif plan_strategy == "skip":
            summary["plans_skipped"] += 1
            plan_cache_by_name[plan_name.lower()] = plan
            continue
        elif plan_strategy == "replace":
            summary["plans_replaced"] += 1
        else:
            summary["plans_merged"] += 1

        plan.description = (plan_payload.get("description") or None)
        incoming_exercises = [pe for pe in (plan_payload.get("exercises") or []) if isinstance(pe, dict)]

        if plan_strategy == "replace":
            plan.exercises.clear()
            db.session.flush()
            for idx, pe in enumerate(incoming_exercises, start=1):
                exercise = ensure_exercise(pe.get("exercise"))
                if exercise is None:
                    continue
                plan.exercises.append(
                    PlanExercise(
                        exercise_id=exercise.id,
                        position=_parse_optional_int(pe.get("position")) or idx,
                        target_sets=_parse_optional_int(pe.get("target_sets")),
                        target_reps=(str(pe.get("target_reps")).strip() if pe.get("target_reps") is not None else None),
                        group_key=(str(pe.get("group_key")).strip() if pe.get("group_key") is not None else None),
                        side=_normalize_plan_side(pe.get("side")),
                    )
                )
        elif plan_strategy == "merge" and plan.id is not None:
            existing_by_exercise_name = {}
            for existing_pe in plan.exercises:
                if existing_pe.exercise is not None:
                    existing_by_exercise_name[existing_pe.exercise.name.lower()] = existing_pe
            next_position = max((pe.position or 0 for pe in plan.exercises), default=0) + 1
            for idx, pe in enumerate(incoming_exercises, start=1):
                exercise = ensure_exercise(pe.get("exercise"))
                if exercise is None:
                    continue
                target_sets = _parse_optional_int(pe.get("target_sets"))
                target_reps = (str(pe.get("target_reps")).strip() if pe.get("target_reps") is not None else None)
                group_key = (str(pe.get("group_key")).strip() if pe.get("group_key") is not None else None)
                side = _normalize_plan_side(pe.get("side"))
                pos = _parse_optional_int(pe.get("position")) or idx
                existing_pe = existing_by_exercise_name.get(exercise.name.lower())
                if existing_pe is None:
                    plan.exercises.append(
                        PlanExercise(
                            exercise_id=exercise.id,
                            position=max(pos, next_position),
                            target_sets=target_sets,
                            target_reps=target_reps,
                            group_key=group_key,
                            side=side,
                        )
                    )
                    next_position += 1
                else:
                    existing_pe.position = pos
                    existing_pe.target_sets = target_sets
                    existing_pe.target_reps = target_reps
                    existing_pe.group_key = group_key
                    existing_pe.side = side
        else:
            # New plan: populate with imported exercises.
            for idx, pe in enumerate(incoming_exercises, start=1):
                exercise = ensure_exercise(pe.get("exercise"))
                if exercise is None:
                    continue
                plan.exercises.append(
                    PlanExercise(
                        exercise_id=exercise.id,
                        position=_parse_optional_int(pe.get("position")) or idx,
                        target_sets=_parse_optional_int(pe.get("target_sets")),
                        target_reps=(str(pe.get("target_reps")).strip() if pe.get("target_reps") is not None else None),
                        group_key=(str(pe.get("group_key")).strip() if pe.get("group_key") is not None else None),
                        side=_normalize_plan_side(pe.get("side")),
                    )
                )
        plan_cache_by_name[plan_name.lower()] = plan

    for workout_index, workout_payload in enumerate(payload.get("workouts", []) or []):
        if not isinstance(workout_payload, dict):
            continue
        title = " ".join(str(workout_payload.get("title") or "").split())
        if not title:
            continue
        workout_date_raw = str(workout_payload.get("workout_date") or "").strip()
        if not workout_date_raw:
            raise ValueError(f"Workout '{title}' is missing workout_date.")
        workout_date = datetime.strptime(workout_date_raw, "%Y-%m-%d").date()

        plan_name = " ".join(str(workout_payload.get("plan") or "").split()) or None
        plan = plan_cache_by_name.get(plan_name.lower()) if plan_name else None
        if plan is None and plan_name:
            plan = WorkoutPlan.query.filter_by(user_id=user_id, name=plan_name).first()
            if plan:
                plan_cache_by_name[plan_name.lower()] = plan

        duplicate = _find_duplicate_workout_for_import(user_id, title, workout_date, plan)
        strategy = workout_strategies.get(workout_index, default_workout_conflict_strategy)
        if strategy not in {"skip", "merge", "replace"}:
            strategy = default_workout_conflict_strategy

        workout: Workout | None = None
        if duplicate is not None:
            if strategy == "skip":
                summary["workouts_skipped"] += 1
                continue
            if strategy == "replace":
                db.session.delete(duplicate)
                db.session.flush()
                summary["workouts_replaced"] += 1
            elif strategy == "merge":
                workout = duplicate
                workout.plan_id = plan.id if plan else None
                workout.duration_minutes = _parse_optional_int(workout_payload.get("duration_minutes"))
                workout.notes = (str(workout_payload.get("notes")).strip() if workout_payload.get("notes") is not None else None)
                summary["workouts_merged"] += 1

        if workout is None:
            workout = Workout(
                user_id=user_id,
                plan_id=plan.id if plan else None,
                title=title,
                workout_date=workout_date,
                duration_minutes=_parse_optional_int(workout_payload.get("duration_minutes")),
                notes=(str(workout_payload.get("notes")).strip() if workout_payload.get("notes") is not None else None),
            )
            db.session.add(workout)
            db.session.flush()
            summary["workouts_created"] += 1

        existing_sets_by_key: dict[tuple[int, int], SetEntry] = {}
        existing_notes_by_exercise_id: dict[int, WorkoutExerciseNote] = {}
        if duplicate is not None and strategy == "merge":
            for existing_set in SetEntry.query.filter_by(user_id=user_id, workout_id=workout.id).all():
                existing_sets_by_key[(existing_set.exercise_id, existing_set.set_no)] = existing_set
            for existing_note in WorkoutExerciseNote.query.filter_by(user_id=user_id, workout_id=workout.id).all():
                existing_notes_by_exercise_id[existing_note.exercise_id] = existing_note

        for set_payload in workout_payload.get("sets", []) or []:
            if not isinstance(set_payload, dict):
                continue
            exercise = ensure_exercise(set_payload.get("exercise"))
            if exercise is None:
                continue
            set_no = _parse_optional_int(set_payload.get("set_no"))
            if set_no is None:
                continue
            reps = _parse_optional_int(set_payload.get("reps"))
            duration_seconds = _parse_optional_int(set_payload.get("duration_seconds"))
            if reps is None and duration_seconds is None:
                continue
            if reps is not None and duration_seconds is not None:
                continue
            weight_kg = _parse_optional_float(set_payload.get("weight_kg")) or 0.0
            rpe = _parse_optional_float(set_payload.get("rpe"))
            existing_set = existing_sets_by_key.get((exercise.id, set_no))
            if existing_set is not None:
                existing_set.reps = reps
                existing_set.duration_seconds = duration_seconds
                existing_set.weight_kg = weight_kg
                existing_set.rpe = rpe
                summary["sets_updated"] += 1
            else:
                db.session.add(
                    SetEntry(
                        user_id=user_id,
                        workout_id=workout.id,
                        exercise_id=exercise.id,
                        set_no=set_no,
                        reps=reps,
                        duration_seconds=duration_seconds,
                        weight_kg=weight_kg,
                        rpe=rpe,
                    )
                )
                summary["sets_created"] += 1

        for note_payload in workout_payload.get("exercise_notes", []) or []:
            if not isinstance(note_payload, dict):
                continue
            note_text = (str(note_payload.get("note") or "")).strip()
            if not note_text:
                continue
            exercise = ensure_exercise(note_payload.get("exercise"))
            if exercise is None:
                continue
            existing_note = existing_notes_by_exercise_id.get(exercise.id)
            if existing_note is None:
                existing_note = WorkoutExerciseNote.query.filter_by(
                    user_id=user_id,
                    workout_id=workout.id,
                    exercise_id=exercise.id,
                ).first()
            if existing_note is None:
                db.session.add(
                    WorkoutExerciseNote(
                        user_id=user_id,
                        workout_id=workout.id,
                        exercise_id=exercise.id,
                        note=note_text,
                    )
                )
                summary["exercise_notes_created"] += 1
            else:
                existing_note.note = note_text
                summary["exercise_notes_updated"] += 1

    return summary


def _preview_workouts_json_payload(payload: dict, user_id: int | None = None) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("JSON root must be an object.")
    plans = [p for p in (payload.get("plans") or []) if isinstance(p, dict)]
    workouts = [w for w in (payload.get("workouts") or []) if isinstance(w, dict)]
    exercises = [e for e in (payload.get("exercises") or []) if isinstance(e, dict)]

    preview_plans = []
    plan_conflicts = []
    for plan in plans[:5]:
        plan_exercises = [pe for pe in (plan.get("exercises") or []) if isinstance(pe, dict)]
        preview_plans.append(
            {
                "name": str(plan.get("name") or "").strip(),
                "exercise_count": len(plan_exercises),
                "exercise_examples": [
                    str(pe.get("exercise") or "").strip()
                    for pe in plan_exercises[:4]
                    if str(pe.get("exercise") or "").strip()
                ],
            }
        )
    if user_id is not None:
        for idx, plan in enumerate(plans):
            plan_name = str(plan.get("name") or "").strip()
            if not plan_name:
                continue
            existing = _find_duplicate_plan_for_import(user_id, plan_name)
            if existing is not None:
                plan_exercises = [pe for pe in (plan.get("exercises") or []) if isinstance(pe, dict)]
                plan_conflicts.append(
                    {
                        "index": idx,
                        "name": plan_name,
                        "import_exercise_count": len(plan_exercises),
                        "existing_exercise_count": len(existing.exercises),
                    }
                )

    preview_workouts = []
    workout_conflicts = []
    for idx, workout in enumerate(workouts):
        sets = [s for s in (workout.get("sets") or []) if isinstance(s, dict)]
        title = str(workout.get("title") or "").strip()
        workout_date_text = str(workout.get("workout_date") or "").strip()
        plan_name = str(workout.get("plan") or "").strip()
        item = {
            "index": idx,
            "title": title,
            "workout_date": workout_date_text,
            "plan": plan_name,
            "set_count": len(sets),
            "exercise_examples": sorted(
                {
                    str(s.get("exercise") or "").strip()
                    for s in sets
                    if str(s.get("exercise") or "").strip()
                }
            )[:4],
        }
        if len(preview_workouts) < 8:
            preview_workouts.append(item)

        if user_id is not None and title and workout_date_text:
            try:
                workout_date = datetime.strptime(workout_date_text, "%Y-%m-%d").date()
            except ValueError:
                continue
            plan = None
            if plan_name:
                plan = WorkoutPlan.query.filter_by(user_id=user_id, name=plan_name).first()
            duplicate = _find_duplicate_workout_for_import(user_id, title, workout_date, plan)
            if duplicate is not None:
                workout_conflicts.append(
                    {
                        "index": idx,
                        "title": title,
                        "workout_date": workout_date_text,
                        "plan": plan_name,
                        "import_set_count": len(sets),
                        "existing_workout_id": duplicate.id,
                        "existing_set_count": SetEntry.query.filter_by(user_id=user_id, workout_id=duplicate.id).count(),
                    }
                )

    return {
        "meta": {
            "format": payload.get("format"),
            "version": payload.get("version"),
            "exercises_count": len(exercises),
            "plans_count": len(plans),
            "workouts_count": len(workouts),
            "plan_conflicts_count": len(plan_conflicts),
            "workout_conflicts_count": len(workout_conflicts),
        },
        "plans": preview_plans,
        "plan_conflicts": plan_conflicts,
        "workouts": preview_workouts,
        "workout_conflicts": workout_conflicts,
    }


def _import_sets_csv_text(user_id: int, csv_text: str, skip_existing_sets: bool = True) -> dict:
    if not csv_text.strip():
        raise ValueError("CSV input is empty.")

    reader = csv.DictReader(StringIO(csv_text))
    if not reader.fieldnames:
        raise ValueError("CSV file is missing headers.")

    header_map = {_normalized_csv_key(name): name for name in reader.fieldnames}

    def get_cell(row: dict, *aliases: str) -> str:
        for alias in aliases:
            actual = header_map.get(_normalized_csv_key(alias))
            if actual is not None:
                return str(row.get(actual) or "").strip()
        return ""

    summary = {
        "rows_read": 0,
        "rows_skipped": 0,
        "workouts_created": 0,
        "sets_created": 0,
        "sets_skipped_existing": 0,
        "exercises_created": 0,
    }
    exercise_cache: dict[str, Exercise] = {}
    workout_cache: dict[tuple, Workout] = {}

    def ensure_exercise(name: str) -> Exercise:
        clean = " ".join(name.split())
        key = clean.lower()
        if key in exercise_cache:
            return exercise_cache[key]
        exercise = Exercise.query.filter_by(user_id=user_id, name=clean).first()
        if exercise is None:
            exercise = Exercise(user_id=user_id, name=clean)
            db.session.add(exercise)
            db.session.flush()
            summary["exercises_created"] += 1
        exercise_cache[key] = exercise
        return exercise

    for row in reader:
        summary["rows_read"] += 1
        title = get_cell(row, "workout_title", "workout title", "title")
        date_str = get_cell(row, "date", "workout_date")
        exercise_name = get_cell(row, "exercise")
        set_no_str = get_cell(row, "set_no", "set")
        if not title or not date_str or not exercise_name or not set_no_str:
            summary["rows_skipped"] += 1
            continue

        try:
            workout_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            set_no = int(set_no_str)
            reps = _parse_optional_int(get_cell(row, "reps"))
            duration_seconds = _parse_optional_int(get_cell(row, "duration_seconds", "duration seconds"))
            weight_kg = _parse_optional_float(get_cell(row, "weight_kg", "weight kg", "weight")) or 0.0
            rpe = _parse_optional_float(get_cell(row, "rpe"))
            duration_minutes = _parse_optional_int(get_cell(row, "duration", "duration_minutes"))
        except ValueError:
            summary["rows_skipped"] += 1
            continue

        if reps is None and duration_seconds is None:
            summary["rows_skipped"] += 1
            continue
        if reps is not None and duration_seconds is not None:
            summary["rows_skipped"] += 1
            continue

        workout_notes = get_cell(row, "workout_notes", "workout notes", "notes") or None
        workout_key = (workout_date, title, duration_minutes, workout_notes)
        workout = workout_cache.get(workout_key)
        if workout is None:
            workout = Workout.query.filter_by(
                user_id=user_id,
                workout_date=workout_date,
                title=title,
            ).first()
            if workout is None:
                workout = Workout(
                    user_id=user_id,
                    title=title,
                    workout_date=workout_date,
                    duration_minutes=duration_minutes,
                    notes=workout_notes,
                )
                db.session.add(workout)
                db.session.flush()
                summary["workouts_created"] += 1
            workout_cache[workout_key] = workout

        exercise = ensure_exercise(exercise_name)
        if skip_existing_sets:
            existing = SetEntry.query.filter_by(
                user_id=user_id,
                workout_id=workout.id,
                exercise_id=exercise.id,
                set_no=set_no,
            ).first()
            if existing is not None:
                summary["sets_skipped_existing"] += 1
                continue

        db.session.add(
            SetEntry(
                user_id=user_id,
                workout_id=workout.id,
                exercise_id=exercise.id,
                set_no=set_no,
                reps=reps,
                duration_seconds=duration_seconds,
                weight_kg=weight_kg,
                rpe=rpe,
            )
        )
        summary["sets_created"] += 1

    return summary


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


@bp.get("/export/workouts.json")
@login_required
def export_workouts_json():
    user = require_user()
    payload = _export_workouts_payload(user.id)
    filename = f"workout_export_{date.today().isoformat()}.json"
    return Response(
        json.dumps(payload, ensure_ascii=False, indent=2),
        mimetype="application/json",
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


@bp.get("/import")
@login_required
def import_tools():
    return render_template(
        "workouts/import.html",
        json_summary=None,
        csv_summary=None,
        json_preview=None,
        json_text_value="",
        json_default_plan_strategy="merge",
        json_default_strategy="skip",
        json_plan_strategies={},
        json_workout_strategies={},
    )


@bp.post("/import/workouts.json")
@login_required
def import_workouts_json():
    user = require_user()
    raw_text = _read_upload_text("json_file", "json_text")
    dry_run = bool(request.form.get("dry_run"))
    default_plan_strategy = (request.form.get("default_plan_conflict_strategy") or "merge").strip().lower()
    if default_plan_strategy not in {"skip", "merge", "replace"}:
        default_plan_strategy = "merge"
    default_strategy = (request.form.get("default_workout_conflict_strategy") or "skip").strip().lower()
    if default_strategy not in {"skip", "merge", "replace"}:
        default_strategy = "skip"
    plan_strategy_overrides = {}
    for key, value in request.form.items():
        if not key.startswith("plan_strategy_"):
            continue
        idx_part = key.removeprefix("plan_strategy_")
        if idx_part.isdigit():
            choice = (value or "").strip().lower()
            if choice in {"skip", "merge", "replace"}:
                plan_strategy_overrides[int(idx_part)] = choice
    workout_strategy_overrides = {}
    for key, value in request.form.items():
        if not key.startswith("workout_strategy_"):
            continue
        idx_part = key.removeprefix("workout_strategy_")
        if idx_part.isdigit():
            choice = (value or "").strip().lower()
            if choice in {"skip", "merge", "replace"}:
                workout_strategy_overrides[int(idx_part)] = choice

    json_summary = None
    csv_summary = None
    json_preview = None
    try:
        if not raw_text.strip():
            raise ValueError("Provide JSON via file upload or paste JSON text.")
        payload = json.loads(raw_text)
        if request.form.get("preview_json"):
            json_preview = _preview_workouts_json_payload(payload, user_id=user.id)
            flash("JSON preview generated. No data was saved.", "success")
            return render_template(
                "workouts/import.html",
                json_summary=None,
                csv_summary=None,
                json_preview=json_preview,
                json_text_value=raw_text,
                json_default_plan_strategy=default_plan_strategy,
                json_default_strategy=default_strategy,
                json_plan_strategies=plan_strategy_overrides,
                json_workout_strategies=workout_strategy_overrides,
            )
        summary = _import_workouts_json_payload(
            user.id,
            payload,
            default_plan_conflict_strategy=default_plan_strategy,
            plan_strategies=plan_strategy_overrides,
            default_workout_conflict_strategy=default_strategy,
            workout_strategies=workout_strategy_overrides,
        )
        json_summary = {
            "dry_run": dry_run,
            "default_plan_conflict_strategy": default_plan_strategy,
            "default_workout_conflict_strategy": default_strategy,
            "summary": summary,
        }
        if dry_run:
            db.session.rollback()
            flash("JSON import dry-run complete. No data was saved.", "success")
        else:
            db.session.commit()
            flash("JSON import completed.", "success")
    except Exception as exc:  # Keep import UX simple with one error surface.
        db.session.rollback()
        flash(f"JSON import failed: {exc}", "error")

    return render_template(
        "workouts/import.html",
        json_summary=json_summary,
        csv_summary=csv_summary,
        json_preview=json_preview,
        json_text_value=raw_text,
        json_default_plan_strategy=default_plan_strategy,
        json_default_strategy=default_strategy,
        json_plan_strategies=plan_strategy_overrides,
        json_workout_strategies=workout_strategy_overrides,
    )


@bp.post("/import/sets.csv")
@login_required
def import_sets_csv():
    user = require_user()
    raw_text = _read_upload_text("csv_file", "csv_text")
    dry_run = bool(request.form.get("dry_run"))
    skip_existing_sets = bool(request.form.get("skip_existing_sets")) or "skip_existing_sets" not in request.form

    json_summary = None
    csv_summary = None
    json_preview = None
    try:
        summary = _import_sets_csv_text(user.id, raw_text, skip_existing_sets=skip_existing_sets)
        csv_summary = {
            "dry_run": dry_run,
            "skip_existing_sets": skip_existing_sets,
            "summary": summary,
        }
        if dry_run:
            db.session.rollback()
            flash("CSV import dry-run complete. No data was saved.", "success")
        else:
            db.session.commit()
            flash("CSV import completed.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"CSV import failed: {exc}", "error")

    return render_template(
        "workouts/import.html",
        json_summary=json_summary,
        csv_summary=csv_summary,
        json_preview=json_preview,
        json_text_value="",
        json_default_plan_strategy="merge",
        json_default_strategy="skip",
        json_plan_strategies={},
        json_workout_strategies={},
    )
