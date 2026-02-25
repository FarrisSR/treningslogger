from __future__ import annotations

from io import BytesIO

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from flask import Blueprint, Response, render_template

from ..services.stats import pr_estimate_points, weekly_duration_points, weekly_volume_points
from . import login_required, require_user

bp = Blueprint("stats", __name__, url_prefix="/stats")


def _line_chart_png(points, title: str, ylabel: str, color: str) -> bytes:
    fig, ax = plt.subplots(figsize=(8, 3.8), dpi=120)
    if points:
        x_vals = [p[0] for p in points]
        y_vals = [p[1] for p in points]
        ax.plot(x_vals, y_vals, marker="o", linewidth=2, color=color)
    else:
        ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.25)
    fig.autofmt_xdate()
    fig.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


@bp.get("")
@login_required
def stats_index():
    return render_template("stats/index.html")


@bp.get("/volume.png")
@login_required
def volume_png():
    user = require_user()
    png = _line_chart_png(
        weekly_volume_points(user.id),
        title="Weekly Volume",
        ylabel="Reps x Weight (kg)",
        color="#0b7a75",
    )
    return Response(png, mimetype="image/png")


@bp.get("/pr.png")
@login_required
def pr_png():
    user = require_user()
    png = _line_chart_png(
        pr_estimate_points(user.id),
        title="Estimated 1RM (Epley)",
        ylabel="Estimated 1RM (kg)",
        color="#c05621",
    )
    return Response(png, mimetype="image/png")


@bp.get("/time.png")
@login_required
def time_png():
    user = require_user()
    png = _line_chart_png(
        weekly_duration_points(user.id),
        title="Weekly Time Under Tension / Holds",
        ylabel="Seconds",
        color="#1d4ed8",
    )
    return Response(png, mimetype="image/png")
