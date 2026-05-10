# Production Audit — paceline.club — 2026-05-10

Performed via Digital Ocean runtime logs and live site crawl across all major
unauthenticated workflows. Five bugs found; three previously fixed this session;
two fixed in this audit pass.

---

## Bug 1 — Stale PostgreSQL SSL connections (FIXED)

**Severity:** High — sporadic 500 errors visible to users  
**First seen:** 2026-05-09 19:54 (4 occurrences on `/clubs/map/`)  
**Error:**
```
psycopg2.OperationalError: SSL error: decryption failed or bad record mac
psycopg2.OperationalError: SSL SYSCALL error: EOF detected
```
**Cause:** After a new deployment, gunicorn spawned 4 workers whose SQLAlchemy
connection pool held SSL connections the Postgres server had already closed.
Any query that touched a stale pool slot threw immediately.  
**Fix:** Added `SQLALCHEMY_ENGINE_OPTIONS = {'pool_pre_ping': True}` to
`app/config.py`. SQLAlchemy now issues a cheap ping before handing out any
pooled connection and discards it if dead.  
**File:** `app/config.py:11`

---

## Bug 2 — Scheduler `purge_expired_media` SSL error (FIXED)

**Severity:** Medium — nightly media purge job silently fails  
**First seen:** 2026-05-10 02:30 (APScheduler job)  
**Error:**
```
psycopg2.OperationalError: SSL SYSCALL error: EOF detected
  File "/app/app/scheduler.py", line 133, in purge_expired_media
```
**Cause:** Same stale-connection root cause as Bug 1. The scheduler job ran
on a long-idle connection from the overnight pool.  
**Fix:** Same `pool_pre_ping=True` from Bug 1 covers this path.

---

## Bug 3 — Weekly digest crash: `AttributeError: 'NoneType'.is_authenticated` (FIXED)

**Severity:** High — Sunday weekly digest emails never send  
**First seen:** 2026-05-10 07:00 (APScheduler job)  
**Error:**
```
AttributeError: 'NoneType' object has no attribute 'is_authenticated'
  File "/app/app/__init__.py", line 25, in get_locale
      if current_user.is_authenticated and current_user.language:
```
**Cause:** The `send_weekly_digest` scheduler job calls `render_template()`.
Flask invokes the `inject_globals` context processor → `get_locale()` →
`current_user.is_authenticated`. Flask-Login's `current_user` proxy resolves
to `None` (not `AnonymousUser`) when accessed outside a request context.  
**Fix:** Added `if not has_request_context(): return 'en'` as the first line
of `get_locale()` in `app/__init__.py`. Scheduler-invoked templates now
default to English.  
**File:** `app/__init__.py:25`

---

## Bug 4 — Raw markdown syntax displayed in club descriptions (FIXED)

**Severity:** Medium — cosmetic; club about sections show literal `##`, `**`, `- `  
**Found:** Live site crawl — `/clubs/paceline-demo/` and `/clubs/`  
**Example output:**
```
## This is a demo club

This club was created by the Paceline team to showcase every available
feature. **It is not a real cycling club.**

### What you can do here
- Browse the ride calendar...
```
**Cause:** `club.description` and `club.safety_guidelines` are stored as
plain text (possibly with markdown syntax) but templates rendered them with
`style="white-space:pre-line"` which preserves newlines but does not convert
markdown to HTML. The truncated card previews on the homepage and Find Clubs
page also showed raw `##` and `**` prefixes.  
**Fix:**
- Added `mistune` to `requirements.txt`
- Added a `markdown` Jinja2 filter in `app/__init__.py` that renders markdown
  to safe HTML (HTML in source is escaped, preventing XSS)
- Added a `strip_markdown` filter for truncated card previews (homepage, clubs
  index) that strips syntax characters without rendering HTML
- Updated `clubs/home.html`, `clubs/index.html`, `index.html` to use filters  
**Files:** `app/__init__.py`, `app/templates/clubs/home.html`,
`app/templates/clubs/index.html`, `app/templates/index.html`,
`requirements.txt`

---

## Bug 5 — `/clubs/<slug>/join` returns 405 on GET (FIXED)

**Severity:** Low — confusing error if URL is navigated to directly  
**Found:** Live site crawl — `GET /clubs/paceline-demo/join` → HTTP 405  
**Cause:** The `join` route only registered `methods=['POST']`. Flask returns
405 Method Not Allowed before Flask-Login's `@login_required` can redirect the
user. Unauthenticated users who navigate to the URL directly (e.g., from a
search result, a bookmark, or a shared link) see a raw 405 error page rather
than being redirected to login or the club home page.  
**Fix:** Added `'GET'` to the route's allowed methods. A GET request now
redirects to the club home page.  
**File:** `app/routes/clubs.py:656`

---

## Warnings (not fixed — informational)

### flask-limiter in-memory storage
```
UserWarning: Using the in-memory storage for tracking rate limits as no
storage was explicitly specified. This is not recommended for production use.
```
Each of the 4 gunicorn workers tracks rate limits independently, so the
effective per-IP limit is `N × configured_rate`. Acceptable at current scale.
To make limits exact across workers, set `RATELIMIT_STORAGE_URI` to a Redis
instance in the DO app environment variables.

---

## Workflows tested

| Page / workflow | Status |
|---|---|
| Homepage (`/`) | OK |
| Find Clubs (`/clubs/`) | OK (markdown stripped in cards) |
| Club Map (`/clubs/map/`) | OK — 1 club pin loaded |
| Demo Club home (`/clubs/paceline-demo/`) | OK (markdown rendered) |
| Demo Club rides list | OK — 13 rides, filters work |
| Demo Club ride detail | OK — Add to Calendar, Sign In prompt present |
| Demo Club calendar month/week/list views | OK |
| ICS download (`/clubs/paceline-demo/rides/12/ics`) | OK — 200 |
| Discover Rides (`/discover/`) | OK — 4 rides, zip search works |
| Register (`/auth/register`) | OK — all fields + Google OAuth present |
| Login (`/auth/login`) | OK — form renders, CSRF validated |
| About (`/about`) | OK |
| Help (`/help/`) | OK |
| Donate (`/donate`) | OK |
| `GET /clubs/<slug>/join` | Fixed → now redirects to club home |
| `GET /auth/profile` | OK — redirects to login (302) |
| `GET /my-rides/` | OK — redirects to login (302) |
