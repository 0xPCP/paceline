# Developer Guide — Cycling Clubs Platform

## What this is

A multi-tenant cycling club platform. Any cycling club can host a club page, publish a ride calendar, and manage members. Riders register once and see all their rides across every joined club on a single home screen.

---

## Tech stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 |
| Web framework | Flask 3.1 + Gunicorn |
| Database | PostgreSQL (Flask-SQLAlchemy 3.1) |
| Auth | Flask-Login + Flask-Bcrypt |
| Forms | Flask-WTF / WTForms |
| Scheduling | APScheduler 3.10 |
| Email | Flask-Mail (SMTP) |
| Image processing | Pillow 10.4 |
| Maps | Leaflet + OpenStreetMap (club discovery map) |
| Weather | Open-Meteo API (free, no key required) |
| Geocoding | OpenStreetMap Nominatim (free) |
| Strava | OAuth 2.0 (optional per-user and per-club) |
| Container | Docker + Docker Compose |
| Proxy | Traefik (TLS termination) |

---

## Project layout

```
rbc/
├── app/
│   ├── __init__.py          # App factory (create_app)
│   ├── config.py            # All configuration + env-var defaults
│   ├── extensions.py        # Flask extension singletons (db, login_manager, bcrypt, csrf, mail)
│   ├── models.py            # All SQLAlchemy models
│   ├── forms.py             # All WTForms form classes
│   ├── version.py           # __version__ string (bump on every release)
│   ├── email.py             # Email sending functions
│   ├── scheduler.py         # APScheduler jobs + init_scheduler()
│   ├── recurrence.py        # Ride recurrence generator
│   ├── weather.py           # Open-Meteo fetch + WMO code mapping
│   ├── geocoding.py         # Nominatim zip geocoding + haversine distance
│   ├── utils.py             # club_theme_vars() CSS helper
│   ├── routes/
│   │   ├── main.py          # /  /about  /discover
│   │   ├── auth.py          # /auth/*
│   │   ├── clubs.py         # /clubs/*  (public)
│   │   ├── admin.py         # /admin/*  (club admin + superadmin)
│   │   ├── media.py         # /media/*  /clubs/<slug>/rides/<id>/media/*
│   │   ├── api.py           # /api/*    (JSON endpoints for JS)
│   │   └── strava.py        # /strava/* (OAuth)
│   ├── static/
│   │   └── css/style.css    # All custom CSS (Bootstrap 5 base)
│   └── templates/           # Jinja2 templates (see Templates section)
├── tests/
│   ├── conftest.py          # Shared pytest fixtures
│   └── test_*.py            # Feature-specific test modules
├── docs/                    # Strategy and developer docs
├── seed.py                  # Dev DB wipe + re-seed (drop_all → create_all)
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── .env                     # Secrets (not committed; see .env.example)
```

---

## App factory

`create_app(config_class=Config)` in `app/__init__.py`:

1. Initialises Flask extensions (db, bcrypt, login_manager, csrf, mail)
2. Registers all blueprints
3. Registers a `strftime` Jinja2 filter (cross-platform — swaps `%-d` to `%#d` on Windows)
4. Injects `now` and `version` into every template via context processor
5. Calls `init_scheduler(app)` unless `TESTING=True`

---

## Database models

All models live in `app/models.py`. SQLAlchemy 2.x ORM with legacy query API.

### User

Central account. One user can be a member of many clubs and an admin of many clubs.

| Field | Type | Notes |
|---|---|---|
| id | Integer PK | |
| username | String 50, unique | |
| email | String 255, unique | used for login + all email |
| password_hash | String 255 | bcrypt |
| is_admin | Boolean | global superadmin flag |
| created_at | DateTime UTC | |
| address, zip_code | String | for weather widget |
| lat, lng | Float | geocoded from zip_code |
| emergency_contact_name/phone | String | opt-in; shown to ride admins on roster |
| gear_inventory | JSON | list of item IDs from GEAR_CATALOG |
| strava_id | BigInteger unique | nullable |
| strava_access_token / refresh_token | Text | nullable |
| strava_token_expires_at | Integer | unix timestamp |

**Key methods:**

```python
user.is_club_admin(club)        # full admin or superadmin
user.is_ride_manager(club)      # ride_manager role
user.can_manage_rides(club)     # admin OR ride_manager
user.is_active_member_of(club)  # status='active' membership
user.is_pending_member_of(club) # status='pending'
user.is_content_editor(club)    # content_editor role
user.is_treasurer(club)         # treasurer role
user.can_manage_content(club)   # admin OR content_editor
user.can_view_members(club)     # admin OR treasurer
user.has_signed_waiver(club, year=None)  # waiver check for given year
```

---

### Club

One row per club. `slug` is the URL identifier (e.g., `rbc` → `/clubs/rbc/`).

| Field | Type | Notes |
|---|---|---|
| id | Integer PK | |
| slug | String 80, unique | URL-safe; set at creation |
| name | String 200 | |
| description | Text | |
| logo_url, website, contact_email | String | |
| address, city, state, zip_code | String | |
| lat, lng | Float | geocoded |
| is_active | Boolean | inactive clubs hidden from directory |
| theme_primary, theme_accent | String hex | e.g., `#2d6a4f` |
| banner_url | String | header background image |
| is_private | Boolean | hides route URL, GPX, media, comments from non-members |
| require_membership | Boolean | gates ride signups behind active membership |
| join_approval | String | `'auto'` or `'manual'` |
| strava_club_id | BigInteger | optional; enables club activity feed |
| auto_cancel_enabled | Boolean | turns on weather auto-cancel |
| cancel_rain_prob | Integer | % precip probability threshold |
| cancel_wind_mph | Integer | wind speed threshold |
| cancel_temp_min_f / max_f | Integer | temperature range thresholds |

**Key properties:**

```python
club.member_count    # count of active ClubMembership rows
club.current_waiver  # most recently created ClubWaiver
```

---

### ClubMembership

Junction between User and Club with a status.

| Field | Notes |
|---|---|
| user_id, club_id | FK; unique together |
| status | `'active'` or `'pending'` |
| joined_at | DateTime UTC |

**Flows:**
- `join_approval='auto'` → status set to `'active'` immediately on join
- `join_approval='manual'` → status set to `'pending'`; admin approves via team page
- Approval sends `send_membership_approved()` email
- Rejection deletes the row and sends `send_membership_rejected()` email

---

### ClubAdmin

Grants a user an admin role within a specific club.

| Field | Notes |
|---|---|
| user_id, club_id | FK; unique together |
| role | `'admin'` \| `'ride_manager'` \| `'content_editor'` \| `'treasurer'` |

**Role capabilities:**

| Role | Rides | Members | Content | Settings | Financial |
|---|---|---|---|---|---|
| admin | ✓ | ✓ | ✓ | ✓ | ✓ |
| ride_manager | ✓ | — | — | — | — |
| content_editor | — | — | ✓ | — | — |
| treasurer | — | view only | — | — | ✓ |

Global `is_admin` users bypass all role checks.

---

### Ride

One row per ride occurrence. Recurring rides have both a template row and instance rows.

| Field | Notes |
|---|---|
| club_id | FK to Club |
| title, date, time | |
| meeting_location | String 500 |
| distance_miles, elevation_feet | Float/Integer |
| pace_category | `'A'` \| `'B'` \| `'C'` \| `'D'` |
| ride_type | `'road'` \| `'gravel'` \| `'social'` \| `'training'` \| `'event'` \| `'night'` |
| leader_id | FK to User (nullable) |
| ride_leader | String — denormalised display name |
| route_url | RideWithGPS or other URL |
| video_url | YouTube/Vimeo URL |
| max_riders | Integer (nullable = unlimited) |
| is_cancelled, cancel_reason | Boolean + String |
| is_recurring | True on template rows |
| recurrence_parent_id | FK to parent Ride (on instance rows) |

**Key computed properties:**

```python
ride.signup_count       # non-waitlist signups
ride.waitlist_count
ride.is_full            # signup_count >= max_riders (if set)
ride.spots_remaining    # max_riders - signup_count

# RideWithGPS parsing (extracts route ID from URL)
ride.ridewithgps_route_id
ride.ridewithgps_embed_url
ride.ridewithgps_map_image_url

# Video embed
ride.embed_url          # YouTube or Vimeo iframe src

ride.pace_label         # e.g., "A — Fast (22+ mph)"
```

---

### RideSignup

| Field | Notes |
|---|---|
| ride_id, user_id | FK; unique together |
| is_waitlist | True = on waitlist |
| attended | `None` = not recorded; `True` = showed up; `False` = no-show |

When a signup is deleted (unsignup), the scheduler auto-promotes the first waitlist entry to confirmed and sends `send_waitlist_promoted()`.

---

### RideMedia

| Field | Notes |
|---|---|
| media_type | `'photo'` or `'video_link'` |
| file_path | relative path under UPLOAD_FOLDER for photos |
| url | external video URL |
| caption | String 300 |

`embed_url` property extracts YouTube/Vimeo iframe src from `url` via regex.

Only shown when `ride.date <= today`. Private club photos served through Flask with membership check.

---

### RideComment

| Field | Notes |
|---|---|
| ride_id, user_id | FK |
| body | Text |

Members can delete their own. Admins/ride_managers can delete any.

---

### ClubInvite

| Field | Notes |
|---|---|
| club_id, created_by | FK |
| email | invite target address |
| token | 64-char URL-safe unique string |
| expires_at | 7 days from creation |
| used_at, used_by_user_id | set on redemption |

Claim route: `/clubs/invites/<token>`. Redirects to login if unauthenticated. On redeem, creates or upgrades a ClubMembership to `'active'`.

---

### ClubWaiver / WaiverSignature

Each club can have one waiver per year. Riders must sign before their first ride signup of the year.

`user.has_signed_waiver(club)` checks for a WaiverSignature matching the current year.

---

## Blueprint structure

| Blueprint | Prefix | File |
|---|---|---|
| main_bp | (none) | routes/main.py |
| auth_bp | /auth | routes/auth.py |
| clubs_bp | /clubs | routes/clubs.py |
| admin_bp | /admin | routes/admin.py |
| media_bp | (none) | routes/media.py |
| api_bp | /api | routes/api.py |
| strava_bp | /strava | routes/strava.py |

---

## Route reference

### Public routes (no auth required)

| Method | URL | Purpose |
|---|---|---|
| GET | / | Dashboard (logged in) or landing page |
| GET | /about | Static about page |
| GET | /discover/ | Cross-club ride search |
| GET | /clubs/ | Club directory + search |
| GET | /clubs/map/ | Leaflet map of all clubs |
| GET | /clubs/create | Club creation wizard (requires login) |
| GET | /clubs/\<slug\>/ | Club home page |
| GET | /clubs/\<slug\>/leaders/ | Public ride leader roster |
| GET | /clubs/\<slug\>/rides/ | Ride calendar (list/month/week) |
| GET | /clubs/\<slug\>/rides/\<id\> | Ride detail |
| GET | /clubs/\<slug\>/rides/\<id\>/ics | iCalendar (.ics) download |
| GET | /clubs/\<slug\>/rides/\<id\>/gpx | GPX download (private-club gated) |
| GET | /clubs/invites/\<token\> | Invite claim |
| GET | /media/ride/\<id\>/\<file\> | Serve ride photo (private-club gated) |
| GET | /api/clubs/map-data | Club GeoJSON for Leaflet |
| GET | /api/weather/widget | Weather + gear JSON |

### Auth routes

| Method | URL | Purpose |
|---|---|---|
| GET/POST | /auth/register | Create account |
| GET/POST | /auth/login | Sign in |
| GET | /auth/logout | Sign out |
| GET/POST | /auth/profile | Edit profile + gear |

### Authenticated rider actions

| Method | URL | Purpose |
|---|---|---|
| POST | /clubs/\<slug\>/join | Join club |
| POST | /clubs/\<slug\>/leave | Leave club |
| GET/POST | /clubs/\<slug\>/waiver | Sign annual waiver |
| POST | /clubs/\<slug\>/rides/\<id\>/signup | Sign up for ride |
| POST | /clubs/\<slug\>/rides/\<id\>/unsignup | Cancel signup |
| POST | /clubs/\<slug\>/rides/\<id\>/comments | Post comment |
| POST | /clubs/\<slug\>/rides/\<id\>/comments/\<id\>/delete | Delete own comment |
| POST | /clubs/\<slug\>/rides/\<id\>/media/photo | Upload photo (post-ride) |
| POST | /clubs/\<slug\>/rides/\<id\>/media/video | Add video link (post-ride) |
| POST | /clubs/\<slug\>/rides/\<id\>/media/\<id\>/delete | Delete own media |

### Admin routes (require club admin or ride_manager)

| Method | URL | Decorator | Purpose |
|---|---|---|---|
| GET | /admin/clubs/\<slug\>/ | ride_admin | Club dashboard |
| GET/POST | /admin/clubs/\<slug\>/settings | admin | Club settings |
| GET | /admin/clubs/\<slug\>/rides | ride_admin | All rides list |
| GET/POST | /admin/clubs/\<slug\>/rides/new | ride_admin | Create ride |
| GET/POST | /admin/clubs/\<slug\>/rides/\<id\>/edit | ride_admin | Edit ride |
| POST | /admin/clubs/\<slug\>/rides/\<id\>/delete | ride_admin | Delete ride |
| GET | /admin/clubs/\<slug\>/rides/\<id\>/roster | ride_admin | View signup roster |
| POST | /admin/clubs/\<slug\>/rides/\<id\>/attendance | ride_admin | Record attendance |
| GET | /admin/clubs/\<slug\>/team | admin | Team + member management |
| POST | /admin/clubs/\<slug\>/team/add | admin | Add admin role |
| POST | /admin/clubs/\<slug\>/team/\<id\>/remove | admin | Remove admin role |
| POST | /admin/clubs/\<slug\>/members/add | admin | Add member directly |
| POST | /admin/clubs/\<slug\>/members/\<id\>/remove | admin | Remove member |
| POST | /admin/clubs/\<slug\>/members/\<id\>/approve | admin | Approve pending |
| POST | /admin/clubs/\<slug\>/members/\<id\>/reject | admin | Reject pending |
| GET | /admin/clubs/\<slug\>/members/export | member_view | CSV export |
| GET/POST | /admin/clubs/\<slug\>/posts | content | News post list |
| GET/POST | /admin/clubs/\<slug\>/posts/new | content | Create post |
| GET/POST | /admin/clubs/\<slug\>/posts/\<id\>/edit | content | Edit post |
| POST | /admin/clubs/\<slug\>/posts/\<id\>/delete | content | Delete post |
| GET/POST | /admin/clubs/\<slug\>/invites | admin | Send + view invites |
| GET/POST | /admin/clubs/\<slug\>/leaders | admin | Ride leader roster |
| GET/POST | /admin/clubs/\<slug\>/sponsors | admin | Sponsor list |

### Superadmin routes (global `is_admin=True` only)

| Method | URL | Purpose |
|---|---|---|
| GET | /admin/ | Global stats dashboard |
| GET/POST | /admin/clubs/new | Create a new club |

### Strava routes

| Method | URL | Purpose |
|---|---|---|
| GET | /strava/connect | Redirect to Strava OAuth |
| GET | /strava/callback | Exchange code for token |
| POST | /strava/disconnect | Unlink Strava account |

---

## Permission decorators

Defined in `app/routes/admin.py`:

```python
@club_admin_required         # ClubAdmin.role='admin' or User.is_admin
@club_ride_admin_required    # role in ('admin','ride_manager') or is_admin
@club_content_required       # role in ('admin','content_editor') or is_admin
@club_member_view_required   # role in ('admin','treasurer') or is_admin
@superadmin_required         # User.is_admin only
```

All decorators abort 403 immediately if the user is unauthenticated.

---

## Key application flows

### New user signup
1. POST `/auth/register` → hashes password → creates `User`
2. If zip_code provided, `geocode_zip()` populates lat/lng
3. First user created becomes `is_admin=True`

### Joining a club
1. POST `/clubs/<slug>/join`
2. If `club.join_approval == 'auto'` → `ClubMembership(status='active')`
3. If `club.join_approval == 'manual'` → `ClubMembership(status='pending')`; admin sees badge on dashboard
4. Admin approves via team page → status → `'active'` + approval email sent

### Signing up for a ride
1. POST `/clubs/<slug>/rides/<id>/signup`
2. Checks: user logged in → active membership (if `require_membership`) → waiver signed this year → ride not cancelled → not already signed up
3. If `ride.is_full` → `RideSignup(is_waitlist=True)`
4. Otherwise → `RideSignup(is_waitlist=False)`
5. If ride was just created and `new_ride_notification` sent → see email section

### Waiver gate
- `user.has_signed_waiver(club)` checks for `WaiverSignature(user_id, club_id, year=current_year)`
- If missing, signup route redirects to `/clubs/<slug>/waiver`
- After signing, redirect returns to the original ride

### Recurring rides
- Admin checks "Repeat weekly" on ride form
- On save: `generate_instances(ride, weeks=8)` creates 8 copies with `recurrence_parent_id` set
- On edit of template: `delete_future_instances(template)` then `generate_instances()` again
- Instances are independent rides — editing one instance does not affect others

### Weather auto-cancel (scheduler)
1. `check_auto_cancels()` runs at 6:00 AM daily
2. For each active club with `auto_cancel_enabled=True`: fetch rides for today, get weather
3. If any threshold exceeded (rain prob, wind, temp): mark `is_cancelled=True`, set `cancel_reason`, send cancellation emails
4. `send_reminders()` runs at 6:15 AM: sends morning-of reminders to signups for today's rides

### Post-ride media
- Upload forms only appear and accept submissions when `ride.date <= today`
- Photos: validated extension → Pillow resize to `MEDIA_MAX_WIDTH_PX` px wide → JPEG 85% quality → stored in `UPLOAD_FOLDER/ride_media/<ride_id>/<uuid>.jpg`
- Videos: URL stored as-is; `embed_url` property extracts YouTube/Vimeo iframe src
- `purge_expired_media()` runs nightly at 2:30 AM and deletes files + DB rows for rides older than `MEDIA_EXPIRY_DAYS`

---

## Configuration reference

All values read from environment variables. Set in `.env` (development) or environment (production).

| Variable | Default | Purpose |
|---|---|---|
| SECRET_KEY | `dev-secret-key-change-in-production` | Flask session signing |
| DATABASE_URL | `postgresql://rbc:rbc@db:5432/rbc` | PostgreSQL connection string |
| MAIL_SERVER | `` (empty) | SMTP hostname; empty disables all email |
| MAIL_PORT | `587` | SMTP port |
| MAIL_USE_TLS | `true` | |
| MAIL_USERNAME | `` | SMTP credential |
| MAIL_PASSWORD | `` | SMTP credential |
| MAIL_DEFAULT_SENDER | `noreply@cyclingclubs.app` | From address |
| UPLOAD_FOLDER | `../uploads` | Filesystem path for photo storage |
| MAX_CONTENT_LENGTH | `5242880` (5 MB) | Hard upload size limit |
| MEDIA_EXPIRY_DAYS | `90` | Days after ride date before photos are deleted |
| MEDIA_MAX_PHOTOS_PER_USER_RIDE | `5` | Max photos one user can upload per ride |
| MEDIA_MAX_PHOTOS_PER_RIDE | `30` | Total photo cap per ride |
| MEDIA_MAX_WIDTH_PX | `1200` | Pillow resize target width |
| STRAVA_CLIENT_ID | — | Strava app credential |
| STRAVA_CLIENT_SECRET | — | Strava app credential |
| STRAVA_CLUB_ID | — | Default Strava club numeric ID |
| STRAVA_CLUB_REFRESH_TOKEN | — | Club-level refresh token for activity feed |
| AUTO_CANCEL_ENABLED | `true` | Master switch for weather auto-cancel |
| AUTO_CANCEL_HOUR | `6` | Hour (24h) for daily cancel + reminder check |

---

## Scheduled jobs

Managed by APScheduler `BackgroundScheduler`. Initialised in `init_scheduler(app)` which is called by the app factory (skipped when `TESTING=True`).

| Job | Schedule | What it does |
|---|---|---|
| `check_auto_cancels` | Daily at `AUTO_CANCEL_HOUR` (default 6 AM) | Cancels today's rides that breach weather thresholds; sends cancellation emails |
| `send_reminders` | Daily at `AUTO_CANCEL_HOUR + 0:15` | Sends morning-of reminder emails to all signups for today's rides |
| `send_weekly_digests` | Sundays at 7 AM | Emails each active member a digest of the next 7 days of rides |
| `send_board_activity_digests` | Daily at 6 PM | Sends queued message board activity digests |
| `purge_expired_media` | Daily at 2:30 AM | Deletes photo files + DB rows for rides older than `MEDIA_EXPIRY_DAYS` |

---

## Email system

All functions in `app/email.py`. Each is fire-and-forget (errors logged, never raised). If `MAIL_SERVER` is empty, `MAIL_SUPPRESS_SEND=True` is set and no messages are sent. User-configurable notifications are filtered through `users.email_preferences` and the superadmin daily cap stored in `site_settings.email_daily_cap`.

| Function | Trigger | Recipients |
|---|---|---|
| `send_cancellation_emails(ride)` | auto-cancel or manual cancel | all non-waitlist signups |
| `send_ride_reminder(ride)` | scheduler, morning of ride | all non-waitlist signups |
| `send_new_ride_notification(ride)` | admin creates a new ride | all active members |
| `send_club_news_notification(post)` | admin publishes a club news post | all active members |
| `send_waitlist_promoted(signup)` | unsignup frees a slot | promoted rider |
| `send_membership_approved(user, club)` | admin approves pending | joining user |
| `send_membership_rejected(user, club)` | admin rejects pending | joining user |
| `send_invite_email(invite)` | admin sends invite | invite.email address |
| `send_weekly_digest(club, rides)` | Sunday scheduler | all active members of club |
| `send_board_digest(user, items)` | daily board digest scheduler | users with queued board activity |

HTML and plain-text variants exist for all transactional emails under `app/templates/email/`.

See `docs/notifications.md` for the notification strategy, defaults, daily cap behavior, and test coverage.

---

## Weather integration

`app/weather.py` — calls Open-Meteo (no API key, rate-limit friendly).

- `get_weather_for_rides(rides)` — fetches forecasts for rides within the next 14 days; returns `{ride.id: weather_dict}`. Rides beyond 14 days get no forecast.
- `get_current_weather(lat, lng)` — single-point current conditions; cached 15 min per location.
- Responses include: `temp_f`, `feels_like_f`, `wind_mph`, `precip_prob`, `description`, `emoji`, `severity` (0/1/2), `warning` (bool), `warning_reasons`.
- WMO weather codes 0–99 are mapped to descriptions + emoji.
- Cache: in-process dictionary, keyed by `(lat, lng)`, TTL 30 min for forecasts.

---

## Geocoding

`app/geocoding.py` — calls OpenStreetMap Nominatim.

- `geocode_zip(zip_code)` → `(lat, lng)` or `None` (requires User-Agent header)
- `haversine_miles(lat1, lng1, lat2, lng2)` → float distance
- `clubs_near_zip(zip_code, clubs, radius_miles=50)` → `[(club, distance_miles), ...]` sorted by distance; used by club directory and ride discovery

---

## Theming

Per-club color scheme. `app/utils.py` provides `club_theme_vars(club)` which returns a CSS variable block. Injected into club pages via `{% include 'clubs/_theme.html' %}`.

6 preset color schemes: forest, ocean, slate, sunset, crimson, desert. Custom mode uses hex color pickers. Admin settings page has a live preview card.

CSS variables: `--rbc-green` (primary), `--rbc-green-dark`, `--rbc-green-light`, `--rbc-green-pale`, `--rbc-accent`.

---

## Testing

### Framework
pytest + pytest-flask. All tests use in-memory SQLite (`sqlite:///:memory:`).

### Config
`tests/conftest.py` defines shared fixtures:

| Fixture | What it creates |
|---|---|
| `app` | Flask app with `TESTING=True`, `WTF_CSRF_ENABLED=False`, SQLite |
| `client` | Flask test client |
| `db` | SQLAlchemy DB instance |
| `admin_user` | Global superadmin user |
| `regular_user` | Non-admin rider (`rider@test.com`) |
| `second_user` | Second non-admin rider |
| `club_admin_user` | User with `ClubAdmin` role on `sample_club` |
| `sample_club` | A basic active Club |
| `second_club` | A second Club |
| `sample_rides` | 3 rides on next Mon/Tue/Wed (always future) |
| `club_waiver` | A ClubWaiver for `sample_club` |
| `mock_weather` | Patches `get_weather_for_rides` to avoid network |

### Running tests
```bash
# All tests (from project root or inside container)
pytest

# Specific module
pytest tests/test_membership.py -v

# Exclude Playwright browser tests (requires live server)
pytest --ignore=tests/test_browser_mobile.py
```

### Browser tests
`tests/test_browser_mobile.py` uses Playwright to hit the live dev server at `https://cyclingclub.pcp.dev`. Requires:
```bash
pip install pytest-playwright
playwright install chromium
```
Screenshots saved to `tests/screenshots/` (gitignored).

### Test modules

| File | What it covers |
|---|---|
| test_models.py | Model field validation, relationships |
| test_auth.py | Register, login, profile |
| test_clubs.py | Club home, join/leave, privacy gating |
| test_rides.py | Ride signup, waitlist, unsignup, waiver gate |
| test_membership.py | Membership approval flows, private club |
| test_admin_clubs.py | Admin ride CRUD, settings, CSV export |
| test_calendar.py | List/month/week views, filters |
| test_recurrence.py | Recurring ride generation |
| test_auto_cancel.py | Weather threshold cancellation logic |
| test_email.py | All email functions (mock SMTP) |
| test_gpx.py | GPX proxy |
| test_theme.py | Color utilities, template injection |
| test_map.py | Club map GeoJSON endpoint |
| test_discovery.py | Cross-club ride discovery, zip filter |
| test_posts.py | News post CRUD |
| test_gear.py | Gear inventory + weather widget |
| test_strava.py | OAuth flow, activity feed |
| test_club_create.py | Club creation wizard |
| test_comments_invites.py | Ride comments, invite-by-email, superadmin dashboard |
| test_media.py | Photo upload, video links, serve, purge |
| test_attendance_multigroup.py | Attendance recording, same-day group card |
| test_browser_mobile.py | Playwright mobile + map screenshots |
| test_weather.py | Open-Meteo integration |

---

## Dev/deploy workflow

1. Implement feature in `D:\Projects\rbc\`
2. Add/update tests in `tests/`
3. Run `pytest --ignore=tests/test_browser_mobile.py` — all must pass
4. Bump `app/version.py`
5. `git add` specific files, `git commit`, `git push origin master`
6. Robocopy to TrueNAS (excludes `.git`, `__pycache__`, `instance`, `uploads`, `*.pyc`, `*.db`):
   ```powershell
   robocopy D:\Projects\rbc \\192.168.50.189\docker\projects\rbc /MIR /XD .git __pycache__ instance uploads /XF *.pyc *.db
   ```
7. SSH and rebuild + force-recreate:
   ```bash
   cd /mnt/fast/docker/projects/rbc
   docker compose up -d --build --force-recreate web
   ```
8. If schema changed, re-seed dev DB:
   ```bash
   docker compose exec web python seed.py
   ```

**Important:** Always use `--force-recreate` on the web container. Without it, Docker Compose may skip restarting the container even after building a new image, leaving the old code running.

---

## Common gotchas

**WTForms BooleanField**: Treats any non-empty string (including `'0'`) as `True`. For boolean inputs driven by JS hidden fields, read directly: `request.form.get('field') == '1'`.

**SQLite vs PostgreSQL datetimes**: Tests use SQLite which strips timezone info. All datetime comparisons against stored values use `datetime.utcnow()` (naive), never `datetime.now(timezone.utc)` (aware). Model defaults use `lambda: datetime.now(timezone.utc)` for correctness in production.

**`--force-recreate` on deploy**: `docker compose up -d --build` builds a new image but may not restart the running container. Always pass `--force-recreate web` to guarantee the new image is picked up.

**Schema migrations**: This project has no Alembic migration setup — schema changes are applied by running `seed.py` which does `db.drop_all()` + `db.create_all()`. This wipes all data. Not suitable for production with real user data — a proper migration system (Flask-Migrate / Alembic) should be added before public launch.

**Strava refresh tokens**: Club-level Strava feeds use a long-lived refresh token stored in `.env`. User-level tokens are short-lived and stored per-user in the DB.

**Cross-platform strftime**: Templates use `%-d` (Linux) for day-without-leading-zero. A `strftime` Jinja2 filter registered in `create_app()` swaps this to `%#d` on Windows so local test runs work correctly.
