from functools import wraps

from flask import abort, g, redirect, request, session, url_for

from .db import get_db


def load_user():
    uid = session.get("uid")
    g.user = (
        get_db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if uid else None
    )


def login_required(*roles):
    def deco(view):
        @wraps(view)
        def wrapped(*a, **kw):
            if g.user is None:
                if request.path.startswith("/api/"):
                    abort(401)
                return redirect(url_for("web.login", next=request.path))
            if roles and g.user["role"] not in roles:
                abort(403)
            return view(*a, **kw)
        return wrapped
    return deco
