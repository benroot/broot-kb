import functools
import secrets
import time

from flask import Blueprint, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

import config

from .db import get_connection

bp = Blueprint("auth", __name__)


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("authed"):
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def _csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_hex(32)
        session["csrf_token"] = token
    return token


def _recent_failed_attempts(conn):
    cutoff = time.time() - config.LOGIN_LOCKOUT_WINDOW_SECONDS
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM login_attempts WHERE success = 0 AND attempted_at >= ?",
        (cutoff,),
    ).fetchone()
    return row["n"]


def _record_attempt(conn, success):
    conn.execute(
        "INSERT INTO login_attempts (attempted_at, success) VALUES (?, ?)",
        (time.time(), 1 if success else 0),
    )
    conn.commit()


@bp.route("/login", methods=["GET", "POST"])
def login():
    error = None
    conn = get_connection()
    try:
        if request.method == "POST":
            if not secrets.compare_digest(
                request.form.get("csrf_token", ""), session.get("csrf_token", "")
            ):
                error = "Invalid form submission, please try again."
            elif _recent_failed_attempts(conn) >= config.LOGIN_LOCKOUT_MAX_ATTEMPTS:
                error = "Too many failed attempts. Try again later."
            else:
                password = request.form.get("password", "")
                if check_password_hash(config.PASSWORD_HASH, password):
                    _record_attempt(conn, True)
                    next_url = request.args.get("next") or url_for("routes.index")
                    session.clear()
                    session["authed"] = True
                    session.permanent = True
                    return redirect(next_url)
                else:
                    _record_attempt(conn, False)
                    error = "Incorrect password."
    finally:
        conn.close()
    return render_template("login.html", error=error, csrf_token=_csrf_token())


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
