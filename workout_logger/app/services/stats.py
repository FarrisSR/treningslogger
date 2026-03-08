from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy.orm import joinedload

from ..models import Exercise, SetEntry, Workout


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


def weekly_duration_points(user_id: int):
    rows = (
        SetEntry.query.join(Workout, SetEntry.workout_id == Workout.id)
        .filter(SetEntry.user_id == user_id, Workout.user_id == user_id, SetEntry.duration_seconds.isnot(None))
        .options(joinedload(SetEntry.workout))
        .order_by(Workout.workout_date.asc())
        .all()
    )
    totals = defaultdict(int)
    for row in rows:
        if row.workout is None or row.duration_seconds is None:
            continue
        totals[_week_start(row.workout.workout_date)] += int(row.duration_seconds)
    return sorted(totals.items(), key=lambda item: item[0])


def exercise_overview_rows(user_id: int):
    rows = (
        SetEntry.query.join(Workout, SetEntry.workout_id == Workout.id)
        .join(Exercise, SetEntry.exercise_id == Exercise.id)
        .filter(SetEntry.user_id == user_id, Workout.user_id == user_id, Exercise.user_id == user_id)
        .order_by(Exercise.name.asc(), Workout.workout_date.asc(), SetEntry.set_no.asc(), SetEntry.id.asc())
        .with_entities(
            Exercise.name,
            Workout.workout_date,
            SetEntry.reps,
            SetEntry.duration_seconds,
            SetEntry.weight_kg,
            SetEntry.rpe,
        )
        .all()
    )

    summary: dict[str, dict] = {}
    for name, workout_date, reps, duration_seconds, weight_kg, rpe in rows:
        item = summary.setdefault(
            name,
            {
                "exercise": name,
                "set_count": 0,
                "rep_set_count": 0,
                "total_reps": 0,
                "best_weight_kg": 0.0,
                "last_weight_kg": 0.0,
                "last_date": None,
                "total_duration_seconds": 0,
                "rpe_sum": 0.0,
                "rpe_count": 0,
            },
        )
        item["set_count"] += 1
        item["best_weight_kg"] = max(float(item["best_weight_kg"]), float(weight_kg or 0.0))
        item["last_weight_kg"] = float(weight_kg or 0.0)
        item["last_date"] = workout_date
        if reps is not None:
            item["rep_set_count"] += 1
            item["total_reps"] += int(reps)
        if duration_seconds is not None:
            item["total_duration_seconds"] += int(duration_seconds)
        if rpe is not None:
            item["rpe_sum"] += float(rpe)
            item["rpe_count"] += 1

    result = []
    for item in summary.values():
        rep_set_count = int(item["rep_set_count"])
        rpe_count = int(item["rpe_count"])
        result.append(
            {
                "exercise": item["exercise"],
                "set_count": int(item["set_count"]),
                "total_reps": int(item["total_reps"]),
                "avg_reps": (item["total_reps"] / rep_set_count) if rep_set_count else None,
                "best_weight_kg": float(item["best_weight_kg"]),
                "last_weight_kg": float(item["last_weight_kg"]),
                "last_date": item["last_date"],
                "total_duration_seconds": int(item["total_duration_seconds"]),
                "avg_rpe": (item["rpe_sum"] / rpe_count) if rpe_count else None,
            }
        )
    return sorted(result, key=lambda row: row["exercise"].lower())
