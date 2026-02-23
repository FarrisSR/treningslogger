from __future__ import annotations

from flask import Blueprint, abort, jsonify, request

from .. import db
from ..models import Exercise, SetEntry, Workout, WorkoutExerciseNote
from ..services.history import get_previous_workout
from . import login_required, require_user

bp = Blueprint("api", __name__, url_prefix="/api")


def _user_workout_or_404(user_id: int, workout_id: int) -> Workout:
    workout = Workout.query.filter_by(id=workout_id, user_id=user_id).first()
    if workout is None:
        abort(404)
    return workout


def _user_exercise_or_404(user_id: int, exercise_id: int) -> Exercise:
    exercise = Exercise.query.filter_by(id=exercise_id, user_id=user_id).first()
    if exercise is None:
        abort(404)
    return exercise


@bp.get("/workouts/<int:workout_id>/exercise_hint")
@login_required
def exercise_hint(workout_id: int):
    user = require_user()
    workout = _user_workout_or_404(user.id, workout_id)

    exercise_id_raw = request.args.get("exercise_id", "")
    if not exercise_id_raw.isdigit():
        return jsonify({"error": "exercise_id is required"}), 400
    exercise = _user_exercise_or_404(user.id, int(exercise_id_raw))

    previous_workout = get_previous_workout(user.id, workout)
    previous_payload = None
    previous_note = None

    if previous_workout is not None:
        previous_sets = (
            SetEntry.query.filter_by(
                user_id=user.id,
                workout_id=previous_workout.id,
                exercise_id=exercise.id,
            )
            .order_by(SetEntry.set_no.asc(), SetEntry.id.asc())
            .all()
        )
        previous_payload = {
            "workout_id": previous_workout.id,
            "workout_date": previous_workout.workout_date.isoformat(),
            "title": previous_workout.title,
            "sets": [
                {
                    "set_no": s.set_no,
                    "reps": s.reps,
                    "weight_kg": s.weight_kg,
                    "rpe": s.rpe,
                }
                for s in previous_sets
            ],
        }
        prev_note_row = WorkoutExerciseNote.query.filter_by(
            user_id=user.id,
            workout_id=previous_workout.id,
            exercise_id=exercise.id,
        ).first()
        previous_note = prev_note_row.note if prev_note_row else None

    current_note_row = WorkoutExerciseNote.query.filter_by(
        user_id=user.id,
        workout_id=workout.id,
        exercise_id=exercise.id,
    ).first()

    return jsonify(
        {
            "exercise": exercise.name,
            "previous": previous_payload,
            "previous_note": previous_note,
            "current_note": current_note_row.note if current_note_row else None,
        }
    )


@bp.post("/workouts/<int:workout_id>/exercise_note")
@login_required
def save_exercise_note(workout_id: int):
    user = require_user()
    workout = _user_workout_or_404(user.id, workout_id)
    payload = request.get_json(silent=True) or {}

    exercise_id = payload.get("exercise_id")
    if not isinstance(exercise_id, int):
        return jsonify({"error": "exercise_id must be an integer"}), 400
    exercise = _user_exercise_or_404(user.id, exercise_id)

    note = (payload.get("note") or "")
    if not isinstance(note, str):
        return jsonify({"error": "note must be a string"}), 400
    note = note.strip()

    row = WorkoutExerciseNote.query.filter_by(
        user_id=user.id,
        workout_id=workout.id,
        exercise_id=exercise.id,
    ).first()
    if row is None and note:
        row = WorkoutExerciseNote(
            user_id=user.id,
            workout_id=workout.id,
            exercise_id=exercise.id,
            note=note,
        )
        db.session.add(row)
    elif row is not None and note:
        row.note = note
    elif row is not None and not note:
        db.session.delete(row)

    db.session.commit()
    return jsonify({"status": "ok", "exercise": exercise.name, "note": note or None})
