from datetime import timedelta

from flask import Flask

import config

from . import auth, routes


def create_app():
    if not config.SECRET_KEY or not config.PASSWORD_HASH:
        raise RuntimeError(
            "SECRET_KEY and PASSWORD_HASH must be set (env vars or .env) to serve the app"
        )

    app = Flask(__name__)
    app.config["SECRET_KEY"] = config.SECRET_KEY
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=config.SESSION_LIFETIME_DAYS)
    app.config["SESSION_COOKIE_SECURE"] = config.SESSION_COOKIE_SECURE
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    app.register_blueprint(auth.bp)
    app.register_blueprint(routes.bp)

    return app
