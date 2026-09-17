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

Requires `rsync` on PATH (e.g. cwRsync on Windows, run without admin rights)
and SSH key auth already set up to the server. Needs REMOTE_SSH_TARGET,
REMOTE_VAULT_DIR, REMOTE_DATABASE_PATH set - see .env.example.

The exact rsync flags/path quoting here are a starting point, not finalized -
verify them against your actual cwRsync build and remote layout (see
CLAUDE.md's Open Questions).
"""
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


def _run(cmd):
    print("+", " ".join(shlex.quote(part) for part in cmd))
    subprocess.run(cmd, check=True)


def sync_media():
    remote_target = _require("REMOTE_SSH_TARGET")
    remote_vault_dir = _require("REMOTE_VAULT_DIR").rstrip("/")
    local_vault_dir = config.VAULT_DIR.rstrip("/\\") + "/"

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
        config.DATABASE_PATH,
        f"{remote_target}:{remote_database_path}",
    ])


def main():
    print("Reindexing local vault...")
    reindex.main()

    print("\nSyncing media...")
    sync_media()

    print("\nSyncing database...")
    sync_database()

    print("\nDone.")


if __name__ == "__main__":
    main()
