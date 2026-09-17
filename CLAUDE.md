# Personal Knowledge Base Web Viewer — System Reference

## Purpose
A single-user web app for browsing and searching a personal Obsidian vault (<10,000 markdown files, growing) as rendered web pages, from any device/browser — not just the machine running Obsidian. Solves a specific frustration: the vault is currently only accessible from the user's own computers.

Reference: `SAMPLE_CLAUDE.MD` in this same repo is the system-reference file from a prior, separate project (a calorie tracker) built by the same person on the **same shared-hosting account** (confirmed). Many hosting/deployment decisions here are carried over from that project directly, on that basis.

---

## Status
Design phase, in progress. Core stack, hosting model, sync mechanism, and auth approach agreed. Rendering/search implementation details and exact rsync invocation still to be finalized. Not yet scaffolded. Intended to eventually be handed to Claude Code for implementation, not built in-chat.

---

## Architecture

**Vault source of truth**: the Obsidian vault stays local and authoritative on the user's machine. Content reaches the server via a one-way rsync push — no live sync, no bidirectional editing on the server.

**Backend**: Python, Flask — chosen for consistency with the prior project and because it's a known-working fit for this host's Passenger/WSGI model.

**Markdown parsing**: pure-Python only. `obsidian-export` (the Rust CLI originally considered) is assumed **not usable**, since shared cPanel hosting typically does not allow running arbitrary compiled binaries. Likely candidates: `markdown-it-py` or `mistune`, extended with custom rules for:
- Wikilinks: `[[note]]`, `[[note|display text]]`
- Callouts: `> [!note]`, `> [!warning]`, etc.
- Obsidian-style frontmatter (YAML)

**Note-in-note transclusion is explicitly out of scope.** The user doesn't embed notes into other notes in practice — `![[...]]` in this vault only ever refers to **media** (images, PDFs), never another note's rendered content. This removes an entire category of complexity: no cross-file rendering dependency, no cache-invalidation cascade (A's cached HTML going stale because embedded note B changed), no "is this a note-embed or a media-embed" branching in the general case. `![[...]]` resolution is simply: recognize a media file extension, resolve the filename to a served URL via the same filename-lookup table used for wikilinks, and emit an `<img>` tag (images) or a link/embed (PDFs). Media files themselves stay as files on disk in the synced vault directory — only the filename→path mapping goes into SQLite; file bytes are never stored in the DB.

**Serving media**: needs its own authenticated route rather than Flask's default `/static` (which isn't behind the login check) — e.g. `/vault-assets/<path:filepath>` with `send_from_directory`, guarded by the same `@login_required` as everything else.

**Storage & search**: SQLite, using an **FTS5** virtual table for full-text search. No separate search service (e.g. MeiliSearch) — fits the no-persistent-process hosting constraint.

**Rendered HTML persistence**: a `rendered_html` TEXT column on the same `files` table used for metadata/mtime tracking — populated at reindex time, read directly on every page view. This is treated as **persisted data, not a cache** (no TTL, no eviction — it's durable until the source file changes and reindex overwrites it). No caching package (`diskcache`, Flask-Caching, etc.) is used or needed: the persistence layer is the SQLite DB the project already depends on via the stdlib `sqlite3` module, consistent with the no-unnecessary-dependencies philosophy carried over from the prior project. Keeping rendered HTML in the same row as the file's own metadata (rather than a separate cache store or flat `.html` files on disk) means one write, one source of truth, and the existing mark-and-sweep deletion logic automatically cleans it up too.

**Frontend**: minimal, server-rendered.
- Homepage: search bar + list of most-recently-edited files below it.
- Clicking a file: rendered HTML view of that note.
- Typing a search query: fast full-text search against FTS5, with highlighted preview snippets.

**Auth**: single-user login, session persists ~30 days, enforced over HTTPS. See Auth section below for detail — this is a firmer requirement here than in the prior project, since this app is intentionally internet-reachable rather than local/LAN-only.

---

## File Sync & Reindexing

- **Mechanism**: rsync over SSH (confirmed available on this cPanel account), pushed from the user's Windows machine (via the free cwRsync client, run without admin rights) to a data directory on the server — kept separate from the app's own git repo so content syncs don't collide with code deploys.
- **No live file-watching**: the host can't run a persistent process to watch for changes, so this is a push-then-reindex model, not real-time.
- **Archive mode (`-a`) required**: preserves the *source* file's modification time on the destination. This matters specifically because "most recently edited" on the homepage is meant to reflect actual Obsidian edit time — without `-a`/`-t`, every file would get "now" as its mtime on every sync, breaking that feature.
- **Excludes**: `.obsidian/` config directory and any non-markdown clutter should be excluded from the sync.
- **Reindex trigger: standalone script over SSH, not an HTTP route.** An `/admin/reindex` route was the original idea, but Passenger/WSGI requests typically have a timeout (often 30–60s), and cPanel shared hosting usually runs under CloudLinux LVE CPU/memory limits — a reindex could exceed either and die mid-run, leaving the DB inconsistent. Since SSH access is confirmed available, reindex instead runs as a plain script invoked directly, chained onto the rsync command itself (e.g. `rsync ... && ssh user@host 'cd ~/app && venv/bin/python reindex.py'`). This has no WSGI-imposed time limit, and keeps the web app itself purely read-only against whatever's currently in SQLite — reindexing never touches the request/response cycle.
- **Incremental, not full, on routine syncs**: the reindex script compares each synced file's mtime against what's already stored in SQLite from the last run, and only re-parses/re-renders files that are new or changed. A full 10k-file reindex only happens once, on initial setup — routine reindexes (a normal day's worth of edits) touch only a handful of rows and should be fast (sub-second to a few seconds), since there's no cross-file rendering dependency to worry about now that note transclusion is out of scope (see Architecture).
- **Deletion handling**: if `--delete` is used with rsync, the reindex step needs a mark-and-sweep pass — reconcile the full current file list against the DB and remove entries for files no longer present, to avoid stale search results and dead links.
- **Separate from code deploys**: content sync (rsync + reindex) and app code deploy (git pull + Passenger restart) are two distinct actions and should not be conflated in tooling or documentation.
- Exact rsync command/flags: **deliberately not finalized yet** — to be worked out later.

---

## Deployment Target
*(Carried over from the prior project's `SAMPLE_CLAUDE.MD` — confirmed same hosting account for this project.)*

- **Hosting**: cPanel-based shared hosting, using cPanel's "Setup Python App" tool (Passenger integration). Apache owns the web ports; the app runs inside Apache's process model via Passenger, not as a standalone process on its own port.
- **Python version**: 3.8.20, a hard ceiling set by the host. No 3.9+-only syntax (no `match`/`case`, no `X | Y` type unions).
- **WSGI entry point**: `passenger_wsgi.py` in the project root, committed to git (no secrets in it).
- **Secrets**: set via cPanel's "Setup Python App" environment-variable UI in production, not via `.env` (Passenger's `.env` auto-loading behavior isn't reliably consistent with local dev).
- **Deploy process**: manual — SSH/cPanel Terminal → `git pull` → Restart via the Python App page. No CI/CD.

---

## Challenges & Decisions — Auth

- **30-day session**: Flask's signed-cookie session (`itsdangerous`, built in) — `session.permanent = True` + `app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)`. No server-side session store needed; fits the stateless/no-daemon hosting model.
- **`SECRET_KEY`**: must be a real random secret, set via cPanel's env-var UI (same pattern as `ANTHROPIC_API_KEY` in the prior project) — never hardcoded or committed. A leaked key lets anyone forge a valid login cookie indefinitely.
- **Credential storage**: single user, so a password hash (`werkzeug.security.generate_password_hash`) in an env var or a one-row config table is sufficient — no `users` table needed.
- **Cookie flags**: `Secure`, `HttpOnly`, `SameSite=Lax` — required here, unlike the prior project where auth was deferred as "likely unnecessary for single-user." This app is intentionally public-facing.
- **HTTPS/TLS**: terminated by Apache in front of Passenger (cPanel AutoSSL/Let's Encrypt) — not something Flask handles directly. Confirm a cert is provisioned before going live.
- **Brute-force protection**: a failed-login counter with lockout, stored in the existing SQLite DB — no new infrastructure required.
- **CSRF protection**: needed on the login form, the one unauthenticated state-changing endpoint.

## Challenges & Decisions — Rendering & Search

- **Render-once, persist in DB**: markdown → HTML conversion happens at reindex time, not per-request — avoids re-parsing custom Obsidian syntax on every page view at 10k-file scale. See Architecture for the `rendered_html` column decision and why no caching package is used.
- **No cross-file rendering dependency**: with note-in-note transclusion out of scope, each file's rendered HTML depends only on that file's own content — reindexing one file never requires touching or invalidating any other file's cached HTML.
- **Broken links**: wikilinks pointing to renamed/deleted/not-yet-synced notes must degrade gracefully (plain text or a distinguishable "broken link" style), not error the whole page. Same treatment applies to `![[...]]` media references pointing at missing files.
- **Search previews**: FTS5's `snippet()`/`highlight()` functions generate matched-term preview snippets directly — no custom preview-generation logic needed.
- **SQLite write concurrency**: single-writer limitation is a minor consideration during reindex, but unlikely to matter at single-user scale with infrequent syncs.
- **Multiple Passenger worker processes**: since all state (rendered HTML, FTS index) lives in SQLite rather than in-memory, there's no cross-worker cache-invalidation problem — every worker reads current DB state directly.

---

## Open Questions / Not Yet Decided
- Exact rsync command and flags (deliberately deferred).
- Whether the SSH-chained reindex call is run manually after each rsync push, or scripted into one combined command the user runs.
- Whether "recently edited" on the homepage is a fixed count (e.g. last 20 files) or a date-window cutoff.
- Whether search should match only file content, or also filenames/tags/frontmatter fields.
- Specific brute-force lockout thresholds for the login route.
- Real-world reindex timing hasn't been measured yet — the "sub-second to a few seconds for incremental" estimate is analytical, not benchmarked against this host's actual LVE CPU limits.
- Backlinks, tag browsing, graph view, dark mode — all explicitly out of scope for MVP, to be considered only after basic render/search/auth is working end-to-end.
- Note-in-note transclusion is out of scope for now per current usage patterns — would need revisiting (and reintroduces the cache-invalidation-cascade problem) if that authoring habit ever changes.
