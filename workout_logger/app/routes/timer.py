from __future__ import annotations

from flask import Blueprint, render_template

from . import login_required

bp = Blueprint('timer', __name__, url_prefix='/timer')


@bp.get('')
@login_required
def hiit_timer():
    return render_template('timer/index.html')
