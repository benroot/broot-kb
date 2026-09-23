import os
import sqlite3
from urllib.parse import unquote

from flask import Blueprint, abort, render_template, request, send_from_directory

import config

from .auth import login_required
from .db import get_connection

bp = Blueprint("routes", __name__)


def _path_variants(filepath):
    """`filepath` as received, plus a %-decoded fallback if it contains a
    `%` - some Apache/Passenger proxy setups (seen on this host, mounting
    the app under a URL subdirectory) don't decode %20 etc. before handing
    the path to Flask, so a space-containing name arrives still literally
    encoded and misses an exact match against the db/filesystem."""
    variants = [filepath]
    if "%" in filepath:
        variants.append(unquote(filepath))
    return variants


def _recent_files(conn):
    return conn.execute(
        "SELECT path, title, mtime FROM files ORDER BY mtime DESC LIMIT ?",
        (config.RECENT_FILES_LIMIT,),
    ).fetchall()


def _run_search(conn, query):
    try:
        return conn.execute(
            """
            SELECT f.path AS path, f.title AS title,
                   snippet(files_fts, 1, '<mark>', '</mark>', '…', 12) AS snippet
            FROM files_fts
            JOIN files f ON f.id = files_fts.rowid
            WHERE files_fts MATCH ?
            ORDER BY rank
            LIMIT 50
            """,
            (query,),
        ).fetchall()
    except sqlite3.OperationalError:
        # malformed FTS5 query syntax from user input - treat as no results
        return []


@bp.route("/")
@login_required
def index():
    conn = get_connection()
    try:
        recent_files = _recent_files(conn)
    finally:
        conn.close()
    return render_template("index.html", recent_files=recent_files, query=None, results=None)


@bp.route("/search")
@login_required
def search():
    query = request.args.get("q", "").strip()
    conn = get_connection()
    try:
        results = _run_search(conn, query) if query else None
        recent_files = _recent_files(conn) if not query else []
    finally:
        conn.close()
    return render_template("index.html", recent_files=recent_files, query=query, results=results)


@bp.route("/note/<path:filepath>")
@login_required
def note(filepath):
    conn = get_connection()
    try:
        row = None
        for candidate in _path_variants(filepath):
            row = conn.execute(
                "SELECT title, rendered_html FROM files WHERE path = ?", (candidate,)
            ).fetchone()
            if row is not None:
                break
    finally:
        conn.close()
    if row is None:
        abort(404)
    return render_template("note.html", title=row["title"], html=row["rendered_html"])


@bp.route("/vault-assets/<path:filepath>")
@login_required
def vault_asset(filepath):
    vault_root = os.path.normpath(config.VAULT_DIR)
    for candidate in _path_variants(filepath):
        full_path = os.path.normpath(os.path.join(vault_root, candidate))
        if os.path.commonpath([vault_root, full_path]) != vault_root:
            continue
        if os.path.isfile(full_path):
            directory, name = os.path.split(full_path)
            return send_from_directory(directory, name)
    abort(404)
