# AGENTS.md

## Architecture Overview

This repository contains a small Flask application using the application factory pattern.

### Main Components

- `workout_logger/app/__init__.py`
  - Defines `db` (`Flask-SQLAlchemy`) and `create_app()`.
  - Loads config from environment.
  - Auto-creates SQLite tables on first request.
  - Registers blueprints.

- `workout_logger/app/models.py`
  - SQLAlchemy models for users, exercises, plans, workouts, sets, and per-exercise notes.
  - Data is user-scoped (queries should always filter by `user_id`).

- `workout_logger/app/routes/`
  - `auth.py`: register/login/logout
  - `workouts.py`: dashboard, workout CRUD/logging, CSV/XLSX exports
  - `plans.py`: plan CRUD and start workout from plan
  - `stats.py`: stats page + server-rendered PNG chart endpoints
  - `api.py`: exercise history hint and per-exercise note JSON endpoints

- `workout_logger/app/services/`
  - `history.py`: previous workout selection logic
  - `stats.py`: weekly volume and Epley 1RM aggregation

- `workout_logger/app/templates/`
  - Server-rendered HTML (Jinja)

- `workout_logger/app/static/js/workout_detail.js`
  - Vanilla JS for exercise hint loading and debounced note save

## Developer Notes

- Keep the app simple and maintainable: server-rendered pages, vanilla JS only.
- Avoid introducing frontend frameworks.
- Prefer explicit user ownership filtering on all data access.
- If adding features, keep them blueprint/service-scoped to avoid circular imports.
- The project currently uses `db.create_all()` at runtime instead of migrations; `workout_logger/migrations/` is a placeholder for future migration tooling.
