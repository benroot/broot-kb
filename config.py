import os

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SECRET_KEY = os.environ["SECRET_KEY"]
PASSWORD_HASH = os.environ["PASSWORD_HASH"]

VAULT_DIR = os.environ.get("VAULT_DIR", os.path.join(BASE_DIR, "dev_vault"))
DATABASE_PATH = os.environ.get("DATABASE_PATH", os.path.join(BASE_DIR, "broot-kb.db"))

SESSION_LIFETIME_DAYS = 30
# Browsers won't send Secure cookies back over plain HTTP during local dev;
# set SESSION_COOKIE_SECURE=0 in .env for local testing. Production (HTTPS via
# Apache/Passenger) must leave this at the default of "1".
SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "1") == "1"

LOGIN_LOCKOUT_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT_WINDOW_SECONDS = 15 * 60

RECENT_FILES_LIMIT = 20

MEDIA_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp",
    ".pdf",
}
