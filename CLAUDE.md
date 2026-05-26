# Cycling Clubs App — CLAUDE.md

## What this project is

A multi-tenant cycling club platform where any cycling club can host their club page, manage a weekly ride calendar, and publish rides. Users register once, subscribe to clubs, and see all their upcoming rides across every club on a single home screen.

The current codebase started as a single-club app (Reston Bike Club). It is being generalized into the multi-tenant platform described here.

## Tech stack

- **Backend:** Python / Flask + gunicorn
- **Database:** PostgreSQL (Flask-SQLAlchemy)
- **Auth:** Flask-Login + Flask-Bcrypt (future: OAuth via Google/Microsoft)
- **Forms:** Flask-WTF / WTForms
- **Weather:** Open-Meteo API (self-hosted logic ported from the `weatherapp` project)
- **Maps:** RideWithGPS embeds; club/ride discovery map TBD (Leaflet + OpenStreetMap preferred)
- **Containerization:** Docker, deployed on TrueNAS Scale

## Repository & deployment

- **Local dev / source of truth:** `/home/nullbnx/Projects/paceline/`
- **Dev platform:** TrueNAS Scale at `192.168.50.189` via Docker Compose
- **Dev URL:** `cyclingclub.pcp.dev` (Cloudflare Tunnel)
- **Git remote:** `github.com/0xPCP/paceline` (private)

## Dev/deploy workflow

1. Implement feature locally in `/home/nullbnx/Projects/paceline/`
2. Write/update test harness for the feature (see `tests/`)
3. Run tests: `pytest` inside the container or locally
4. Commit to GitHub with a message naming the feature
5. `rsync` project to TrueNAS: `rsync -av --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' --exclude='.venv' --exclude='instance/' --exclude='*.db' --exclude='.env' /home/nullbnx/Projects/paceline/ nullbnx@192.168.50.189:/mnt/fast/docker/projects/paceline/`
6. SSH to TrueNAS: `cd /mnt/fast/docker/projects/paceline && sg docker -c 'docker compose up -d --build'`
7. If schema changed: `docker compose exec web python seed.py` (wipe + re-seed dev DB)

## Testing rules

- Every new feature must have a corresponding test module or additions to an existing one in `tests/`
- Tests that need data use the fixtures in `tests/conftest.py` — extend conftest rather than duplicating setup
- If a feature requires test data beyond what conftest provides, add it to `seed.py`
- Run the full suite before every commit: all tests must pass
- Run the dependency/CVE audit before every commit and before every push:
  `.venv/bin/pip-audit --cache-dir /tmp/paceline-pip-audit-cache -r requirements.txt`
- After pushing, confirm GitHub Actions' `Security Audit / dependency-audit` job passes before treating the deploy as complete

## Headless browser / screenshot testing

For any feature with a significant UI component (maps, interactive widgets, theming, dynamic JS), add a `tests/test_browser_<feature>.py` module that uses **Playwright** (pytest-playwright) to:

1. Launch a headless Chromium browser
2. Navigate to the relevant page on the live dev server (`https://cyclingclub.pcp.dev`) or the local test server
3. Wait for the UI to settle (e.g., `.wait_for_selector()`)
4. Take a screenshot with `page.screenshot(path='tests/screenshots/<feature>.png')`
5. Assert that key visible elements are present (`page.locator(...).is_visible()`)

This catches Cloudflare Access intercepts, JS runtime errors, CDN failures, and rendering regressions that Flask's test client cannot see.

**Install:** `pip install pytest-playwright && playwright install chromium`

**Screenshot directory:** `tests/screenshots/` (gitignored — add `tests/screenshots/` to `.gitignore`)

**Known issue:** `cyclingclub.pcp.dev` is behind Cloudflare Access (URL unchanged for now). Browser tests that need to reach the live URL must either:
- Use a Cloudflare service token passed as a header, OR
- Run against the local Flask dev server (`flask run`) started before the test session
- Preferred approach: use `pytest-playwright` with `base_url` pointed at `http://localhost:5000` with `FLASK_ENV=testing`

## Infrastructure notes

- Traefik reverse proxy handles TLS (`*.pcp.dev` wildcard cert, entrypoint-level — do NOT add per-router `tls.certresolver` labels)
- Docker network: `internal` (external, pre-existing on TrueNAS)
- Watchtower disabled (`com.centurylinklabs.watchtower.enable=false`) — local builds only
- DB credentials live in `.env` (not committed); see `.env.example`

## Key files

| File | Purpose |
|------|---------|
| `app/__init__.py` | App factory, context processor (injects `version`, `now`) |
| `app/models.py` | SQLAlchemy models — `Club`, `ClubMembership` (status: active/pending), `ClubAdmin` (role: admin/ride_manager), `Ride`, etc. |
| `app/routes/clubs.py` | Public club routes; join/leave respects `join_approval`; ride_signup gates on `require_membership`; private club route hiding |
| `app/routes/admin.py` | Club admin routes; `club_admin_required` / `club_ride_admin_required` decorators; team management; membership approve/reject |
| `app/forms.py` | WTForms: `ClubCreateForm`, `ClubSettingsForm` (includes `require_membership`, `join_approval`) |
| `app/weather.py` | Weather fetch + WMO condition logic (Open-Meteo) |
| `app/templates/` | Jinja2 templates; `base.html` is the layout |
| `app/templates/clubs/create.html` | 5-step club creation wizard with theme picker |
| `app/templates/admin/club_team.html` | Team management + pending membership approval |
| `seed.py` | Dev seed data — wipe + re-run after schema changes; `test@pcp.dev`/`password` = RBC admin |
| `tests/conftest.py` | Pytest fixtures (app, client, db, seeded users/rides) |
| `tests/test_membership.py` | 25 tests for membership gates, approval flows, private club route hiding |

## Membership model notes

- `ClubMembership.status`: `'active'` (full member) | `'pending'` (awaiting admin approval)
- `Club.join_approval`: `'auto'` (immediate active) | `'manual'` (pending until approved)
- `Club.require_membership`: if True, only `status='active'` members can sign up for rides
- `Club.is_private`: if True, route URL, RideWithGPS embed, and GPX are hidden from non-active-members
- All clubs are discoverable on the map + Find Clubs regardless of privacy settings
- `User.is_active_member_of(club)` and `User.is_pending_member_of(club)` are the authoritative checks

## Post-ride media sharing

Photos and video links can be shared by members after a ride. Key constraints:

- **Videos:** External links only (YouTube, Strava, Vimeo) — no server-side video storage or transcoding.
- **Photos:** JPEG/PNG/WebP, ≤5 MB input, Pillow-resized to 1200 px wide, stored at `uploads/ride_media/<ride_id>/`.
- **Limits:** `MEDIA_MAX_PHOTOS_PER_USER_RIDE` (default 5), `MEDIA_MAX_PHOTOS_PER_RIDE` (default 30).
- **Expiry:** `MEDIA_EXPIRY_DAYS` (default 90) — scheduler job at 02:30 deletes old files + DB rows.
- **Visibility:** Upload forms only appear after `ride.date`. Private-club photos require active membership to serve.
- **Full strategy, storage estimates, and migration guide to Cloudflare R2:** `docs/media_strategy.md`

Blueprint: `app/routes/media.py`. Model: `RideMedia` in `app/models.py`.
All limits are env-var overridable — edit `.env`, no code change needed.

## WTForms gotcha

`BooleanField` treats any non-empty string (including `'0'`) as `True`. For boolean form fields driven by JS hidden inputs, read directly: `request.form.get('field') == '1'`.

## Feature status tracking

`requirements.md` is the canonical product spec. Every feature has a status marker:
- ✅ Built — shipped and tested
- 🔨 In progress
- 📋 Planned — in the backlog
- 💡 Icebox — good idea, not yet scheduled

`tasks.md` is the engineering backlog — completed work at the top, then sections: High Priority, Medium Priority, Icebox. When starting a new feature, find it in both files and update status markers as work progresses.
