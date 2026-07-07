from __future__ import annotations

from io import BytesIO

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from flask import Blueprint, Response, render_template, request

from ..services.stats import (
    exercise_overview_rows,
    exercise_progress_points,
    exercise_rep_choices,
    session_duration_points,
    session_pr_estimate_points,
    session_volume_points,
)
from . import login_required, require_user

bp = Blueprint("stats", __name__, url_prefix="/stats")


def _line_chart_png(points, title: str, ylabel: str, color: str) -> bytes:
    fig, ax = plt.subplots(figsize=(8, 3.8), dpi=120)
    if points:
        x_vals = list(range(len(points)))
        labels = [p[0] for p in points]
        y_vals = [p[1] for p in points]
        ax.plot(x_vals, y_vals, marker="o", linewidth=2, color=color)
        tick_step = max(1, len(labels) // 8)
        tick_indexes = list(range(0, len(labels), tick_step))
        if tick_indexes[-1] != len(labels) - 1:
            tick_indexes.append(len(labels) - 1)
        ax.set_xticks(tick_indexes)
        ax.set_xticklabels([labels[idx] for idx in tick_indexes], rotation=35, ha="right")
    else:
        ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _selected_exercise_id(raw_value: str | None, choices: list[dict[str, object]]) -> int | None:
    if not choices:
        return None
    try:
        selected = int(raw_value) if raw_value else int(choices[0]["id"])
    except (TypeError, ValueError):
        selected = int(choices[0]["id"])
    valid_ids = {int(item["id"]) for item in choices}
    return selected if selected in valid_ids else int(choices[0]["id"])


def _selected_metric(raw_value: str | None) -> str:
    return raw_value if raw_value in {"volume", "top_set"} else "volume"


def _exercise_chart_title(metric: str, period: str) -> str:
    labels = {
        "volume": {"session": "Exercise Load per Session", "week": "Exercise Load per Week"},
        "top_set": {"session": "Top Set Weight per Session", "week": "Top Set Weight per Week"},
    }
    return labels[metric][period]


def _exercise_chart_ylabel(metric: str) -> str:
    return "Top Weight (kg)" if metric == "top_set" else "Reps x Weight (kg)"


@bp.get("")
@login_required
def stats_index():
    user = require_user()
    exercise_choices = exercise_rep_choices(user.id)
    selected_period = request.args.get("exercise_period", "session")
    if selected_period not in {"session", "week"}:
        selected_period = "session"
    selected_metric = _selected_metric(request.args.get("exercise_metric"))
    selected_exercise_id = _selected_exercise_id(request.args.get("exercise_id"), exercise_choices)
    return render_template(
        "stats/index.html",
        exercise_rows=exercise_overview_rows(user.id),
        exercise_choices=exercise_choices,
        selected_exercise_id=selected_exercise_id,
        selected_exercise_period=selected_period,
        selected_exercise_metric=selected_metric,
    )


@bp.get("/volume.png")
@login_required
def volume_png():
    user = require_user()
    png = _line_chart_png(
        session_volume_points(user.id),
        title="Volume per Session",
        ylabel="Reps x Weight (kg)",
        color="#0b7a75",
    )
    return Response(png, mimetype="image/png")


@bp.get("/pr.png")
@login_required
def pr_png():
    user = require_user()
    png = _line_chart_png(
        session_pr_estimate_points(user.id),
        title="Estimated 1RM per Session (Epley)",
        ylabel="Estimated 1RM (kg)",
        color="#c05621",
    )
    return Response(png, mimetype="image/png")


@bp.get("/time.png")
@login_required
def time_png():
    user = require_user()
    png = _line_chart_png(
        session_duration_points(user.id),
        title="Timed Work per Session",
        ylabel="Seconds",
        color="#1d4ed8",
    )
    return Response(png, mimetype="image/png")


@bp.get("/exercise-volume.png")
@login_required
def exercise_volume_png():
    user = require_user()
    period = request.args.get("period", "session")
    if period not in {"session", "week"}:
        period = "session"
    metric = _selected_metric(request.args.get("metric"))
    choices = exercise_rep_choices(user.id)
    selected_exercise_id = _selected_exercise_id(request.args.get("exercise_id"), choices)
    points = (
        exercise_progress_points(user.id, selected_exercise_id, period, metric)
        if selected_exercise_id is not None
        else []
    )
    png = _line_chart_png(
        points,
        title=_exercise_chart_title(metric, period),
        ylabel=_exercise_chart_ylabel(metric),
        color="#7c3aed",
    )
    return Response(png, mimetype="image/png")
