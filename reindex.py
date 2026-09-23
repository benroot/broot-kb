"""Reindex script - run locally against the real vault, before any sync to
the server (see sync.py, and CLAUDE.md's File Sync & Reindexing section).
Never runs on the server itself: this keeps parsing/rendering off the
shared-hosting box entirely, sidestepping Passenger/WSGI request timeouts and
CloudLinux LVE CPU/memory limits rather than working around them.

Two-phase, per CLAUDE.md's "no cross-file rendering dependency" design:
  Phase A: walk the vault, sync path/mtime for every note & media file so the
           filename lookup table is complete before anything renders.
  Phase B: render only the notes that are new or whose mtime advanced,
           resolving wikilinks/embeds against the now-complete lookup.

Use --limit N to try this against a real vault before trusting it on the
whole thing: Phase A still scans everything (so the lookup table - and
therefore link resolution - is complete and correct), but Phase B only
renders a random sample of N notes, so you get a fast, representative
preview without waiting for or committing a full run. Point DATABASE_PATH
at a scratch file while doing this so it doesn't touch your real db.
"""
import argparse
import json
import os
import random

import config
from wsgi_app import db, links, render


def scan_vault(conn):
    """Phase A. Returns (changed_note_paths, seen_note_paths, seen_media_paths)."""
    existing_mtimes = {r["path"]: r["mtime"] for r in conn.execute("SELECT path, mtime FROM files")}

    changed_note_paths = []
    seen_note_paths = set()
    seen_media_paths = set()

    for root, dirs, filenames in os.walk(config.VAULT_DIR):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fname in filenames:
            if fname.startswith("."):
                continue
            full_path = os.path.join(root, fname)
            rel_path = os.path.relpath(full_path, config.VAULT_DIR).replace(os.sep, "/")
            mtime = os.path.getmtime(full_path)
            ext = os.path.splitext(fname)[1].lower()

            if ext == ".md":
                seen_note_paths.add(rel_path)
                prior_mtime = existing_mtimes.get(rel_path)
                if prior_mtime is None or mtime > prior_mtime:
                    changed_note_paths.append(rel_path)
                if prior_mtime is None:
                    # `mtime` is only advanced once Phase B actually renders the
                    # file (see render_changed) - not here - so a mid-run crash
                    # leaves the row looking stale and it gets retried next time,
                    # rather than being silently treated as already up to date.
                    stem = os.path.splitext(fname)[0]
                    conn.execute(
                        "INSERT INTO files (path, title, mtime, rendered_html, body) "
                        "VALUES (?, ?, 0, '', '')",
                        (rel_path, stem),
                    )
            elif ext in config.MEDIA_EXTENSIONS:
                seen_media_paths.add(rel_path)
                conn.execute(
                    """
                    INSERT INTO media (filename, path, mtime) VALUES (?, ?, ?)
                    ON CONFLICT(path) DO UPDATE SET mtime = excluded.mtime, filename = excluded.filename
                    """,
                    (fname, rel_path, mtime),
                )

    conn.commit()
    return changed_note_paths, seen_note_paths, seen_media_paths


def sweep_deleted(conn, seen_note_paths, seen_media_paths):
    """Mark-and-sweep: drop DB rows for files no longer on disk."""
    existing_note_paths = {r["path"] for r in conn.execute("SELECT path FROM files")}
    existing_media_paths = {r["path"] for r in conn.execute("SELECT path FROM media")}

    deleted_notes = existing_note_paths - seen_note_paths
    deleted_media = existing_media_paths - seen_media_paths

    for path in deleted_notes:
        conn.execute("DELETE FROM files WHERE path = ?", (path,))
    for path in deleted_media:
        conn.execute("DELETE FROM media WHERE path = ?", (path,))

    conn.commit()
    return len(deleted_notes), len(deleted_media)


def render_changed(conn, changed_note_paths):
    """Phase B. Render only changed/new notes against a lookup built from
    the now-complete (post Phase A) files/media tables."""
    if not changed_note_paths:
        return 0

    lookup = links.build_lookup(conn)
    rendered = 0

    for rel_path in changed_note_paths:
        full_path = os.path.join(config.VAULT_DIR, rel_path.replace("/", os.sep))
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                raw_text = f.read()
        except OSError:
            continue  # deleted mid-run; the next sweep will remove its row

        frontmatter, body = render.split_frontmatter(raw_text)
        html = render.render_note_body(body, lookup)

        title = frontmatter.get("title")
        if not isinstance(title, str) or not title.strip():
            title = os.path.splitext(os.path.basename(rel_path))[0]

        conn.execute(
            """
            UPDATE files
            SET title = ?, rendered_html = ?, body = ?, frontmatter_json = ?, mtime = ?
            WHERE path = ?
            """,
            (
                title, html, body,
                # default=str: YAML auto-parses unquoted dates/timestamps into
                # datetime.date/datetime objects, which json.dumps can't
                # serialize natively - str() gives a reasonable ISO-ish
                # representation for storage purposes.
                json.dumps(frontmatter, default=str),
                os.path.getmtime(full_path), rel_path,
            ),
        )
        rendered += 1

    conn.commit()
    return rendered


def main(argv=None):
    parser = argparse.ArgumentParser(description="Reindex the vault into the SQLite db.")
    parser.add_argument(
        "--limit", type=int, default=None, metavar="N",
        help="Render at most N changed/new notes, chosen at random, instead of all "
             "of them. Phase A still scans the whole vault so links resolve "
             "correctly - only Phase B's rendering is capped. Useful for a quick, "
             "representative preview against a real vault (point DATABASE_PATH at "
             "a scratch file first).",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Delete the existing db first and rebuild from scratch, so every note "
             "gets re-rendered regardless of mtime. Needed after a code change to "
             "render.py/links.py (e.g. URL_PREFIX) - incremental reindex only "
             "re-renders notes whose file mtime advanced, so it won't otherwise "
             "pick up a change that affects rendering but not the source files.",
    )
    args = parser.parse_args(argv)

    if args.force and os.path.exists(config.DATABASE_PATH):
        print(f"--force: deleting existing db at {config.DATABASE_PATH}")
        os.remove(config.DATABASE_PATH)

    db.init_db()
    conn = db.get_connection()
    try:
        changed, seen_notes, seen_media = scan_vault(conn)
        deleted_notes, deleted_media = sweep_deleted(conn, seen_notes, seen_media)

        skipped = 0
        if args.limit is not None and len(changed) > args.limit:
            skipped = len(changed) - args.limit
            changed = random.sample(changed, args.limit)

        rendered = render_changed(conn, changed)
    finally:
        conn.close()

    print(f"Scanned vault: {len(seen_notes)} note(s), {len(seen_media)} media file(s)")
    limit_note = f" ({skipped} more skipped by --limit)" if skipped else ""
    print(f"Rendered {rendered} new/changed note(s){limit_note}")
    print(f"Removed {deleted_notes} deleted note row(s), {deleted_media} deleted media row(s)")


if __name__ == "__main__":
    main()
