"""
Browser workflow tests: New User Registration â†’ Join Club â†’ Ride Signup

Runs a real Flask dev server in a background thread and drives it with Playwright
headless Chromium, taking a screenshot at every key step of the workflow.

Screenshots are written to tests/screenshots/wf_new_user_*.png

Scenarios
---------
A  Happy path (auto-approval club)
   register â†’ club directory â†’ club home â†’ join â†’ waiver â†’ ride detail â†’ signup

B  Manual-approval path
   register â†’ join (pending state shown) â†’ admin approves â†’ ride now accessible

Run with:
    pip install pytest-playwright && playwright install chromium
    pytest tests/test_browser_workflow_new_user.py -v -s
"""
import os
import threading
import time as _time
import pytest
from datetime import date, time as dtime, timedelta

from app import create_app
from app.extensions import db as _db
from app.models import (
    Club, Ride, ClubWaiver, User, ClubAdmin, ClubMembership,
)

SCREENSHOTS_DIR = os.path.join(os.path.dirname(__file__), 'screenshots')
SERVER_PORT = 5201
TEST_DB_PATH = os.path.join(os.path.dirname(__file__), '_wf_new_user.db')

os.makedirs(SCREENSHOTS_DIR, exist_ok=True)


class WFTestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = f'sqlite:///{TEST_DB_PATH}'
    WTF_CSRF_ENABLED = False
    SECRET_KEY = 'wf-new-user-secret'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    STRAVA_CLIENT_ID = None
    STRAVA_CLIENT_SECRET = None
    STRAVA_CLUB_ID = None
    STRAVA_CLUB_REFRESH_TOKEN = None


# â”€â”€ Module-level server fixture â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@pytest.fixture(scope='module')
def server_info():
    """
    Start a Flask dev server with a seeded club, waiver, and future rides.
    Yields a dict with base_url and key IDs.
    """
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)

    app = create_app(WFTestConfig)
    from app.extensions import bcrypt

    today = date.today()
    next_sat = today + timedelta(days=(5 - today.weekday()) % 7 or 7)

    with app.app_context():
        _db.create_all()

        # Auto-approval club with waiver and rides
        auto_club = Club(
            slug='rbc', name='Reston Bike Club',
            city='Reston', state='VA', zip_code='20191',
            lat=38.9376, lng=-77.3476,
            join_approval='auto', require_membership=True,
            theme_primary='#2d6a4f', theme_accent='#e76f51',
            description='A community cycling club for all abilities.',
        )
        _db.session.add(auto_club)
        _db.session.flush()

        waiver = ClubWaiver(
            club_id=auto_club.id, year=today.year,
            title='RBC Annual Riding Waiver',
            body='By signing, I acknowledge the risks of cycling and agree to '
                 'ride safely, follow traffic laws, and wear a helmet.',
        )
        _db.session.add(waiver)

        rides = [
            Ride(
                club_id=auto_club.id, title='Saturday A Ride',
                date=next_sat, time=dtime(8, 0),
                meeting_location='Hunterwoods Shopping Center',
                distance_miles=40.0, elevation_feet=2200, pace_category='A',
                ride_type='road',
                ride_leader='Dave K.',
            ),
            Ride(
                club_id=auto_club.id, title='Saturday B Ride',
                date=next_sat, time=dtime(8, 0),
                meeting_location='Hunterwoods Shopping Center',
                distance_miles=30.0, elevation_feet=1500, pace_category='B',
                ride_type='road',
            ),
            Ride(
                club_id=auto_club.id, title='Tuesday Evening C Ride',
                date=today + timedelta(days=((1 - today.weekday()) % 7 or 7)),
                time=dtime(18, 30),
                meeting_location='The Bike Lane',
                distance_miles=20.0, pace_category='C',
                ride_type='road',
            ),
        ]
        for r in rides:
            _db.session.add(r)
        _db.session.flush()

        auto_club_slug = auto_club.slug
        first_ride_id = rides[0].id

        # Manual-approval club
        manual_club = Club(
            slug='nvcc', name='Northern Virginia Cycling Club',
            city='McLean', state='VA', zip_code='22101',
            lat=38.9339, lng=-77.1773,
            join_approval='manual', require_membership=True,
            is_private=True,
            theme_primary='#1a5276', theme_accent='#f39c12',
        )
        _db.session.add(manual_club)
        _db.session.flush()

        # Admin user for manual club + member approvals
        club_admin = User(
            username='rbcadmin',
            email='admin@rbc.example.com',
            password_hash=bcrypt.generate_password_hash('AdminPass1!').decode(),
            is_admin=False,
        )
        _db.session.add(club_admin)
        _db.session.flush()
        _db.session.add(ClubAdmin(
            user_id=club_admin.id, club_id=manual_club.id, role='admin'))

        manual_waiver = ClubWaiver(
            club_id=manual_club.id, year=today.year,
            title='NVCC Annual Waiver',
            body='I understand the inherent risks of competitive cycling.',
        )
        _db.session.add(manual_waiver)
        _db.session.add(Ride(
            club_id=manual_club.id, title='NVCC Saturday Hammerfest',
            date=next_sat, time=dtime(7, 30),
            meeting_location='Lake Accotink Parking Lot',
            distance_miles=50.0, elevation_feet=3100, pace_category='A',
            ride_type='road',
        ))

        _db.session.commit()
        manual_club_slug = manual_club.slug

    # Start Flask in a daemon thread
    t = threading.Thread(
        target=lambda: app.run(
            host='127.0.0.1', port=SERVER_PORT,
            use_reloader=False, threaded=True,
        ),
        daemon=True,
    )
    t.start()
    _time.sleep(1.0)

    base = f'http://127.0.0.1:{SERVER_PORT}'
    yield {
        'base': base,
        'auto_club_slug': auto_club_slug,
        'manual_club_slug': manual_club_slug,
        'first_ride_id': first_ride_id,
    }

    try:
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)
    except OSError:
        pass


# â”€â”€ Auth helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _register_user(page, base, username, email, password='TestPass1!'):
    """Fill and submit the registration form via the browser."""
    page.goto(f'{base}/auth/register')
    page.wait_for_selector('input[name="username"]')
    page.fill('input[name="username"]', username)
    page.fill('input[name="email"]', email)
    page.fill('input[name="password"]', password)
    page.fill('input[name="confirm_password"]', password)
    page.check('input[name="policy_ack"]')
    page.click('button[type="submit"], input[type="submit"]')
    page.wait_for_load_state('networkidle')


def _logout_user(page, base):
    """Log out the current user."""
    page.goto(f'{base}/')
    page.request.post(f'{base}/auth/logout')
    page.wait_for_load_state('networkidle')


def _login_user(page, base, email, password='TestPass1!'):
    """Log out any current user, then log in via the login form."""
    _logout_user(page, base)
    page.goto(f'{base}/auth/login')
    page.wait_for_selector('input[name="email"]')
    page.fill('input[name="email"]', email)
    page.fill('input[name="password"]', password)
    page.click('button[type="submit"], input[type="submit"]')
    page.wait_for_load_state('networkidle')


def _shot(page, name):
    """Save a full-page screenshot."""
    path = os.path.join(SCREENSHOTS_DIR, f'wf_new_user_{name}.png')
    page.screenshot(path=path, full_page=True)


# â”€â”€ Scenario A: Auto-approval club happy path â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def test_scenario_a_register_join_auto_club_signup(server_info, browser):
    """
    Complete new-user journey through a public auto-approval club.

    Screenshots:
      01_homepage          â€” landing page before login
      02_register          â€” registration form
      03_after_register    â€” page after successful registration
      04_club_directory    â€” /clubs/ listing
      05_club_home         â€” club home page
      06_after_join        â€” club home after joining (shows member state)
      07_waiver            â€” waiver acceptance page
      08_after_waiver      â€” page after signing waiver
      09_ride_detail       â€” ride detail page with signup card
      10_after_signup      â€” ride detail after signing up (roster count updated)
    """
    base = server_info['base']
    slug = server_info['auto_club_slug']
    ride_id = server_info['first_ride_id']

    context = browser.new_context()
    page = context.new_page()

    # 01: Homepage (unauthenticated)
    page.goto(f'{base}/')
    page.wait_for_load_state('networkidle')
    _shot(page, '01_homepage')

    # 02: Registration form
    page.goto(f'{base}/auth/register')
    page.wait_for_selector('input[name="username"]')
    _shot(page, '02_register')

    # Register the new user
    page.fill('input[name="username"]', 'newrider')
    page.fill('input[name="email"]', 'newrider@wf.example.com')
    page.fill('input[name="password"]', 'TestPass1!')
    page.fill('input[name="confirm_password"]', 'TestPass1!')
    page.check('input[name="policy_ack"]')
    _shot(page, '02_register_filled')
    page.click('button[type="submit"], input[type="submit"]')
    page.wait_for_load_state('networkidle')

    # 03: After registration — redirected to login page; log in explicitly
    _shot(page, '03_after_register')
    _login_user(page, base, 'newrider@wf.example.com')

    # 04: Club directory
    page.goto(f'{base}/clubs/')
    page.wait_for_selector('h1')
    assert 'Reston Bike Club' in page.content(), \
        'Club should be visible in directory'
    _shot(page, '04_club_directory')

    # 05: Club home page
    page.goto(f'{base}/clubs/{slug}/')
    page.wait_for_selector('h1')
    _shot(page, '05_club_home')

    # 06: Join club
    join_btn = page.locator('form[action*="/join"] button, a[href*="/join"]').first
    if join_btn.count() == 0:
        # Try submitting the join form directly
        page.evaluate(
            "document.querySelector('form[action*=\"/join\"]')?.submit()"
        )
    else:
        join_btn.click()
    page.wait_for_load_state('networkidle')
    _shot(page, '06_after_join')

    # 07: Waiver page
    page.goto(f'{base}/clubs/{slug}/waiver')
    page.wait_for_selector('input[name="agree"], .waiver-body, h1')
    _shot(page, '07_waiver')

    # Sign the waiver
    agree_box = page.locator('input[name="agree"]')
    if agree_box.count() > 0:
        agree_box.check()
    page.click('button[type="submit"], input[type="submit"]')
    page.wait_for_load_state('networkidle')
    _shot(page, '08_after_waiver')

    # 09: Ride detail
    page.goto(f'{base}/clubs/{slug}/rides/{ride_id}')
    page.wait_for_selector('.signup-card, h1, .ride-title')
    _shot(page, '09_ride_detail')

    # Sign up for ride
    signup_btn = page.locator(
        'form[action*="/signup"] button[type="submit"], '
        'button:has-text("Sign Up"), button:has-text("Join Ride")'
    ).first
    if signup_btn.count() > 0:
        signup_btn.click()
        page.wait_for_load_state('networkidle')
    _shot(page, '10_after_signup')

    page.close()
    context.close()


# â”€â”€ Scenario B: Manual-approval club â€” pending state + admin approval â”€â”€â”€â”€â”€â”€â”€â”€â”€

def test_scenario_b_manual_club_pending_then_approved(server_info, browser):
    """
    Join a manual-approval club â†’ pending state shown â†’ admin approves â†’ access.

    Screenshots:
      11_manual_club_home    â€” club home as non-member
      12_after_join_pending  â€” club home after joining (pending state)
      13_pending_blocked     â€” ride page showing membership required
      14_admin_team_page     â€” admin team/membership management page
      15_after_approval      â€” club home as newly approved member
      16_member_ride_detail  â€” ride page accessible to approved member
    """
    base = server_info['base']
    manual_slug = server_info['manual_club_slug']

    context = browser.new_context()
    page = context.new_page()

    # Register a new user for this scenario, then log in
    _register_user(page, base, 'pendinguser', 'pending@wf.example.com')
    _login_user(page, base, 'pending@wf.example.com')

    # 11: Manual club home
    page.goto(f'{base}/clubs/{manual_slug}/')
    page.wait_for_selector('h1')
    _shot(page, '11_manual_club_home')

    # Join â†’ pending
    join_form = page.locator('form[action*="/join"]')
    if join_form.count() > 0:
        join_form.locator('button').click()
        page.wait_for_load_state('networkidle')

    # 12: After join (should show pending state)
    page.goto(f'{base}/clubs/{manual_slug}/')
    page.wait_for_load_state('networkidle')
    _shot(page, '12_after_join_pending')

    # 13: Try to access a ride while pending â€” should see membership required
    # Find a ride by navigating to rides page
    page.goto(f'{base}/clubs/{manual_slug}/rides/')
    page.wait_for_load_state('networkidle')
    _shot(page, '13_rides_while_pending')

    # 14: Admin logs in and views team/membership page
    _login_user(page, base, 'admin@rbc.example.com', 'AdminPass1!')
    page.goto(f'{base}/admin/clubs/{manual_slug}/team')
    page.wait_for_selector('h1, .card')
    _shot(page, '14_admin_team_page')

    # Approve the pending member â€” find the approve button on the team page
    approve_btn = page.locator(
        'form[action*="/approve"] button, button:has-text("Approve")'
    ).first
    if approve_btn.count() > 0:
        approve_btn.click()
        page.wait_for_load_state('networkidle')
        _shot(page, '14b_after_approval_admin_view')

    # 15: Approved member logs in and views club home
    _login_user(page, base, 'pending@wf.example.com', 'TestPass1!')
    page.goto(f'{base}/clubs/{manual_slug}/')
    page.wait_for_load_state('networkidle')
    _shot(page, '15_member_club_home')

    # 16: Ride detail now accessible (waiver page first)
    page.goto(f'{base}/clubs/{manual_slug}/rides/')
    page.wait_for_load_state('networkidle')
    _shot(page, '16_member_ride_list')

    page.close()
    context.close()


# â”€â”€ Scenario C: Public pages (no login) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def test_scenario_c_public_pages_screenshot_tour(server_info, browser):
    """
    Screenshot tour of all key public pages without logging in.

    Screenshots:
      20_public_club_directory  â€” /clubs/
      21_public_club_map        â€” /clubs/map/
      22_public_club_home       â€” /clubs/<slug>/
      23_public_ride_list       â€” /clubs/<slug>/rides/?view=list
      24_public_ride_detail     â€” /clubs/<slug>/rides/<id>
      25_public_login_prompt    â€” join button redirects to login
    """
    base = server_info['base']
    slug = server_info['auto_club_slug']
    ride_id = server_info['first_ride_id']

    context = browser.new_context()
    page = context.new_page()

    # 20: Club directory
    page.goto(f'{base}/clubs/')
    page.wait_for_selector('h1')
    _shot(page, '20_public_club_directory')

    # 21: Club map
    page.goto(f'{base}/clubs/map/')
    page.wait_for_selector('#map-subtitle, #map', timeout=5000)
    _shot(page, '21_public_club_map')

    # 22: Club home
    page.goto(f'{base}/clubs/{slug}/')
    page.wait_for_selector('h1')
    _shot(page, '22_public_club_home')

    # 23: Ride list
    page.goto(f'{base}/clubs/{slug}/rides/?view=list')
    page.wait_for_selector('.ride-row, .ride-card, h1')
    _shot(page, '23_public_ride_list')

    # 24: Ride detail
    page.goto(f'{base}/clubs/{slug}/rides/{ride_id}')
    page.wait_for_selector('h1, .ride-title, .signup-card')
    _shot(page, '24_public_ride_detail')

    page.close()
    context.close()


