import base64
import os

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Not required at import time (.get, not []) so that reindex.py/sync.py -
# which never touch auth - can run standalone without Flask secrets
# configured. create_app() enforces these are actually set before serving.
SECRET_KEY = os.environ.get("SECRET_KEY")

# PASSWORD_HASH is stored base64-encoded in the env var - werkzeug's raw
# pbkdf2:sha256:...$salt$hash format contains `$`, which has previously not
# round-tripped cleanly through this host's env-var storage (plausibly
# shell variable expansion somewhere in how it gets sourced). Base64's
# alphabet has no shell/URL-metacharacters, sidestepping that entirely.
# Generate values with generate_password_hash.py, which encodes for you.
_password_hash_b64 = os.environ.get("PASSWORD_HASH")
if _password_hash_b64:
    try:
        PASSWORD_HASH = base64.urlsafe_b64decode(_password_hash_b64).decode("ascii")
    except (ValueError, UnicodeDecodeError) as e:
        raise RuntimeError(
            "PASSWORD_HASH is not valid base64 - generate it with generate_password_hash.py"
        ) from e
else:
    PASSWORD_HASH = None

VAULT_DIR = os.environ.get("VAULT_DIR", os.path.join(BASE_DIR, "dev_vault"))
DATABASE_PATH = os.environ.get("DATABASE_PATH", os.path.join(BASE_DIR, "broot-kb.db"))

# Only matters on the machine running reindex.py/sync.py, not the server.
# links.py bakes wikilink/embed URLs directly into rendered_html at reindex
# time, outside any Flask request - it has no SCRIPT_NAME/url_for to work
# with, unlike server-rendered templates (homepage/search links, which pick
# up the app's URL prefix for free via Passenger). If the app is deployed
# under a subdirectory (e.g. https://example.com/broot-kb/), set this to
# that path (e.g. "/broot-kb") on the reindexing machine and re-run
# reindex.py/sync.py - otherwise in-note links/embeds resolve against the
# domain root and 404.
URL_PREFIX = os.environ.get("URL_PREFIX", "").rstrip("/")

# Sync destination, used only by sync.py (run on the machine that hosts the
# Obsidian vault, never on the server itself - see CLAUDE.md: File Sync &
# Reindexing). Optional here since the deployed app itself never needs them.
REMOTE_SSH_TARGET = os.environ.get("REMOTE_SSH_TARGET")  # e.g. "user@example.com"
REMOTE_VAULT_DIR = os.environ.get("REMOTE_VAULT_DIR")
REMOTE_DATABASE_PATH = os.environ.get("REMOTE_DATABASE_PATH")

SESSION_LIFETIME_DAYS = 30
# Browsers won't send Secure cookies back over plain HTTP during local dev;
# set SESSION_COOKIE_SECURE=0 in .env for local testing. Production (HTTPS via
# Apache/Passenger) must leave this at the default of "1".
SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "1") == "1"

LOGIN_LOCKOUT_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT_WINDOW_SECONDS = 15 * 60

RECENT_FILES_LIMIT = 20

# Extensions an <img> tag can display inline in a browser. HEIC/HEIF (the
# default on iPhone) is deliberately excluded even though it's an image
# format - only Safari renders it natively in <img>, so it's treated as a
# download instead (see DOWNLOAD_EXTENSIONS).
IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".avif",
    ".tif", ".tiff",
}

# Recognized but rendered as a link/download rather than inlined.
DOWNLOAD_EXTENSIONS = {
    ".pdf", ".docx", ".heic", ".heif",
}

MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | DOWNLOAD_EXTENSIONS
