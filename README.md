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
- `scripts/deploy.sh` simple deploy script for test/prod sync
- `Makefile` wrapper for deploy commands

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

## Deploy

Utvikling skjer i dette repoet. Deploy skjer til egne kataloger:

- `make test` kopierer nødvendige runtime-filer til `/opt/test-treningslogger`
- `make prod` kjører først `make test`, og kopierer deretter samme runtime-filer til `/opt/treningslogger`

Deploy-scriptet kopierer disse filene:

- `workout_logger/`
- `run.py`
- `requirements.txt`
- `gunicorn.conf.py`

Deploy-scriptet kopierer ikke:

- `.env`
- `.venv`
- `instance/`
- `deploy/`
- `scripts/`

## Production (Ubuntu + Gunicorn + Nginx)

1. Kjør `make prod` for å kopiere appen til `/opt/treningslogger`.
2. Opprett virtualenv i `/opt/treningslogger/.venv` og installer dependencies med `pip install -r requirements.txt`.
3. Create `/opt/treningslogger/.env` with a strong `SECRET_KEY`.
4. Test Gunicorn manually:

```bash
gunicorn -c gunicorn.conf.py run:app
```

5. Install the example `systemd` unit:

```bash
sudo cp deploy/systemd/treningslogger.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now treningslogger
```

The service unit sets `MPLCONFIGDIR` to a writable runtime directory under `/run/` so Matplotlib can render charts without permission warnings.

6. Install the example Nginx site:

```bash
sudo cp deploy/nginx/treningslogger.conf /etc/nginx/sites-available/treningslogger
sudo ln -s /etc/nginx/sites-available/treningslogger /etc/nginx/sites-enabled/treningslogger
sudo nginx -t
sudo systemctl reload nginx
```

## Security Notes

- Set `SECRET_KEY` in the environment for production.
- Passwords are hashed using Werkzeug.
- All app routes and API endpoints enforce user ownership filtering on workout data.
- This project is designed for self-hosted/private use.
