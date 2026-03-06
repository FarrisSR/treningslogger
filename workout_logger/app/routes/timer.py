from __future__ import annotations

from flask import Blueprint, Response, request, render_template

from . import login_required

bp = Blueprint('timer', __name__, url_prefix='/timer')


@bp.get('')
@login_required
def hiit_timer():
    return render_template('timer/index.html')


@bp.get('/track')
@login_required
def hiit_timer_track():
    # Endpoint intentionally returns no content; query params are captured in access logs.
    request.args.get('event', '')
    request.args.get('work', '')
    request.args.get('rest', '')
    request.args.get('cycles', '')
    request.args.get('sets', '')
    request.args.get('set_rest', '')
    request.args.get('start_delay', '')
    request.args.get('keep_awake', '')
    request.args.get('phase', '')
    return Response(status=204)
