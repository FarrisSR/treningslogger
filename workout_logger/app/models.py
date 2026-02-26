from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import validates

from . import db


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    exercises = db.relationship("Exercise", back_populates="user", cascade="all, delete-orphan")
    workout_plans = db.relationship("WorkoutPlan", back_populates="user", cascade="all, delete-orphan")
    workouts = db.relationship("Workout", back_populates="user", cascade="all, delete-orphan")
    profile = db.relationship("UserProfile", back_populates="user", uselist=False, cascade="all, delete-orphan")


class UserProfile(db.Model):
    __table_args__ = (UniqueConstraint("user_id", name="uq_user_profile_user_id"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    workout_view_mode = db.Column(db.String(20), nullable=False, default="accordion")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship("User", back_populates="profile")


class Exercise(db.Model):
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_exercise_user_name"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    user = db.relationship("User", back_populates="exercises")
    plan_exercises = db.relationship("PlanExercise", back_populates="exercise")
    set_entries = db.relationship("SetEntry", back_populates="exercise")
    workout_notes = db.relationship("WorkoutExerciseNote", back_populates="exercise")

    @validates("name")
    def normalize_name(self, _key: str, value: str) -> str:
        return " ".join(value.strip().split())


class WorkoutPlan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    user = db.relationship("User", back_populates="workout_plans")
    exercises = db.relationship(
        "PlanExercise",
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="PlanExercise.position",
    )
    workouts = db.relationship("Workout", back_populates="plan")


class PlanExercise(db.Model):
    __table_args__ = (UniqueConstraint("plan_id", "exercise_id", name="uq_plan_exercise"),)

    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey("workout_plan.id", ondelete="CASCADE"), nullable=False, index=True)
    exercise_id = db.Column(db.Integer, db.ForeignKey("exercise.id", ondelete="CASCADE"), nullable=False, index=True)
    position = db.Column(db.Integer, nullable=False, default=0)
    target_sets = db.Column(db.Integer, nullable=True)
    target_reps = db.Column(db.String(40), nullable=True)
    group_key = db.Column(db.String(80), nullable=True)
    side = db.Column(db.String(16), nullable=True)

    plan = db.relationship("WorkoutPlan", back_populates="exercises")
    exercise = db.relationship("Exercise", back_populates="plan_exercises")


class Workout(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    plan_id = db.Column(db.Integer, db.ForeignKey("workout_plan.id", ondelete="SET NULL"), nullable=True, index=True)
    title = db.Column(db.String(160), nullable=False)
    workout_date = db.Column(db.Date, nullable=False, default=date.today, index=True)
    duration_minutes = db.Column(db.Integer, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship("User", back_populates="workouts")
    plan = db.relationship("WorkoutPlan", back_populates="workouts")
    sets = db.relationship(
        "SetEntry",
        back_populates="workout",
        cascade="all, delete-orphan",
        order_by="SetEntry.id",
    )
    exercise_notes = db.relationship(
        "WorkoutExerciseNote",
        back_populates="workout",
        cascade="all, delete-orphan",
    )


class SetEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    workout_id = db.Column(db.Integer, db.ForeignKey("workout.id", ondelete="CASCADE"), nullable=False, index=True)
    exercise_id = db.Column(db.Integer, db.ForeignKey("exercise.id", ondelete="CASCADE"), nullable=False, index=True)
    set_no = db.Column(db.Integer, nullable=False)
    reps = db.Column(db.Integer, nullable=True)
    duration_seconds = db.Column(db.Integer, nullable=True)
    weight_kg = db.Column(db.Float, nullable=False, default=0.0)
    rpe = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    workout = db.relationship("Workout", back_populates="sets")
    exercise = db.relationship("Exercise", back_populates="set_entries")


class WorkoutExerciseNote(db.Model):
    __table_args__ = (UniqueConstraint("workout_id", "exercise_id", name="uq_workout_exercise_note"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    workout_id = db.Column(db.Integer, db.ForeignKey("workout.id", ondelete="CASCADE"), nullable=False, index=True)
    exercise_id = db.Column(db.Integer, db.ForeignKey("exercise.id", ondelete="CASCADE"), nullable=False, index=True)
    note = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    workout = db.relationship("Workout", back_populates="exercise_notes")
    exercise = db.relationship("Exercise", back_populates="workout_notes")
