"""
Visual screenshot tests for the white/grey retheme.
Run: pytest tests/test_screenshot_retheme.py -v -s
Screenshots saved to tests/screenshots/retheme/
"""
import os, threading, time as _time
from datetime import date, timedelta, time as dtime
import pytest
from app import create_app
from app.extensions import db as _db
from app.models import Club, Ride, User, ClubMembership
from app.extensions import bcrypt

DESKTOP = {'width': 1440, 'height': 900}
MOBILE  = {'width': 390,  'height': 844}
PORT    = 5204
DB_PATH = os.path.join(os.path.dirname(__file__), '_retheme_test.db')
OUT_DIR = os.path.join(os.path.dirname(__file__), 'screenshots', 'retheme')


class Cfg:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = f'sqlite:///{DB_PATH}'
    WTF_CSRF_ENABLED = False
    SECRET_KEY = 'retheme-secret'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    STRAVA_CLIENT_ID = STRAVA_CLIENT_SECRET = STRAVA_CLUB_ID = STRAVA_CLUB_REFRESH_TOKEN = None


@pytest.fixture(scope='module')
def srv():
    os.makedirs(OUT_DIR, exist_ok=True)
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    app = create_app(Cfg)
    today = date.today()

    with app.app_context():
        _db.create_all()

        club = Club(
            slug='test-rbc', name='Reston Bike Club',
            tagline="Northern Virginia's premier road cycling community",
            description='Weekly rides for all levels — from beginner to racer.',
            city='Reston', state='VA', zip_code='20191',
            is_active=True, is_hidden=False,
        )
        _db.session.add(club)
        _db.session.flush()

        for i, (title, pace, days) in enumerate([
            ('Tuesday Worlds — A Group', 'A', 2),
            ('Wednesday Ramble', 'C', 3),
            ('Saturday Long Ride', 'B', 5),
        ]):
            _db.session.add(Ride(
                club_id=club.id, title=title, pace_category=pace,
                date=today + timedelta(days=days),
                time=dtime(8 + i, 0),
                distance_miles=30 + i * 5,
                elevation_feet=800 + i * 200,
                meeting_location='Lake Fairfax Park',
            ))

        pw = bcrypt.generate_password_hash('password').decode('utf-8')
        user = User(username='testphil', email='phil@test.com', password_hash=pw, zip_code='20148')
        _db.session.add(user)
        _db.session.flush()

        _db.session.add(ClubMembership(user_id=user.id, club_id=club.id, status='active'))
        _db.session.commit()

    t = threading.Thread(
        target=lambda: app.run(host='127.0.0.1', port=PORT,
                               use_reloader=False, threaded=True),
        daemon=True,
    )
    t.start()
    _time.sleep(1.0)
    yield f'http://127.0.0.1:{PORT}'

    try:
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
    except OSError:
        pass


def test_landing_page_desktop(srv, browser):
    """Landing page hero — should be dark charcoal, not green."""
    page = browser.new_page(viewport=DESKTOP)
    page.goto(srv)
    page.wait_for_selector('.paceline-hero')
    page.wait_for_timeout(500)
    page.screenshot(path=f'{OUT_DIR}/01_landing_desktop.png', full_page=True)
    page.close()


def test_landing_page_mobile(srv, browser):
    page = browser.new_page(viewport=MOBILE)
    page.goto(srv)
    page.wait_for_selector('.paceline-hero')
    page.wait_for_timeout(400)
    page.screenshot(path=f'{OUT_DIR}/02_landing_mobile.png', full_page=True)
    page.close()


def test_navbar_closeup(srv, browser):
    """Navbar should be white with dark logo."""
    page = browser.new_page(viewport=DESKTOP)
    page.goto(srv)
    page.wait_for_selector('.paceline-navbar')
    nav = page.locator('.paceline-navbar')
    nav.screenshot(path=f'{OUT_DIR}/03_navbar_closeup.png')
    page.close()


def test_footer_closeup(srv, browser):
    """Footer should be dark charcoal."""
    page = browser.new_page(viewport=DESKTOP)
    page.goto(srv)
    page.wait_for_selector('.paceline-footer')
    page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
    page.wait_for_timeout(300)
    footer = page.locator('.paceline-footer')
    footer.screenshot(path=f'{OUT_DIR}/04_footer_closeup.png')
    page.close()


def test_find_clubs_page(srv, browser):
    """Find clubs page — page header should be light grey."""
    page = browser.new_page(viewport=DESKTOP)
    page.goto(f'{srv}/clubs/')
    page.wait_for_selector('.page-header')
    page.wait_for_timeout(400)
    page.screenshot(path=f'{OUT_DIR}/05_find_clubs_desktop.png', full_page=True)
    page.close()


def test_club_home_nav(srv, browser):
    """Club page tab bar is present."""
    page = browser.new_page(viewport=DESKTOP)
    page.goto(f'{srv}/clubs/test-rbc/')
    page.wait_for_selector('.club-tab-bar')
    page.wait_for_timeout(800)
    nav = page.locator('.club-tab-bar')
    nav.screenshot(path=f'{OUT_DIR}/06_club_nav_closeup.png')
    page.close()


def test_club_home_full(srv, browser):
    """Full club home — check overall look."""
    page = browser.new_page(viewport=DESKTOP)
    page.goto(f'{srv}/clubs/test-rbc/')
    page.wait_for_selector('.club-hero-name')
    page.wait_for_timeout(800)
    page.screenshot(path=f'{OUT_DIR}/07_club_home_full.png', full_page=True)
    page.close()


def test_dashboard_logged_in(srv, browser):
    """Dashboard page header should be light grey with dark text."""
    page = browser.new_page(viewport=DESKTOP)
    page.goto(f'{srv}/auth/login')
    page.wait_for_selector('input[name="email"]')
    page.fill('input[name="email"]', 'phil@test.com')
    page.fill('input[name="password"]', 'password')
    page.locator('input[type="submit"]').click()
    page.wait_for_selector('.page-header', timeout=5000)
    page.wait_for_timeout(500)
    page.screenshot(path=f'{OUT_DIR}/08_dashboard.png', full_page=True)
    page.close()


def test_dashboard_page_header(srv, browser):
    """Closeup of page header — should be light grey, not dark green."""
    page = browser.new_page(viewport=DESKTOP)
    page.goto(f'{srv}/auth/login')
    page.wait_for_selector('input[name="email"]')
    page.fill('input[name="email"]', 'phil@test.com')
    page.fill('input[name="password"]', 'password')
    page.locator('input[type="submit"]').click()
    page.wait_for_selector('.page-header', timeout=5000)
    header = page.locator('.page-header')
    header.screenshot(path=f'{OUT_DIR}/09_page_header_closeup.png')
    page.close()
