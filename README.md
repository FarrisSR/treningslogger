# Workout Logger

Workout Logger is a self-hosted Flask application for logging workouts, tracking per-exercise notes, comparing against your previous matching session, and exporting your set history.

## Features

- Local username/password authentication (session-based)
- Workout plans (templates)
- Workout logging with sets, reps, weight, and RPE
- Per-exercise notes within each workout
- Previous-session comparison (plan-based first, fallback to title)
- Statistics charts (weekly volume and Epley 1RM estimate)
- CSV (streaming) and Excel exports
- SQLite storage
- Gunicorn + Nginx deployment examples

## Project Layout

- `workout_logger/app/` Flask app package (factory, models, routes, services, templates, static JS)
- `workout_logger/migrations/` placeholder for future migrations
- `run.py` local entry point
- `gunicorn.conf.py` production Gunicorn config
- `deploy/` example `systemd` and Nginx configs

## Local Setup

1. Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Configure environment:

```bash
cp .env.example .env
export SECRET_KEY="replace-with-a-long-random-string"
```

3. Run the app:

```bash
python run.py
```

The SQLite database file is created automatically in `instance/workout_logger.db`. Tables are created automatically on the first request (`db.create_all()` behavior via `before_request`).

## Usage Notes

- Create an account from `/register`
- Create a plan (optional)
- Create a workout or start one from a plan
- On the workout page, select an exercise to see the previous matching session and notes
- Exports are available in the top navigation once logged in

## Production (Ubuntu + Gunicorn + Nginx)

1. Copy the app to `/opt/workout-logger` and create a virtual environment.
2. Install dependencies with `pip install -r requirements.txt`.
3. Create `/opt/workout-logger/.env` with a strong `SECRET_KEY`.
4. Test Gunicorn manually:

```bash
gunicorn -c gunicorn.conf.py run:app
```

5. Install the example `systemd` unit:

```bash
sudo cp deploy/systemd/workout-logger.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now workout-logger
```

6. Install the example Nginx site:

```bash
sudo cp deploy/nginx/workout-logger.conf /etc/nginx/sites-available/workout-logger
sudo ln -s /etc/nginx/sites-available/workout-logger /etc/nginx/sites-enabled/workout-logger
sudo nginx -t
sudo systemctl reload nginx
```

## Security Notes

- Set `SECRET_KEY` in the environment for production.
- Passwords are hashed using Werkzeug.
- All app routes and API endpoints enforce user ownership filtering on workout data.
- This project is designed for self-hosted/private use.
