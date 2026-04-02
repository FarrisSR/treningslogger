from __future__ import annotations

from collections import Counter

from flask import Blueprint, Response, jsonify, request, render_template
from sqlalchemy import func

from .. import db
from ..models import TimerEvent
from . import login_required, require_user

bp = Blueprint('timer', __name__, url_prefix='/timer')


def _parse_int_arg(name: str) -> int | None:
    raw = (request.args.get(name) or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _default_timer_config() -> dict[str, int]:
    return {
        "work_seconds": 20,
        "rest_seconds": 10,
        "cycles": 8,
        "sets": 1,
        "set_rest_seconds": 60,
        "start_delay_seconds": 5,
    }


def _most_used_timer_config(user_id: int) -> dict[str, int]:
    rows = (
        TimerEvent.query.filter(
            TimerEvent.user_id == user_id,
            TimerEvent.event.in_(["start", "finish"]),
            TimerEvent.work_seconds.isnot(None),
            TimerEvent.rest_seconds.isnot(None),
            TimerEvent.cycles.isnot(None),
            TimerEvent.sets.isnot(None),
            TimerEvent.set_rest_seconds.isnot(None),
            TimerEvent.start_delay_seconds.isnot(None),
        )
        .order_by(TimerEvent.created_at.desc(), TimerEvent.id.desc())
        .all()
    )
    if not rows:
        rows = (
            TimerEvent.query.filter(
                TimerEvent.user_id == user_id,
                TimerEvent.work_seconds.isnot(None),
                TimerEvent.rest_seconds.isnot(None),
                TimerEvent.cycles.isnot(None),
                TimerEvent.sets.isnot(None),
                TimerEvent.set_rest_seconds.isnot(None),
                TimerEvent.start_delay_seconds.isnot(None),
            )
            .order_by(TimerEvent.created_at.desc(), TimerEvent.id.desc())
            .all()
        )
    if not rows:
        return _default_timer_config()

    counts = Counter(
        (
            row.work_seconds,
            row.rest_seconds,
            row.cycles,
            row.sets,
            row.set_rest_seconds,
            row.start_delay_seconds,
        )
        for row in rows
    )
    best_config, _ = max(
        counts.items(),
        key=lambda item: (
            item[1],
            next(
                idx
                for idx, row in enumerate(rows)
                if (
                    row.work_seconds,
                    row.rest_seconds,
                    row.cycles,
                    row.sets,
                    row.set_rest_seconds,
                    row.start_delay_seconds,
                )
                == item[0]
            ) * -1,
        ),
    )
    return {
        "work_seconds": int(best_config[0]),
        "rest_seconds": int(best_config[1]),
        "cycles": int(best_config[2]),
        "sets": int(best_config[3]),
        "set_rest_seconds": int(best_config[4]),
        "start_delay_seconds": int(best_config[5]),
    }


@bp.get('')
@login_required
def hiit_timer():
    user = require_user()
    return render_template('timer/index.html', timer_defaults=_most_used_timer_config(user.id))


@bp.get('/usage')
@login_required
def hiit_timer_usage():
    user = require_user()
    rows = (
        TimerEvent.query.filter_by(user_id=user.id)
        .order_by(TimerEvent.created_at.desc(), TimerEvent.id.desc())
        .limit(300)
        .all()
    )
    counts = Counter(row.event for row in rows)
    top_configs = Counter(
        (
            row.work_seconds,
            row.rest_seconds,
            row.cycles,
            row.sets,
            row.set_rest_seconds,
            row.start_delay_seconds,
        )
        for row in rows
        if row.work_seconds is not None
    ).most_common(8)
    run_rows = (
        TimerEvent.query.filter(
            TimerEvent.user_id == user.id,
            TimerEvent.run_id.isnot(None),
            TimerEvent.event.in_(["start", "finish"]),
        )
        .with_entities(TimerEvent.run_id, TimerEvent.event)
        .all()
    )
    run_events: dict[str, set[str]] = {}
    for run_id, event in run_rows:
        run_events.setdefault(run_id, set()).add(event)
    started_runs = sum(1 for events in run_events.values() if "start" in events)
    finished_runs = sum(1 for events in run_events.values() if "finish" in events)
    recent_events = rows[:40]
    return render_template(
        "timer/usage.html",
        event_counts=counts,
        top_configs=top_configs,
        started_runs=started_runs,
        finished_runs=finished_runs,
        completion_rate=(finished_runs / started_runs * 100.0) if started_runs else None,
        recent_events=recent_events,
    )


@bp.get('/track')
@login_required
def hiit_timer_track():
    user = require_user()
    event = (request.args.get('event') or '').strip().lower()
    if not event:
        return jsonify({"ok": False, "error": "Missing event"}), 400
    keep_awake = (request.args.get('keep_awake') or '1').strip() == '1'
    timer_event = TimerEvent(
        user_id=user.id,
        run_id=(request.args.get('run_id') or '').strip() or None,
        event=event,
        phase=(request.args.get('phase') or '').strip() or None,
        work_seconds=_parse_int_arg('work'),
        rest_seconds=_parse_int_arg('rest'),
        cycles=_parse_int_arg('cycles'),
        sets=_parse_int_arg('sets'),
        set_rest_seconds=_parse_int_arg('set_rest'),
        start_delay_seconds=_parse_int_arg('start_delay'),
        total_duration_seconds=_parse_int_arg('total_seconds'),
        keep_awake=keep_awake,
        preset_name=(request.args.get('preset_name') or '').strip() or None,
    )
    db.session.add(timer_event)
    db.session.commit()
    return Response(status=204)
