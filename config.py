import os

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Not required at import time (.get, not []) so that reindex.py/sync.py -
# which never touch auth - can run standalone without Flask secrets
# configured. create_app() enforces these are actually set before serving.
SECRET_KEY = os.environ.get("SECRET_KEY")
PASSWORD_HASH = os.environ.get("PASSWORD_HASH")

VAULT_DIR = os.environ.get("VAULT_DIR", os.path.join(BASE_DIR, "dev_vault"))
DATABASE_PATH = os.environ.get("DATABASE_PATH", os.path.join(BASE_DIR, "broot-kb.db"))

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
