import os
from pathlib import Path

from flask import Flask, g, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text


db = SQLAlchemy()


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")
    BASE_DIR = Path(__file__).resolve().parents[2]
    INSTANCE_DIR = BASE_DIR / "instance"
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{(INSTANCE_DIR / 'workout_logger.db').as_posix()}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JSON_SORT_KEYS = False


def _ensure_set_entry_schema() -> None:
    # Lightweight SQLite migration for early-stage schema changes without Alembic.
    engine = db.engine
    if engine.url.get_backend_name() != "sqlite":
        return

    with engine.begin() as conn:
        table_exists = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='set_entry'")
        ).first()
        if not table_exists:
            return

        columns = conn.execute(text("PRAGMA table_info(set_entry)")).mappings().all()
        if not columns:
            return

        has_duration = any(col["name"] == "duration_seconds" for col in columns)
        reps_col = next((col for col in columns if col["name"] == "reps"), None)
        reps_nullable = bool(reps_col and reps_col["notnull"] == 0)
        if has_duration and reps_nullable:
            return

        conn.execute(text("PRAGMA foreign_keys=OFF"))
        conn.execute(
            text(
                """
                CREATE TABLE set_entry_new (
                    id INTEGER NOT NULL PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    workout_id INTEGER NOT NULL,
                    exercise_id INTEGER NOT NULL,
                    set_no INTEGER NOT NULL,
                    reps INTEGER,
                    duration_seconds INTEGER,
                    weight_kg FLOAT NOT NULL,
                    rpe FLOAT,
                    created_at DATETIME NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES user (id) ON DELETE CASCADE,
                    FOREIGN KEY(workout_id) REFERENCES workout (id) ON DELETE CASCADE,
                    FOREIGN KEY(exercise_id) REFERENCES exercise (id) ON DELETE CASCADE
                )
                """
            )
        )
        if has_duration:
            conn.execute(
                text(
                    """
                    INSERT INTO set_entry_new
                    (id, user_id, workout_id, exercise_id, set_no, reps, duration_seconds, weight_kg, rpe, created_at)
                    SELECT id, user_id, workout_id, exercise_id, set_no, reps, duration_seconds, weight_kg, rpe, created_at
                    FROM set_entry
                    """
                )
            )
        else:
            conn.execute(
                text(
                    """
                    INSERT INTO set_entry_new
                    (id, user_id, workout_id, exercise_id, set_no, reps, duration_seconds, weight_kg, rpe, created_at)
                    SELECT id, user_id, workout_id, exercise_id, set_no, reps, NULL, weight_kg, rpe, created_at
                    FROM set_entry
                    """
                )
            )
        conn.execute(text("DROP TABLE set_entry"))
        conn.execute(text("ALTER TABLE set_entry_new RENAME TO set_entry"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_set_entry_user_id ON set_entry (user_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_set_entry_workout_id ON set_entry (workout_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_set_entry_exercise_id ON set_entry (exercise_id)"))
        conn.execute(text("PRAGMA foreign_keys=ON"))


def _ensure_plan_exercise_schema() -> None:
    engine = db.engine
    if engine.url.get_backend_name() != "sqlite":
        return
    with engine.begin() as conn:
        table_exists = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='plan_exercise'")
        ).first()
        if not table_exists:
            return
        columns = conn.execute(text("PRAGMA table_info(plan_exercise)")).mappings().all()
        names = {col["name"] for col in columns}
        if "group_key" not in names:
            conn.execute(text("ALTER TABLE plan_exercise ADD COLUMN group_key VARCHAR(80)"))
        if "side" not in names:
            conn.execute(text("ALTER TABLE plan_exercise ADD COLUMN side VARCHAR(16)"))


def _format_duration_seconds(value: int | None) -> str:
    if value is None:
        return ""
    try:
        total = int(value)
    except (TypeError, ValueError):
        return ""
    if total < 0:
        return ""
    minutes, seconds = divmod(total, 60)
    if minutes and seconds:
        return f"{minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m"
    return f"{seconds}s"



def create_app(config_object: type[Config] = Config) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object)
    Path(app.config["INSTANCE_DIR"]).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    app.jinja_env.filters["fmt_duration"] = _format_duration_seconds

    from .models import User, UserProfile  # noqa: F401

    @app.before_request
    def load_current_user_and_init_db() -> None:
        if not app.extensions.get("_tables_ready"):
            db.create_all()
            _ensure_set_entry_schema()
            _ensure_plan_exercise_schema()
            app.extensions["_tables_ready"] = True
        user_id = session.get("user_id")
        g.current_user = User.query.filter_by(id=user_id).first() if user_id else None
        g.current_user_profile = (
            UserProfile.query.filter_by(user_id=user_id).first() if user_id else None
        )

    from .routes.api import bp as api_bp
    from .routes.auth import bp as auth_bp
    from .routes.plans import bp as plans_bp
    from .routes.stats import bp as stats_bp
    from .routes.timer import bp as timer_bp
    from .routes.workouts import bp as workouts_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(workouts_bp)
    app.register_blueprint(plans_bp)
    app.register_blueprint(stats_bp)
    app.register_blueprint(timer_bp)
    app.register_blueprint(api_bp)

    return app
