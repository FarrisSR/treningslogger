from __future__ import annotations

from sqlalchemy import func

from ..models import Workout


def get_previous_workout(user_id: int, workout: Workout) -> Workout | None:
    query = Workout.query.filter(
        Workout.user_id == user_id,
        Workout.id != workout.id,
    )

    if workout.plan_id:
        query = query.filter(Workout.plan_id == workout.plan_id)
    else:
        normalized_title = (workout.title or "").strip().lower()
        if not normalized_title:
            return None
        query = query.filter(func.lower(Workout.title) == normalized_title)

    return (
        query.order_by(Workout.workout_date.desc(), Workout.created_at.desc())
        .first()
    )
