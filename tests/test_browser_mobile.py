"""
Browser smoke tests for mobile-responsive layout and public-page rendering.

Uses Playwright headless Chromium against a real Flask dev server started in a
background thread.  A file-based SQLite DB is used instead of :memory: so that
the seeded data is visible across the thread boundary.

Run with:
    pip install pytest-playwright && playwright install chromium
    pytest tests/test_browser_mobile.py -v
"""
import os
import threading
import time as _time
import pytest
from datetime import date, timedelta, time as dtime

from app import create_app
from app.extensions import db as _db
from app.models import Club, Ride

MOBILE_VIEWPORT = {'width': 390, 'height': 844}
TEST_DB_PATH = os.path.join(os.path.dirname(__file__), '_browser_test.db')
SERVER_PORT = 5099


class BrowserTestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = f'sqlite:///{TEST_DB_PATH}'
    WTF_CSRF_ENABLED = False
    SECRET_KEY = 'browser-test-secret'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    STRAVA_CLIENT_ID = None
    STRAVA_CLIENT_SECRET = None
    STRAVA_CLUB_ID = None
    STRAVA_CLUB_REFRESH_TOKEN = None


@pytest.fixture(scope='module')
def server_info():
    """Start a real Flask server; yield (base_url, club_slug, ride_id)."""
    # Clean up any stale DB from a previous run
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)

    app = create_app(BrowserTestConfig)

    with app.app_context():
        _db.create_all()

        today = date.today()
        next_monday = today + timedelta(days=7 - today.weekday())

        club = Club(
            slug='browser-club',
            name='Browser Test Club',
            city='Reston', state='VA',
            lat=38.9376, lng=-77.3476,
        )
        _db.session.add(club)
        _db.session.flush()

        rides = [
            Ride(club_id=club.id, title='Tuesday A Ride',
                 date=next_monday + timedelta(days=1), time=dtime(17, 0),
                 meeting_location='Test Location', distance_miles=38.0, pace_category='A'),
            Ride(club_id=club.id, title='Wednesday B Ride',
                 date=next_monday + timedelta(days=2), time=dtime(18, 0),
                 meeting_location='Test Location', distance_miles=25.0, pace_category='B'),
            Ride(club_id=club.id, title='Saturday C Ride',
                 date=next_monday + timedelta(days=5), time=dtime(8, 0),
                 meeting_location='Test Location', distance_miles=20.0, pace_category='C'),
        ]
        for r in rides:
            _db.session.add(r)
        _db.session.commit()

        club_slug = club.slug
        first_ride_id = rides[0].id

    # Start Flask in a daemon thread
    t = threading.Thread(
        target=lambda: app.run(host='127.0.0.1', port=SERVER_PORT,
                                use_reloader=False, threaded=True),
        daemon=True,
    )
    t.start()
    _time.sleep(0.8)  # wait for server to bind

    base = f'http://127.0.0.1:{SERVER_PORT}'
    yield base, club_slug, first_ride_id

    # Best-effort cleanup — daemon thread may still hold the file on Windows
    try:
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)
    except OSError:
        pass


# ── Helpers ───────────────────────────────────────────────────────────────────

def mobile_page(browser):
    return browser.new_page(viewport=MOBILE_VIEWPORT)


def desktop_page(browser):
    return browser.new_page(viewport={'width': 1440, 'height': 900})


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_club_home_renders_on_mobile(server_info, browser):
    base, slug, _ = server_info
    page = mobile_page(browser)
    page.goto(f'{base}/clubs/{slug}/')
    page.wait_for_selector('h1')

    assert 'Browser Test Club' in page.locator('h1').inner_text()
    assert page.locator('a.btn-paceline').filter(has_text='Sign In to Join').is_visible()
    # Tab bar is present; "Rides" tab button is visible (Upcoming Rides now lives inside it)
    assert page.locator('.club-tab').filter(has_text='Rides').is_visible()

    page.screenshot(path='tests/screenshots/browser_club_home_mobile.png',
                    full_page=True)
    page.close()


def test_club_home_shows_rides(server_info, browser):
    base, slug, _ = server_info
    page = mobile_page(browser)
    page.goto(f'{base}/clubs/{slug}/')
    # Switch to the Rides tab so ride cards become visible
    page.locator('.club-tab').filter(has_text='Rides').click()
    page.wait_for_selector('.ride-card')

    cards = page.locator('.ride-card')
    assert cards.count() >= 3
    page.close()


def test_ride_list_renders_on_mobile(server_info, browser):
    base, slug, _ = server_info
    page = mobile_page(browser)
    page.goto(f'{base}/clubs/{slug}/rides/?view=list')
    page.wait_for_selector('.ride-row, .ride-card')

    assert page.locator('text=Tuesday A Ride').is_visible()
    page.screenshot(path='tests/screenshots/browser_rides_list_mobile.png',
                    full_page=True)
    page.close()


def test_week_view_has_scroll_wrapper(server_info, browser):
    """Week grid must be wrapped in .week-grid-wrap for overflow-x scrolling."""
    base, slug, _ = server_info
    page = mobile_page(browser)
    page.goto(f'{base}/clubs/{slug}/rides/?view=week')
    page.wait_for_selector('.week-grid-wrap')

    wrapper = page.locator('.week-grid-wrap')
    assert wrapper.count() == 1
    assert wrapper.is_visible()

    page.screenshot(path='tests/screenshots/browser_week_mobile.png',
                    full_page=True)
    page.close()


def test_month_view_renders_on_mobile(server_info, browser):
    base, slug, _ = server_info
    page = mobile_page(browser)
    page.goto(f'{base}/clubs/{slug}/rides/?view=month')
    page.wait_for_selector('.month-grid-wrap, .month-grid')

    assert page.locator('text=Ride Calendar').is_visible()
    page.screenshot(path='tests/screenshots/browser_month_mobile.png',
                    full_page=True)
    page.close()


def test_ride_detail_signup_card_first_on_mobile(server_info, browser):
    """Signup card (order-1) must appear above ride details (order-2) on mobile."""
    base, slug, ride_id = server_info
    page = mobile_page(browser)
    page.goto(f'{base}/clubs/{slug}/rides/{ride_id}')
    page.wait_for_selector('.signup-card')

    # Verify both sections exist
    assert page.locator('.signup-card').is_visible()
    assert page.locator('.detail-card').first.is_visible()

    # On mobile the signup-card column has order-1 so it visually appears first.
    # Check that the signup card's bounding box top < ride details top.
    signup_box = page.locator('.signup-card').bounding_box()
    detail_box = page.locator('.detail-card').first.bounding_box()
    assert signup_box['y'] < detail_box['y'], \
        'signup card should appear above ride details on mobile viewport'

    page.screenshot(path='tests/screenshots/browser_ride_detail_mobile.png',
                    full_page=True)
    page.close()


def test_map_page_embeds_clubs_no_loading_spinner(server_info, browser):
    """Map page must show club count subtitle, not stuck 'Loading clubs…'."""
    base, _, _ = server_info
    page = mobile_page(browser)
    page.goto(f'{base}/clubs/map/')
    page.wait_for_selector('#map-subtitle')

    subtitle = page.locator('#map-subtitle').inner_text()
    assert 'Loading' not in subtitle, f'Map is still showing loading state: {subtitle}'
    assert 'club' in subtitle.lower(), f'Unexpected subtitle: {subtitle}'

    page.screenshot(path='tests/screenshots/browser_map_mobile.png',
                    full_page=True)
    page.close()


def test_map_header_controls_visible_on_desktop(server_info, browser):
    """Map header controls should be readable before hover on the light header."""
    base, _, _ = server_info
    page = desktop_page(browser)
    page.goto(f'{base}/clubs/map/')
    page.wait_for_selector('#map-controls')

    assert page.locator('#map-controls .btn-outline-light').count() == 0
    secondary_controls = page.locator('#map-controls .btn-map-secondary')
    assert secondary_controls.count() >= 2
    for i in range(secondary_controls.count()):
        control = secondary_controls.nth(i)
        assert control.is_visible()
        colors = control.evaluate("""el => {
            const style = getComputedStyle(el);
            return { color: style.color, backgroundColor: style.backgroundColor };
        }""")
        assert colors['color'] not in ('rgb(255, 255, 255)', 'rgba(255, 255, 255, 1)'), (
            f"Map control '{control.inner_text()}' uses white text before hover"
        )
        assert colors['backgroundColor'] not in ('rgba(0, 0, 0, 0)', 'transparent'), (
            f"Map control '{control.inner_text()}' has no visible button background"
        )

    page.screenshot(path='tests/screenshots/browser_map_controls_desktop.png',
                    full_page=True)
    page.close()


def test_clubs_index_renders_on_mobile(server_info, browser):
    base, _, _ = server_info
    page = mobile_page(browser)
    page.goto(f'{base}/clubs/')
    page.wait_for_selector('h1')

    assert page.locator('text=Browser Test Club').is_visible()
    page.screenshot(path='tests/screenshots/browser_clubs_index_mobile.png',
                    full_page=True)
    page.close()


def test_login_page_renders_on_mobile(server_info, browser):
    base, _, _ = server_info
    page = mobile_page(browser)
    page.goto(f'{base}/auth/login')
    page.wait_for_selector('.auth-card, form')

    assert page.locator('input[type=email], input[name=email]').is_visible()
    assert page.locator('input[type=password], input[name=password]').is_visible()
    page.screenshot(path='tests/screenshots/browser_login_mobile.png',
                    full_page=True)
    page.close()
