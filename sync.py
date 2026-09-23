"""Local sync orchestrator. Run this on the machine that hosts the Obsidian
vault - NEVER deployed to or run on the server itself.

    1. Reindex locally against the real vault (config.VAULT_DIR /
       config.DATABASE_PATH, pointed at the real vault and a local db path
       via .env on this machine) - all the parsing/rendering work happens
       here, never under the server's CPU/memory limits.
    2. rsync media files (everything except .md and .obsidian/) to the
       server, mirroring deletions.
    3. rsync the freshly-built sqlite db to the server, last, so it never
       ends up referencing media that hasn't arrived yet.

Requires `rsync` on PATH (a Cygwin/MSYS-style build - MSYS2's `rsync`
package, or cwRsync) and SSH key auth already set up to the server. Needs
REMOTE_SSH_TARGET, REMOTE_VAULT_DIR, REMOTE_DATABASE_PATH set - see
.env.example. VAULT_DIR/DATABASE_PATH stay in native Windows-path form in
.env (what Python/config.py want); _to_rsync_local_path() converts them to
the /c/... form rsync's own argument parser needs for a LOCAL path right
before each rsync call, since a raw `C:\foo` is otherwise misread as a
remote host spec (rsync uses `:` to mean host:path).
"""
import argparse
import os
import shlex
import subprocess
import sys

import config
import reindex


def _require(name):
    value = getattr(config, name, None)
    if not value:
        sys.exit(f"Missing required setting: {name} (set it in .env)")
    return value


def _to_rsync_local_path(path):
    """Convert a Windows-style path (C:\\foo\\bar) to the /c/foo/bar form a
    Cygwin/MSYS-style rsync binary (MSYS2's rsync, cwRsync - what's
    realistically available on Windows) needs for a LOCAL path argument.
    Not MSYS2-specific: rsync's own argument syntax uses `:` to mean "this is
    a remote host spec" (host:path), so a raw `C:\\foo` is misread as
    "connect to a host named C" rather than a local path, regardless of
    which shell invokes this script. Idempotent - already-POSIX or relative
    paths (no drive letter) pass through with just backslashes normalized.

    Uses the MSYS2 mount convention (/c/...). A Cygwin-based client like
    cwRsync instead expects /cygdrive/c/... - swap the prefix below if you
    switch tooling.
    """
    drive, rest = os.path.splitdrive(path)
    if not drive:
        return path.replace("\\", "/")
    return "/" + drive.rstrip(":").lower() + rest.replace("\\", "/")


def _run(cmd):
    print("+", " ".join(shlex.quote(part) for part in cmd))
    subprocess.run(cmd, check=True)


def sync_media():
    remote_target = _require("REMOTE_SSH_TARGET")
    remote_vault_dir = _require("REMOTE_VAULT_DIR").rstrip("/")
    local_vault_dir = _to_rsync_local_path(config.VAULT_DIR).rstrip("/") + "/"

    _run([
        "rsync", "-av", "--delete",
        "--exclude=*.md",
        "--exclude=.obsidian/",
        local_vault_dir,
        f"{remote_target}:{remote_vault_dir}/",
    ])


def sync_database():
    remote_target = _require("REMOTE_SSH_TARGET")
    remote_database_path = _require("REMOTE_DATABASE_PATH")

    _run([
        "rsync", "-av",
        _to_rsync_local_path(config.DATABASE_PATH),
        f"{remote_target}:{remote_database_path}",
    ])


def main(argv=None):
    parser = argparse.ArgumentParser(description="Reindex locally, then sync media + db to the server.")
    parser.add_argument(
        "--force", action="store_true",
        help="Delete the local db and fully rebuild before syncing - forwarded to "
             "reindex.py --force. Use after a render.py/links.py change (e.g. "
             "URL_PREFIX) that needs every note re-rendered.",
    )
    args = parser.parse_args(argv)

    print("Reindexing local vault...")
    reindex.main(["--force"] if args.force else [])

    print("\nSyncing media...")
    sync_media()

    print("\nSyncing database...")
    sync_database()

    print("\nDone.")


if __name__ == "__main__":
    main()
