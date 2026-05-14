"""
Performance regression tests.

Measures median response time over several repetitions using the Flask test
client (SQLite in-memory, no network).  The goal is regression detection, not
micro-benchmarking — budgets are set at ~5-10x typical observed time so they
flag order-of-magnitude regressions (N+1 queries, runaway loops, missing eager
loads) without flapping on normal variance.

SQLite is faster than Managed PostgreSQL in production; add ~5-20ms per query
for production estimates.

Run standalone:
    pytest tests/test_perf.py -v
    pytest tests/test_perf.py -v -s   # prints timing table even on pass
"""
import statistics
import time
import pytest
from datetime import date, time as dtime, timedelta

from app.extensions import db
from app.models import Club, ClubMembership, Ride, RideSignup

from tests.conftest import login

# ── Budget thresholds (milliseconds) ─────────────────────────────────────────
# fast:   forms and pages with ≤1 DB query
# normal: pages with a handful of queries and template rendering
# heavy:  pages that aggregate across clubs/rides or call mocked weather

BUDGET = {
    'fast':   80,
    'normal': 250,
    'heavy':  500,
}

REPS = 7  # requests per route; median is reported


# ── Helpers ───────────────────────────────────────────────────────────────────

def _timings(client, path, reps=REPS, follow_redirects=False):
    """Return a list of elapsed-ms measurements for GET path."""
    results = []
    for _ in range(reps):
        t0 = time.perf_counter()
        client.get(path, follow_redirects=follow_redirects)
        results.append((time.perf_counter() - t0) * 1000)
    return results


def _assert(timings, budget_ms, label):
    med = statistics.median(timings)
    p95 = sorted(timings)[int(len(timings) * 0.95)]
    print(f'\n  {label}: median={med:.0f}ms  p95={p95:.0f}ms  budget={budget_ms}ms')
    assert med < budget_ms, (
        f'{label}: median {med:.0f}ms exceeds {budget_ms}ms budget'
    )


# ── Multi-club fixture ────────────────────────────────────────────────────────

@pytest.fixture
def multi_club_setup(db, regular_user):
    """
    Three clubs with 5 rides each and the regular_user joined to all of them.
    Exercises the dashboard and discover aggregation paths with realistic
    (though small) data volume.
    """
    today = date.today()
    next_monday = today + timedelta(days=7 - today.weekday())
    clubs = []
    for i in range(3):
        club = Club(
            slug=f'perf-club-{i}',
            name=f'Perf Club {i}',
            city='Reston', state='VA', zip_code='20191',
            lat=38.9376, lng=-77.3476,
            is_hidden=False,
        )
        db.session.add(club)
        db.session.flush()
        db.session.add(ClubMembership(
            user_id=regular_user.id, club_id=club.id, status='active',
        ))
        for j in range(5):
            db.session.add(Ride(
                club_id=club.id,
                title=f'Ride {j} of Club {i}',
                date=next_monday + timedelta(days=j),
                time=dtime(17, 0),
                meeting_location='Test Location',
                distance_miles=25.0,
                pace_category='B',
                ride_type='road',
            ))
        clubs.append(club)
    db.session.commit()
    return clubs, regular_user


# ── Anonymous routes ──────────────────────────────────────────────────────────

class TestAnonPerf:
    def test_health_endpoint(self, client):
        t = _timings(client, '/health')
        _assert(t, BUDGET['fast'], 'GET /health')

    def test_login_page(self, client):
        t = _timings(client, '/auth/login')
        _assert(t, BUDGET['fast'], 'GET /auth/login')

    def test_register_page(self, client):
        t = _timings(client, '/auth/register')
        _assert(t, BUDGET['fast'], 'GET /auth/register')

    def test_homepage_anon(self, client, sample_club):
        t = _timings(client, '/')
        _assert(t, BUDGET['normal'], 'GET / (anon)')

    def test_clubs_index(self, client, sample_club):
        t = _timings(client, '/clubs/')
        _assert(t, BUDGET['normal'], 'GET /clubs/')

    def test_club_map_page(self, client, sample_club):
        # Map page is a shell — data loads via JS/API
        t = _timings(client, '/clubs/map/')
        _assert(t, BUDGET['fast'], 'GET /clubs/map/')

    def test_club_map_api(self, client, sample_club):
        t = _timings(client, '/api/clubs/map-data')
        _assert(t, BUDGET['normal'], 'GET /api/clubs/map-data')

    def test_club_home(self, client, sample_club, sample_rides, mock_weather):
        t = _timings(client, f'/clubs/{sample_club.slug}/')
        _assert(t, BUDGET['normal'], 'GET /clubs/{slug}/')

    def test_club_ride_list(self, client, sample_club, sample_rides, mock_weather):
        t = _timings(client, f'/clubs/{sample_club.slug}/rides/')
        _assert(t, BUDGET['normal'], 'GET /clubs/{slug}/rides/')

    def test_club_ride_list_week_view(self, client, sample_club, sample_rides, mock_weather):
        t = _timings(client, f'/clubs/{sample_club.slug}/rides/?view=week')
        _assert(t, BUDGET['normal'], 'GET /clubs/{slug}/rides/?view=week')

    def test_ride_detail(self, client, sample_club, sample_rides, mock_weather):
        ride = sample_rides[0]
        t = _timings(client, f'/clubs/{sample_club.slug}/rides/{ride.id}')
        _assert(t, BUDGET['normal'], 'GET /clubs/{slug}/rides/{id}')

    def test_discover_all_source(self, client, sample_rides, mock_weather):
        t = _timings(client, '/discover/?source=all')
        _assert(t, BUDGET['heavy'], 'GET /discover/?source=all')

    def test_discover_verified_source(self, client, sample_rides, mock_weather):
        t = _timings(client, '/discover/')
        _assert(t, BUDGET['heavy'], 'GET /discover/ (verified)')


# ── Authenticated routes ──────────────────────────────────────────────────────

class TestAuthPerf:
    def test_dashboard_no_clubs(self, client, regular_user, mock_weather):
        login(client)
        t = _timings(client, '/')
        _assert(t, BUDGET['normal'], 'GET / (dashboard, no memberships)')

    def test_dashboard_with_clubs(self, client, multi_club_setup, mock_weather):
        _, user = multi_club_setup
        login(client)
        t = _timings(client, '/')
        _assert(t, BUDGET['heavy'], 'GET / (dashboard, 3 clubs × 5 rides)')

    def test_profile_page(self, client, regular_user):
        login(client)
        t = _timings(client, '/auth/profile')
        _assert(t, BUDGET['normal'], 'GET /auth/profile')

    def test_my_rides_page(self, client, regular_user):
        login(client)
        t = _timings(client, '/my-rides/')
        _assert(t, BUDGET['normal'], 'GET /my-rides/')

    def test_discover_authenticated(self, client, multi_club_setup, mock_weather):
        _, user = multi_club_setup
        login(client)
        t = _timings(client, '/discover/?source=all')
        _assert(t, BUDGET['heavy'], 'GET /discover/ (authenticated)')


# ── Club admin routes ─────────────────────────────────────────────────────────

class TestAdminPerf:
    def test_club_admin_dashboard(self, client, club_admin_user, sample_club, sample_rides):
        login(client, email='clubadmin@test.com')
        t = _timings(client, f'/admin/clubs/{sample_club.slug}/')
        _assert(t, BUDGET['normal'], 'GET /admin/clubs/{slug}/')

    def test_club_admin_rides_list(self, client, club_admin_user, sample_club, sample_rides):
        login(client, email='clubadmin@test.com')
        t = _timings(client, f'/admin/clubs/{sample_club.slug}/rides/')
        _assert(t, BUDGET['normal'], 'GET /admin/clubs/{slug}/rides/')

    def test_club_new_ride_form(self, client, club_admin_user, sample_club):
        login(client, email='clubadmin@test.com')
        t = _timings(client, f'/admin/clubs/{sample_club.slug}/rides/new')
        _assert(t, BUDGET['fast'], 'GET /admin/clubs/{slug}/rides/new')


# ── Signup write path ─────────────────────────────────────────────────────────

class TestWritePerf:
    """
    Write-path timing.  Each rep signs up then cancels to avoid state buildup.
    Measures the round-trip time of the most common user action.
    """

    def test_ride_signup_cancel_cycle(
        self, client, regular_user, sample_club, sample_rides, mock_weather
    ):
        db.session.add(
            ClubMembership(user_id=regular_user.id, club_id=sample_club.id, status='active')
        )
        db.session.commit()
        login(client)

        ride = sample_rides[0]
        signup_url  = f'/clubs/{sample_club.slug}/rides/{ride.id}/signup'
        cancel_url  = f'/clubs/{sample_club.slug}/rides/{ride.id}/cancel'

        times = []
        for _ in range(REPS):
            t0 = time.perf_counter()
            client.post(signup_url, follow_redirects=True)
            times.append((time.perf_counter() - t0) * 1000)
            client.post(cancel_url, follow_redirects=True)

        _assert(times, BUDGET['normal'], 'POST ride signup')
