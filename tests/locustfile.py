"""
Paceline stress test — simulates up to 1000 concurrent riders.

Three user personas at realistic think times:
  AnonBrowser   (70%) — browses clubs, discover, ride schedules without login
  AuthRider     (20%) — logs in as a test rider, views dashboard and rides
  ClubAdminUser (10%) — logs in as a club admin, checks admin pages

Requires seeded test accounts (seed.py).  If running against a fresh
production DB without seed data, disable AuthRider/ClubAdminUser classes
or supply RIDER_EMAIL / RIDER_PASSWORD env vars.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
QUICK START
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Install (one-time):
    pip3 install locust

Against production with web UI (recommended first run):
    BETA_PASSWORD=pacelinesarefast \\
        locust -f tests/locustfile.py --host https://paceline.club
    # Open http://localhost:8089 → set Users=1000, Spawn rate=50 → Start

Headless run (CI/scripted):
    BETA_PASSWORD=pacelinesarefast \\
        locust -f tests/locustfile.py \\
        --headless --users 1000 --spawn-rate 50 --run-time 3m \\
        --host https://paceline.club \\
        --html tests/stress_report_$(date +%Y%m%d_%H%M).html

Against dev server (requires temporary port exposure):
    # 1. On TrueNAS, add to web service in docker-compose.yml:
    #      ports:
    #        - "8001:8000"
    # 2. sg docker -c 'docker compose up -d --no-build'
    # 3. Run:
    BETA_PASSWORD=pacelinesaregreat \\
        locust -f tests/locustfile.py --host http://192.168.50.189:8001

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHAT TO WATCH
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

RPS (req/sec)     — throughput ceiling; plateaus when server is saturated
p50 / p95 / p99   — latency percentiles; p95 > 2s = users notice
Failure %         — any non-2xx/3xx; should stay 0% under normal load
"Users" ramp      — watch p95 vs user count to find the knee of the curve

Expected DO basic-xs limits (2 workers, 1 shared vCPU):
  ~ 20-40 RPS sustainable
  ~ 50-100 concurrent users before p95 climbs past 1s
  ~ 200+ users → queuing, timeouts, potential 503s
"""
import os
import re
import random

import requests as _requests
from locust import HttpUser, between, events, task


# ── Runtime config ────────────────────────────────────────────────────────────

BETA_PASSWORD = os.environ.get('BETA_PASSWORD', '').strip()

# Optional override: point all auth riders at one account
_RIDER_EMAIL_OVERRIDE = os.environ.get('RIDER_EMAIL', '').strip()
_RIDER_PASS_OVERRIDE  = os.environ.get('RIDER_PASSWORD', '').strip()

# Seeded accounts from seed.py (password123 for riders, password for test@pcp.dev)
_RIDER_CREDS = [
    ('john.smith@example.com',   'password123'),
    ('mary.baker@example.com',   'password123'),
    ('tom.wheels@example.com',   'password123'),
    ('kate.roller@example.com',  'password123'),
    ('dave.keller@example.com',  'password123'),
    ('sarah.martin@example.com', 'password123'),
    ('alex.rider@example.com',   'password123'),
    ('beth.climber@example.com', 'password123'),
    ('claire.spin@example.com',  'password123'),
]
if _RIDER_EMAIL_OVERRIDE and _RIDER_PASS_OVERRIDE:
    _RIDER_CREDS = [(_RIDER_EMAIL_OVERRIDE, _RIDER_PASS_OVERRIDE)]

# Club-admin credentials mapped to their club slug
_ADMIN_MAP = [
    ('test@pcp.dev',        'password',   'rbc'),
    ('admin@nvcc.dev',      'password123', 'nvcc'),
    ('admin@artemis.dev',   'password123', 'artemis'),
]


# ── Startup: discover public clubs and ride URLs ──────────────────────────────

_CLUB_SLUGS: list[str] = []
_RIDE_URLS:  list[str] = []


@events.init.add_listener
def _discover_urls(environment, **kwargs):
    """
    Before workers spawn, query the live server for available clubs and
    a sample of upcoming ride URLs.  Runs once in the main process.
    """
    host = environment.host or 'http://localhost:8000'
    s = _requests.Session()
    s.headers['User-Agent'] = 'Paceline-Locust/1.0 (stress test)'

    # Unlock beta gate once so the discovery requests can get through
    if BETA_PASSWORD:
        try:
            s.post(f'{host}/_beta',
                   data={'password': BETA_PASSWORD, 'next': '/'},
                   timeout=15)
        except Exception as e:
            print(f'[locust] beta gate unlock failed: {e}')

    # Club slugs via the public map API
    try:
        resp = s.get(f'{host}/api/clubs/map-data', timeout=15)
        if resp.ok:
            for club in resp.json():
                slug = club.get('slug')
                if slug:
                    _CLUB_SLUGS.append(slug)
    except Exception as e:
        print(f'[locust] club discovery failed: {e}')

    # A few ride detail URLs per club — parse ids from the rides list page
    for slug in _CLUB_SLUGS[:5]:
        try:
            resp = s.get(f'{host}/clubs/{slug}/rides/', timeout=15)
            if resp.ok:
                ids = re.findall(
                    r'/clubs/' + re.escape(slug) + r'/rides/(\d+)',
                    resp.text,
                )
                for rid in ids[:6]:  # cap at 6 per club
                    _RIDE_URLS.append(f'/clubs/{slug}/rides/{rid}')
        except Exception:
            pass

    print(f'\n[locust] discovered: {len(_CLUB_SLUGS)} clubs, '
          f'{len(_RIDE_URLS)} ride detail URLs')
    if not _CLUB_SLUGS:
        print('[locust] WARNING: no public clubs — club tasks will be skipped. '
              'Run seed.py on the target server or make clubs visible.')


# ── Shared helpers ────────────────────────────────────────────────────────────

def _beta_unlock(client):
    """Submit the beta gate form once per virtual user session."""
    if not BETA_PASSWORD:
        return
    client.post(
        '/_beta',
        data={'password': BETA_PASSWORD, 'next': '/'},
        name='/_beta [gate]',
    )


def _login(client, email, password, name='/auth/login'):
    with client.post(
        '/auth/login',
        data={'email': email, 'password': password},
        allow_redirects=True,
        name=name,
        catch_response=True,
    ) as resp:
        # A successful login redirects to / or wherever; failure stays on /auth/login
        if '/auth/login' in resp.url and resp.status_code == 200:
            resp.failure(f'Login rejected for {email}')


# ── User personas ─────────────────────────────────────────────────────────────

class AnonBrowser(HttpUser):
    """
    Anonymous visitor — 70% of traffic.
    Browses the public club directory, discover rides, and club pages.
    Think time 2-8s to simulate casual mobile and desktop browsing.
    """
    weight = 7
    wait_time = between(2, 8)

    def on_start(self):
        _beta_unlock(self.client)

    @task(4)
    def homepage(self):
        self.client.get('/', name='/ [anon]')

    @task(3)
    def clubs_index(self):
        self.client.get('/clubs/', name='/clubs/')

    @task(2)
    def club_map(self):
        self.client.get('/clubs/map/', name='/clubs/map/')

    @task(2)
    def discover(self):
        self.client.get('/discover/', name='/discover/')

    @task(5)
    def club_home(self):
        if _CLUB_SLUGS:
            slug = random.choice(_CLUB_SLUGS)
            self.client.get(f'/clubs/{slug}/', name='/clubs/<slug>/')

    @task(4)
    def club_ride_list(self):
        if _CLUB_SLUGS:
            slug = random.choice(_CLUB_SLUGS)
            self.client.get(f'/clubs/{slug}/rides/', name='/clubs/<slug>/rides/')

    @task(3)
    def ride_detail(self):
        if _RIDE_URLS:
            self.client.get(random.choice(_RIDE_URLS),
                            name='/clubs/<slug>/rides/<id>')

    @task(1)
    def map_api(self):
        self.client.get('/api/clubs/map-data', name='/api/clubs/map-data')

    @task(1)
    def login_page(self):
        self.client.get('/auth/login', name='/auth/login [page]')


class AuthRider(HttpUser):
    """
    Authenticated rider — 20% of traffic.
    Logs in and checks their ride dashboard, discover page, and profile.
    Think time 3-10s — slightly more deliberate than anonymous browsing.
    """
    weight = 2
    wait_time = between(3, 10)

    def on_start(self):
        _beta_unlock(self.client)
        email, pw = random.choice(_RIDER_CREDS)
        _login(self.client, email, pw)

    @task(5)
    def dashboard(self):
        self.client.get('/', name='/ [dashboard]')

    @task(3)
    def discover_all(self):
        self.client.get('/discover/?source=all', name='/discover/ [all]')

    @task(3)
    def club_home(self):
        if _CLUB_SLUGS:
            slug = random.choice(_CLUB_SLUGS)
            self.client.get(f'/clubs/{slug}/', name='/clubs/<slug>/ [auth]')

    @task(3)
    def ride_detail(self):
        if _RIDE_URLS:
            self.client.get(random.choice(_RIDE_URLS),
                            name='/clubs/<slug>/rides/<id> [auth]')

    @task(2)
    def club_ride_list(self):
        if _CLUB_SLUGS:
            slug = random.choice(_CLUB_SLUGS)
            self.client.get(f'/clubs/{slug}/rides/', name='/clubs/<slug>/rides/ [auth]')

    @task(1)
    def profile(self):
        self.client.get('/auth/profile', name='/auth/profile')

    @task(1)
    def my_rides(self):
        self.client.get('/my-rides/', name='/my-rides/')


class ClubAdminUser(HttpUser):
    """
    Club admin — 10% of traffic.
    Checks their admin dashboard and ride list.
    Think time 5-15s — deliberate, task-focused sessions.
    """
    weight = 1
    wait_time = between(5, 15)

    def on_start(self):
        _beta_unlock(self.client)
        # Rotate through admin accounts; each admin manages one club
        entry = random.choice(_ADMIN_MAP)
        email, pw, slug = entry
        self._slug = slug
        _login(self.client, email, pw, name='/auth/login [admin]')

    @task(4)
    def admin_dashboard(self):
        self.client.get(f'/admin/clubs/{self._slug}/',
                        name='/admin/clubs/<slug>/')

    @task(3)
    def admin_rides(self):
        self.client.get(f'/admin/clubs/{self._slug}/rides/',
                        name='/admin/clubs/<slug>/rides/')

    @task(2)
    def admin_team(self):
        self.client.get(f'/admin/clubs/{self._slug}/team/',
                        name='/admin/clubs/<slug>/team/')

    @task(1)
    def admin_settings(self):
        self.client.get(f'/admin/clubs/{self._slug}/settings/',
                        name='/admin/clubs/<slug>/settings/')
