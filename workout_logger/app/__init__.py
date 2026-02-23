import os
from pathlib import Path

from flask import Flask, g, session
from flask_sqlalchemy import SQLAlchemy


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



def create_app(config_object: type[Config] = Config) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object)
    Path(app.config["INSTANCE_DIR"]).mkdir(parents=True, exist_ok=True)

    db.init_app(app)

    from .models import User  # noqa: F401

    @app.before_request
    def load_current_user_and_init_db() -> None:
        if not app.extensions.get("_tables_ready"):
            db.create_all()
            app.extensions["_tables_ready"] = True
        user_id = session.get("user_id")
        g.current_user = User.query.filter_by(id=user_id).first() if user_id else None

    from .routes.api import bp as api_bp
    from .routes.auth import bp as auth_bp
    from .routes.plans import bp as plans_bp
    from .routes.stats import bp as stats_bp
    from .routes.workouts import bp as workouts_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(workouts_bp)
    app.register_blueprint(plans_bp)
    app.register_blueprint(stats_bp)
    app.register_blueprint(api_bp)

    return app
