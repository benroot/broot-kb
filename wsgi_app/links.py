import os
from urllib.parse import quote

MEDIA_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp",
    ".pdf",
}


def _stem(path):
    return os.path.splitext(os.path.basename(path))[0]


def build_lookup(conn):
    """Build in-memory lookup tables from the DB so a whole render pass
    can resolve links without re-querying per link. Call once per Phase B
    reindex run, after Phase A has fully updated `files`/`media`.
    """
    notes_by_title = {}
    for row in conn.execute("SELECT path, title FROM files"):
        notes_by_title.setdefault(row["title"].lower(), row["path"])

    media_by_filename = {}
    for row in conn.execute("SELECT path, filename FROM media"):
        media_by_filename.setdefault(row["filename"].lower(), row["path"])

    return {"notes": notes_by_title, "media": media_by_filename}


def resolve(lookup, name):
    """Resolve a wikilink/embed target name to a served URL.

    Returns a dict: {"kind": "note"|"media"|"broken", "url": str|None}
    `name` is the raw text inside [[...]] (before the `|display` split).
    """
    ext = os.path.splitext(name)[1].lower()

    if ext in MEDIA_EXTENSIONS:
        path = lookup["media"].get(_stem(name).lower() + ext) or lookup["media"].get(name.lower())
        if path:
            return {"kind": "media", "url": "/vault-assets/" + quote(path)}
        return {"kind": "broken", "url": None}

    path = lookup["notes"].get(name.lower()) or lookup["notes"].get(_stem(name).lower())
    if path:
        return {"kind": "note", "url": "/note/" + quote(path)}
    return {"kind": "broken", "url": None}
