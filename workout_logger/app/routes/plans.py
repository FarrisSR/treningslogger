from __future__ import annotations

from datetime import date

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from .. import db
from ..models import Exercise, PlanExercise, Workout, WorkoutPlan
from . import login_required, require_user

bp = Blueprint("plans", __name__, url_prefix="/plans")


def _user_plan_or_404(user_id: int, plan_id: int) -> WorkoutPlan:
    plan = WorkoutPlan.query.filter_by(id=plan_id, user_id=user_id).first()
    if plan is None:
        abort(404)
    return plan


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


def _parse_plan_exercise_lines(user_id: int, plan: WorkoutPlan, exercise_lines: list[str]) -> None:
    seen = set()
    for position, line in enumerate(exercise_lines, start=1):
        parts = [part.strip() for part in line.split("|")]
        exercise_name = parts[0]
        key = exercise_name.lower()
        if key in seen:
            continue
        seen.add(key)
        exercise = _get_or_create_exercise(user_id, exercise_name)
        if exercise is None:
            continue
        target_sets = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
        target_reps = parts[2] if len(parts) > 2 and parts[2] else None
        group_key = parts[3] if len(parts) > 3 and parts[3] else None
        side = (parts[4].lower() if len(parts) > 4 and parts[4] else None)
        if side not in {None, "left", "right", "both"}:
            side = None
        db.session.add(
            PlanExercise(
                plan_id=plan.id,
                exercise_id=exercise.id,
                position=position,
                target_sets=target_sets,
                target_reps=target_reps,
                group_key=group_key,
                side=side,
            )
        )


def _plan_exercises_text(plan: WorkoutPlan) -> str:
    lines = []
    for pe in plan.exercises:
        if pe.exercise is None:
            continue
        parts = [pe.exercise.name]
        if pe.target_sets is not None or pe.target_reps is not None or pe.group_key or pe.side:
            parts.append(str(pe.target_sets) if pe.target_sets is not None else "")
            parts.append(pe.target_reps or "")
        if pe.group_key or pe.side:
            parts.append(pe.group_key or "")
            parts.append(pe.side or "")
        lines.append("|".join(parts))
    return "\n".join(lines)


@bp.get("")
@login_required
def list_plans():
    user = require_user()
    plans = (
        WorkoutPlan.query.filter_by(user_id=user.id)
        .order_by(WorkoutPlan.created_at.desc())
        .all()
    )
    return render_template("plans/list.html", plans=plans)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def create_plan():
    user = require_user()
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        description = (request.form.get("description") or "").strip() or None
        exercise_lines = [line.strip() for line in (request.form.get("exercises") or "").splitlines() if line.strip()]

        if not name:
            flash("Plan name is required.", "error")
            return render_template("plans/form.html", form_data=request.form, is_edit=False, plan=None)

        plan = WorkoutPlan(user_id=user.id, name=name, description=description)
        db.session.add(plan)
        db.session.flush()

        _parse_plan_exercise_lines(user.id, plan, exercise_lines)

        db.session.commit()
        return redirect(url_for("plans.view_plan", plan_id=plan.id))

    return render_template("plans/form.html", form_data=None, is_edit=False, plan=None)


@bp.route("/<int:plan_id>/edit", methods=["GET", "POST"])
@login_required
def edit_plan(plan_id: int):
    user = require_user()
    plan = _user_plan_or_404(user.id, plan_id)

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        description = (request.form.get("description") or "").strip() or None
        exercise_lines = [line.strip() for line in (request.form.get("exercises") or "").splitlines() if line.strip()]
        if not name:
            flash("Plan name is required.", "error")
            return render_template("plans/form.html", form_data=request.form, is_edit=True, plan=plan)

        plan.name = name
        plan.description = description
        plan.exercises.clear()
        db.session.flush()
        _parse_plan_exercise_lines(user.id, plan, exercise_lines)
        db.session.commit()
        flash("Bygger oppdatert.", "success")
        return redirect(url_for("plans.view_plan", plan_id=plan.id))

    initial_form = {
        "name": plan.name,
        "description": plan.description or "",
        "exercises": _plan_exercises_text(plan),
    }
    return render_template("plans/form.html", form_data=initial_form, is_edit=True, plan=plan)


@bp.get("/<int:plan_id>")
@login_required
def view_plan(plan_id: int):
    user = require_user()
    plan = _user_plan_or_404(user.id, plan_id)
    return render_template("plans/detail.html", plan=plan)


@bp.post("/<int:plan_id>/start")
@login_required
def start_workout_from_plan(plan_id: int):
    user = require_user()
    plan = _user_plan_or_404(user.id, plan_id)

    workout = Workout(
        user_id=user.id,
        plan_id=plan.id,
        title=plan.name,
        workout_date=date.today(),
    )
    db.session.add(workout)
    db.session.commit()
    flash("Workout created from plan.", "success")
    return redirect(url_for("workouts.view_workout", workout_id=workout.id))
