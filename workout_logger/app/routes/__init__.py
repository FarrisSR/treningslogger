from __future__ import annotations

from functools import wraps

from flask import abort, g, redirect, request, session, url_for


def login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("auth.login", next=request.path))
        return view_func(*args, **kwargs)

    return wrapped


def current_user():
    return getattr(g, "current_user", None)


def require_user() -> object:
    user = current_user()
    if user is None:
        abort(401)
    return user
