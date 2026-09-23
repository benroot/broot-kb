# Personal Knowledge Base Web Viewer — System Reference

## Purpose
A single-user web app for browsing and searching a personal Obsidian vault (<10,000 markdown files, growing) as rendered web pages, from any device/browser — not just the machine running Obsidian. Solves a specific frustration: the vault is currently only accessible from the user's own computers.

Reference: `SAMPLE_CLAUDE.MD` in this same repo is the system-reference file from a prior, separate project (a calorie tracker) built by the same person on the **same shared-hosting account** (confirmed). Many hosting/deployment decisions here are carried over from that project directly, on that basis.

---

## Status
Scaffolded and functional: Flask app, SQLite+FTS5 schema, auth (login/CSRF/lockout), mistune-based renderer (wikilinks/embeds/callouts), homepage/search/note routes, and reindex/sync scripts all exist and have been exercised end-to-end against a test vault. Exact rsync flags/path quoting for the real vault and real remote host are still to be verified (see Open Questions). Being implemented directly with Claude Code, not just designed in-chat.

---

## Architecture

**Vault source of truth**: the Obsidian vault stays local and authoritative on the user's machine. Content reaches the server via a one-way rsync push — no live sync, no bidirectional editing on the server.

**Rendering happens locally, never on the server.** Markdown → HTML conversion (and the whole reindex pass) runs on the machine that hosts the Obsidian vault, via `reindex.py`, orchestrated by `sync.py` (see File Sync & Reindexing). The server only ever serves rows that were already rendered elsewhere — it never parses markdown, so it doesn't need `mistune`/`PyYAML` at all. This fully sidesteps the CloudLinux LVE CPU/memory-limit risk a server-side reindex would carry, rather than just mitigating it.

**Backend**: Python, Flask — chosen for consistency with the prior project and because it's a known-working fit for this host's Passenger/WSGI model.

**Markdown parsing**: pure-Python only, using **mistune 3.x** (chosen over `markdown-it-py` — lighter footprint, and Obsidian callouts are blockquote-based so custom rules are needed with either engine). `obsidian-export` (the Rust CLI originally considered) is assumed **not usable on the server**, since shared cPanel hosting typically does not allow running arbitrary compiled binaries — moot now anyway since rendering doesn't happen there. Custom mistune rules handle:
- Wikilinks: `[[note]]`, `[[note|display text]]`
- Callouts: `> [!note]`, `> [!warning]`, etc.
- Obsidian-style frontmatter (YAML)

**Note-in-note transclusion is explicitly out of scope.** The user doesn't embed notes into other notes in practice — `![[...]]` in this vault only ever refers to **media** (images, PDFs, docx, HEIC/HEIF photos), never another note's rendered content. This removes an entire category of complexity: no cross-file rendering dependency, no cache-invalidation cascade (A's cached HTML going stale because embedded note B changed), no "is this a note-embed or a media-embed" branching in the general case. `![[...]]` resolution is simply: recognize a media file extension, resolve the filename to a served URL via the same filename-lookup table used for wikilinks, and emit an `<img>` tag for browser-displayable image formats or a download link otherwise (PDF, docx, HEIC/HEIF — HEIC/HEIF is only natively displayable in an `<img>` by Safari, so it's linked rather than inlined everywhere). Media files themselves stay as files on disk in the synced vault directory — only the filename→path mapping goes into SQLite; file bytes are never stored in the DB (considered and rejected: SQLite's incremental-BLOB-read API needs Python 3.11+, unavailable on the server's 3.8.20 ceiling, so serving a large PDF from a BLOB would load the whole thing into memory per request under CloudLinux's memory limits; BLOBs also don't reclaim disk space on delete/replace without a `VACUUM`, unlike plain files). Since rendering happens locally now (see above), the server's copy of the vault directory only needs media files — `.md` files themselves are never synced to the server at all.

**Serving media**: needs its own authenticated route rather than Flask's default `/static` (which isn't behind the login check) — e.g. `/vault-assets/<path:filepath>` with `send_from_directory`, guarded by the same `@login_required` as everything else.

**`URL_PREFIX` for subdirectory deployments**: `links.py` builds wikilink/embed URLs (`/note/...`, `/vault-assets/...`) by hand and bakes them into `rendered_html` at reindex time — outside any Flask request, so it has no `url_for()`/`SCRIPT_NAME` to pick up the app's URL prefix automatically the way server-rendered template links do (homepage, search results — those get it for free via Passenger). Deploying under a subdirectory (e.g. `https://example.com/broot-kb/` rather than the domain root) means setting `URL_PREFIX` (e.g. `/broot-kb`) in `.env` **on the reindexing machine**, then re-running `reindex.py`/`sync.py` — not a server-side setting, which is easy to reach for first and is the wrong place for it given where rendering actually happens.

**Storage & search**: SQLite, using an **FTS5** virtual table for full-text search. No separate search service (e.g. MeiliSearch) — fits the no-persistent-process hosting constraint.

**Rendered HTML persistence**: a `rendered_html` TEXT column on the same `files` table used for metadata/mtime tracking — populated at reindex time, read directly on every page view. This is treated as **persisted data, not a cache** (no TTL, no eviction — it's durable until the source file changes and reindex overwrites it). No caching package (`diskcache`, Flask-Caching, etc.) is used or needed: the persistence layer is the SQLite DB the project already depends on via the stdlib `sqlite3` module, consistent with the no-unnecessary-dependencies philosophy carried over from the prior project. Keeping rendered HTML in the same row as the file's own metadata (rather than a separate cache store or flat `.html` files on disk) means one write, one source of truth, and the existing mark-and-sweep deletion logic automatically cleans it up too.

**Frontend**: minimal, server-rendered.
- Homepage: search bar + list of most-recently-edited files below it.
- Clicking a file: rendered HTML view of that note.
- Typing a search query: fast full-text search against FTS5, with highlighted preview snippets.

**Auth**: single-user login, session persists ~30 days, enforced over HTTPS. See Auth section below for detail — this is a firmer requirement here than in the prior project, since this app is intentionally internet-reachable rather than local/LAN-only.

---

## File Sync & Reindexing

**Reindexing happens locally, not on the server.** This was a pivot from the original design (which ran reindex.py over SSH on the server after each rsync push). Reasoning: SQLite's `rendered_html`/FTS5 persistence already means the server never needs to parse markdown to serve a page, so there was no real reason to make it do that parsing work at sync time either — better to keep the entire render pipeline on a machine with no CPU/memory quota. This also fully resolves what used to be an open risk (reindex timing never benchmarked against this host's actual LVE limits) rather than mitigating it.

- **`sync.py`** (run on the machine hosting the Obsidian vault — never deployed to or run on the server) orchestrates the whole flow in one command:
  1. Runs `reindex.py` locally against the real vault (`VAULT_DIR`/`DATABASE_PATH` env vars point at the real vault and a local db file, not `dev_vault/`) — all parsing/rendering happens here.
  2. `rsync`s media files (everything except `.md` and `.obsidian/`) to the server, with `--delete` so removed media disappears there too.
  3. `rsync`s the freshly-built sqlite db to the server **last**, so it's never live on the server while referencing media that hasn't arrived yet.
- **Mechanism**: rsync over SSH (confirmed available on this cPanel account), via the free cwRsync client on the user's Windows machine, run without admin rights, to a data directory on the server kept separate from the app's own git repo (so content syncs don't collide with code deploys).
- **No live file-watching**: the host can't run a persistent process to watch for changes, so this is a push-model, not real-time — the user runs `sync.py` when they want the server updated.
- **The server's copy of the vault directory holds media only** — no `.md` files are ever synced there, since rendering already happened locally. `.obsidian/` and markdown files are excluded from the media rsync.
- **`.md` mtimes only matter locally now**: "most recently edited" on the homepage is computed from mtimes read directly off the local vault's `.md` files during local reindexing — archive-mode/`-a` preservation of source mtimes matters for the *media* rsync (for correct HTTP caching headers on served assets), but is no longer load-bearing for the recently-edited feature the way it would be if the server were doing the mtime comparison.
- **Database transfer must stay atomic on the server.** Since `reindex.py` closes its connection cleanly when done (no WAL, no lingering journal file at rest) and the app opens a short-lived `sqlite3` connection per request rather than holding one open per worker, a plain `rsync` (its default temp-file-then-rename behavior — never pass `--inplace` for the db) is safe: in-flight requests keep reading the old file, the very next request picks up the new one, no Passenger restart needed.
- **The app never 500s if it's started before the first sync.** `create_app()` calls `db.init_db()` on startup (idempotent - the schema is all `CREATE ... IF NOT EXISTS`, so it's a no-op against a db `sync.py` already populated). Before the first sync this just means an empty-but-working vault instead of "no such table" errors; there's no ordering requirement between "enable the Passenger app" and "run sync.py for the first time."
- **Incremental, not full, on routine syncs**: `reindex.py` compares each vault file's mtime against what's already stored in SQLite from the last run, and only re-parses/re-renders files that are new or changed. A full 10k-file reindex only happens once, on initial setup — routine reindexes (a normal day's worth of edits) touch only a handful of rows, and now run on unconstrained local hardware regardless.
- **Deletion handling**: `reindex.py` does a mark-and-sweep pass on every run — reconciles the full current vault listing against the DB and removes rows for files no longer present, to avoid stale search results and dead links.
- **Separate from code deploys**: content sync (`sync.py`) and app code deploy (git pull + Passenger restart) are two distinct actions and should not be conflated in tooling or documentation.
- Exact rsync flags/path quoting for the real vault and real remote paths (in particular, whether the cwRsync build in use needs Windows paths translated to `/cygdrive/...` form) are **not yet verified against the real setup** — `sync.py`'s rsync invocations are a working starting point, not finalized.

---

## Deployment Target
*(Carried over from the prior project's `SAMPLE_CLAUDE.MD` — confirmed same hosting account for this project.)*

- **Hosting**: cPanel-based shared hosting, using cPanel's "Setup Python App" tool (Passenger integration). Apache owns the web ports; the app runs inside Apache's process model via Passenger, not as a standalone process on its own port.
- **Python version**: 3.8.20, a hard ceiling set by the host. No 3.9+-only syntax (no `match`/`case`, no `X | Y` type unions).
- **Server dependencies are minimal**: `requirements.txt` (Flask + python-dotenv only) is what the server installs. `mistune`/`PyYAML` live in `requirements-dev.txt` instead, since only `reindex.py`/`sync.py` (local-only) need them — the deployed app never imports the renderer.
- **WSGI entry point**: `passenger_wsgi.py` in the project root, committed to git (no secrets in it).
- **Secrets**: set via cPanel's "Setup Python App" environment-variable UI in production, not via `.env` (Passenger's `.env` auto-loading behavior isn't reliably consistent with local dev).
- **Deploy process**: manual — SSH/cPanel Terminal → `git pull` → Restart via the Python App page. No CI/CD.

---

## Challenges & Decisions — Auth

- **30-day session**: Flask's signed-cookie session (`itsdangerous`, built in) — `session.permanent = True` + `app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)`. No server-side session store needed; fits the stateless/no-daemon hosting model.
- **`SECRET_KEY`**: must be a real random secret, set via cPanel's env-var UI (same pattern as `ANTHROPIC_API_KEY` in the prior project) — never hardcoded or committed. A leaked key lets anyone forge a valid login cookie indefinitely.
- **Credential storage**: single user, so a password hash (`werkzeug.security.generate_password_hash`) in an env var is sufficient — no `users` table needed. **Stored base64-encoded**, not raw: werkzeug's `pbkdf2:sha256:...$salt$hash` format contains `$`, which has previously not round-tripped cleanly through this host's env-var storage (plausibly shell variable expansion somewhere in how it gets sourced). Base64's alphabet has no shell/URL-metacharacters, sidestepping that entirely. `config.py` decodes it on the way in; `generate_password_hash.py` encodes it on the way out — the two must stay in sync on this.
- **Cookie flags**: `Secure`, `HttpOnly`, `SameSite=Lax` — required here, unlike the prior project where auth was deferred as "likely unnecessary for single-user." This app is intentionally public-facing.
- **HTTPS/TLS**: terminated by Apache in front of Passenger (cPanel AutoSSL/Let's Encrypt) — not something Flask handles directly. Confirm a cert is provisioned before going live.
- **Brute-force protection**: a failed-login counter with lockout, stored in the existing SQLite DB — no new infrastructure required.
- **CSRF protection**: needed on the login form, the one unauthenticated state-changing endpoint.

## Challenges & Decisions — Rendering & Search

- **Render-once, persist in DB**: markdown → HTML conversion happens at reindex time, not per-request — avoids re-parsing custom Obsidian syntax on every page view at 10k-file scale. See Architecture for the `rendered_html` column decision, why no caching package is used, and why reindexing (and therefore rendering) now happens locally rather than on the server.
- **No cross-file rendering dependency**: with note-in-note transclusion out of scope, each file's rendered HTML depends only on that file's own content — reindexing one file never requires touching or invalidating any other file's cached HTML.
- **Broken links**: wikilinks pointing to renamed/deleted/not-yet-synced notes must degrade gracefully (plain text or a distinguishable "broken link" style), not error the whole page. Same treatment applies to `![[...]]` media references pointing at missing files.
- **Search previews**: FTS5's `snippet()`/`highlight()` functions generate matched-term preview snippets directly — no custom preview-generation logic needed.
- **SQLite write concurrency**: single-writer limitation is a minor consideration during reindex, but unlikely to matter at single-user scale with infrequent syncs.
- **Multiple Passenger worker processes**: since all state (rendered HTML, FTS index) lives in SQLite rather than in-memory, there's no cross-worker cache-invalidation problem — every worker reads current DB state directly.

---

## Open Questions / Not Yet Decided
- Exact rsync flags and path quoting against the real vault/remote host — in particular whether the cwRsync build in use needs Windows paths given in `/cygdrive/...` form. `sync.py` has a working starting point, not verified against the real setup yet.
- Whether search should match only file content, or also filenames/tags/frontmatter fields (currently: title + body only).
- Specific brute-force lockout thresholds for the login route (currently: 5 attempts / 15 minutes, a starting default — not validated against real usage).
- Backlinks, tag browsing, graph view, dark mode — all explicitly out of scope for MVP, to be considered only after basic render/search/auth is working end-to-end.
- Note-in-note transclusion is out of scope for now per current usage patterns — would need revisiting (and reintroduces the cache-invalidation-cascade problem) if that authoring habit ever changes.

**Resolved**: markdown library (mistune 3.x); reindex trigger (`sync.py`, run locally, not SSH-chained on the server); "recently edited" is a fixed count of 20; reindex timing/LVE-limit risk (moot now — reindexing never runs on the server); media-bytes-in-DB was considered and rejected (see Architecture).
