#!/usr/bin/env python3
"""Generate a Werkzeug-compatible pbkdf2:sha256 password hash for the vault app.

Run this locally, paste the printed value into the cPanel env-var UI
(e.g. as PASSWORD_HASH) — never store the plaintext password anywhere.

Printed as base64: werkzeug's raw hash format contains `$`, which has
previously not round-tripped cleanly through this host's env-var storage.
config.py base64-decodes PASSWORD_HASH on the way in, so this and the app
must stay in sync on that encoding.
"""

import base64
from getpass import getpass
from werkzeug.security import generate_password_hash


def main():
    password = getpass("Password: ")
    confirm = getpass("Confirm password: ")

    if not password:
        print("Password cannot be empty.")
        return

    if password != confirm:
        print("Passwords do not match.")
        return

    password_hash = generate_password_hash(password, method="pbkdf2:sha256")
    encoded = base64.urlsafe_b64encode(password_hash.encode("ascii")).decode("ascii")

    print("\nSet this as an environment variable (e.g. PASSWORD_HASH) on the server:\n")
    print(encoded)


if __name__ == "__main__":
    main()
