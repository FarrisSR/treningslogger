from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy.orm import joinedload

from ..models import SetEntry, Workout


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def weekly_volume_points(user_id: int):
    rows = (
        SetEntry.query.join(Workout, SetEntry.workout_id == Workout.id)
        .filter(SetEntry.user_id == user_id, Workout.user_id == user_id)
        .options(joinedload(SetEntry.workout))
        .order_by(Workout.workout_date.asc())
        .all()
    )
    totals = defaultdict(float)
    for row in rows:
        if row.workout is None:
            continue
        totals[_week_start(row.workout.workout_date)] += (row.reps or 0) * (row.weight_kg or 0)
    return sorted(totals.items(), key=lambda item: item[0])


def pr_estimate_points(user_id: int):
    rows = (
        SetEntry.query.join(Workout, SetEntry.workout_id == Workout.id)
        .filter(SetEntry.user_id == user_id, Workout.user_id == user_id, SetEntry.reps > 0)
        .options(joinedload(SetEntry.workout))
        .order_by(Workout.workout_date.asc())
        .all()
    )
    best_by_day = defaultdict(float)
    for row in rows:
        if row.workout is None:
            continue
        est_1rm = (row.weight_kg or 0) * (1 + (row.reps or 0) / 30.0)
        day = row.workout.workout_date
        if est_1rm > best_by_day[day]:
            best_by_day[day] = est_1rm
    return sorted(best_by_day.items(), key=lambda item: item[0])
