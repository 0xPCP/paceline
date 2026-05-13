"""
Browser workflow tests: Club Creator â†’ Setup â†’ Ride Management â†’ Team Management

Runs a real Flask dev server in a background thread and drives it with Playwright
headless Chromium, taking a screenshot at every key step of the club creation and
administration workflow.

Screenshots are written to tests/screenshots/wf_club_creator_*.png

Scenarios
---------
A  Club creation wizard
   register â†’ wizard step 1 (basics) â†’ step 2 (privacy) â†’
   step 3 (theme) â†’ step 4 (details) â†’ step 5 (review + submit) â†’ club home

B  Admin tooling â€” ride creation and team management
   admin dashboard â†’ create road/gravel ride â†’ team page â†’ add ride manager â†’
   add full admin â†’ remove full admin

C  Membership approval workflow
   two users join (pending) â†’ admin views pending list â†’ approve one â†’ reject other

Run with:
    pip install pytest-playwright && playwright install chromium
    pytest tests/test_browser_workflow_club_creator.py -v -s
"""
import os
import threading
import time as _time
import pytest
from datetime import date, time as dtime, timedelta

from app import create_app
from app.extensions import db as _db
from app.models import Club, Ride, ClubWaiver, User, ClubAdmin, ClubMembership

SCREENSHOTS_DIR = os.path.join(os.path.dirname(__file__), 'screenshots')
SERVER_PORT = 5202
TEST_DB_PATH = os.path.join(os.path.dirname(__file__), '_wf_club_creator.db')

os.makedirs(SCREENSHOTS_DIR, exist_ok=True)


class WFCreatorTestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = f'sqlite:///{TEST_DB_PATH}'
    WTF_CSRF_ENABLED = False
    SECRET_KEY = 'wf-creator-secret'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    STRAVA_CLIENT_ID = None
    STRAVA_CLIENT_SECRET = None
    STRAVA_CLUB_ID = None
    STRAVA_CLUB_REFRESH_TOKEN = None


# â”€â”€ Module-level server fixture â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@pytest.fixture(scope='module')
def server_info():
    """
    Start a Flask dev server with seed users for team management and membership tests.
    The primary founder account registers via the browser; supporting accounts are
    pre-seeded so they can be added by email.
    """
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)

    app = create_app(WFCreatorTestConfig)
    from app.extensions import bcrypt

    with app.app_context():
        _db.create_all()

        # Pre-seed support users for team/member scenarios
        support_users = [
            ('ridemgr',   'ridemgr@wf.example.com',    'TestPass1!'),
            ('fulladmin2', 'fulladmin2@wf.example.com',  'TestPass1!'),
            ('joiner_a',  'joiner_a@wf.example.com',    'TestPass1!'),
            ('joiner_b',  'joiner_b@wf.example.com',    'TestPass1!'),
        ]
        seeded = {}
        for username, email, pw in support_users:
            u = User(
                username=username, email=email,
                password_hash=bcrypt.generate_password_hash(pw).decode(),
            )
            _db.session.add(u)
            _db.session.flush()
            seeded[username] = u.id

        _db.session.commit()

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
    yield {'base': base, 'seeded': seeded}

    try:
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)
    except OSError:
        pass


# â”€â”€ Auth helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _register_user(page, base, username, email, password='TestPass1!'):
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
    page.goto(f'{base}/')
    page.request.post(f'{base}/auth/logout')
    page.wait_for_load_state('networkidle')


def _login_user(page, base, email, password='TestPass1!'):
    _logout_user(page, base)
    page.goto(f'{base}/auth/login')
    page.wait_for_selector('input[name="email"]')
    page.fill('input[name="email"]', email)
    page.fill('input[name="password"]', password)
    page.click('button[type="submit"], input[type="submit"]')
    page.wait_for_load_state('networkidle')


def _shot(page, name):
    path = os.path.join(SCREENSHOTS_DIR, f'wf_club_creator_{name}.png')
    page.screenshot(path=path, full_page=True)


# â”€â”€ Scenario A: Club creation wizard â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def test_scenario_a_club_creation_wizard(server_info, browser):
    """
    Complete club creation wizard: 5 steps â†’ submit â†’ club home.

    Screenshots:
      01_register             â€” registration form for the founder
      02_wizard_start         â€” /clubs/create page (step 1 active)
      03_wizard_step1_filled  â€” step 1 with name/location filled in
      04_wizard_step2         â€” privacy step
      05_wizard_step3         â€” theme picker step
      06_wizard_step4         â€” details step
      07_wizard_step5_review  â€” review step before submit
      08_club_home            â€” newly created club's home page
      09_admin_dashboard      â€” /admin/clubs/<slug>/ after creation
      10_club_settings        â€” /admin/clubs/<slug>/settings page
    """
    base = server_info['base']
    context = browser.new_context()
    page = context.new_page()

    # Register founder then log in (register does not auto-login)
    _register_user(page, base, 'clubfounder', 'founder@wf.example.com')
    _login_user(page, base, 'founder@wf.example.com')
    _shot(page, '01_after_register')

    # Navigate to club creation wizard
    page.goto(f'{base}/clubs/create')
    page.wait_for_selector('#step-1, .wz-panel.active, h1')
    _shot(page, '02_wizard_start')

    # â”€â”€ Step 1: Basics â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    page.fill('input[name="name"]', 'Blue Ridge Cyclists')
    page.fill('input[name="city"]', 'Reston')
    page.fill('input[name="state"]', 'VA')
    page.fill('input[name="zip_code"]', '20191')
    _shot(page, '03_wizard_step1_filled')

    # Click "Next: Privacy"
    page.locator('#step-1 button.btn-paceline').click()
    page.wait_for_timeout(400)
    _shot(page, '04_wizard_step2')

    # â”€â”€ Step 2: Privacy â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Click the "Public" privacy card (first card)
    public_card = page.locator('#step-2 .privacy-card').first
    if public_card.count() > 0:
        public_card.click()
        page.wait_for_timeout(200)

    page.locator('#step-2 button.btn-paceline').click()
    page.wait_for_timeout(400)
    _shot(page, '05_wizard_step3')

    # â”€â”€ Step 3: Theme â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Click the first theme card (Forest)
    theme_card = page.locator('#step-3 .theme-card').first
    if theme_card.count() > 0:
        theme_card.click()
        page.wait_for_timeout(200)

    page.locator('#step-3 button.btn-paceline').click()
    page.wait_for_timeout(400)
    _shot(page, '06_wizard_step4')

    # â”€â”€ Step 4: Details â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    desc_field = page.locator('textarea[name="description"], input[name="description"]')
    if desc_field.count() > 0:
        desc_field.fill('A friendly club for road and gravel cyclists in the Reston area.')
    contact_field = page.locator('input[name="contact_email"]')
    if contact_field.count() > 0:
        contact_field.fill('rides@blueridgecyclists.com')

    page.locator('#step-4 button.btn-paceline').click()
    page.wait_for_timeout(400)
    _shot(page, '07_wizard_step5_review')

    # â”€â”€ Step 5: Review + Submit â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Take a screenshot of the review step, then submit
    submit_btn = page.locator(
        'button[type="submit"]:has-text("Create"), '
        'button[type="submit"]:has-text("Launch"), '
        'button[type="submit"]'
    ).first
    submit_btn.click()
    page.wait_for_load_state('networkidle')
    _shot(page, '08_club_home_after_creation')

    # Capture the slug from the current URL
    current_url = page.url
    slug = current_url.rstrip('/').split('/')[-1] if '/clubs/' in current_url else 'blue-ridge-cyclists'

    # Navigate to admin dashboard
    page.goto(f'{base}/admin/clubs/{slug}/')
    page.wait_for_selector('h1, .card')
    _shot(page, '09_admin_dashboard')

    # Club settings page
    page.goto(f'{base}/admin/clubs/{slug}/settings')
    page.wait_for_selector('h1, form')
    _shot(page, '10_club_settings')

    page.close()
    context.close()


# â”€â”€ Scenario B: Admin tooling â€” rides + team management â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def test_scenario_b_admin_rides_and_team_management(server_info, browser):
    """
    Logged in as the previously created founder, create rides and manage the team.

    Screenshots:
      20_ride_new_form        â€” /admin/clubs/<slug>/rides/new form
      21_ride_new_filled      â€” form filled with road ride details
      22_after_ride_created   â€” back on admin dashboard or ride list
      23_ride_new_gravel      â€” gravel ride creation form filled
      24_team_page            â€” /admin/clubs/<slug>/team
      25_team_add_ridemgr     â€” after adding ride manager
      26_team_add_admin       â€” after adding full admin
      27_ridemgr_can_create   â€” ride manager successfully creates a ride
      28_ridemgr_settings_403 â€” ride manager denied settings page
    """
    base = server_info['base']
    context = browser.new_context()
    page = context.new_page()

    # Log in as founder (registered in scenario A)
    _login_user(page, base, 'founder@wf.example.com')

    # Determine club slug â€” navigate to /clubs/ and find the link
    page.goto(f'{base}/clubs/')
    page.wait_for_selector('.club-card, .card, h1')
    club_link = page.locator('a[href*="/clubs/blue-ridge"]').first
    if club_link.count() > 0:
        slug = 'blue-ridge-cyclists'
    else:
        # Fallback: try to find any club we're admin of
        page.goto(f'{base}/admin/')
        page.wait_for_load_state('networkidle')
        slug = 'blue-ridge-cyclists'

    # â”€â”€ Ride creation: road ride â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    page.goto(f'{base}/admin/clubs/{slug}/rides/new')
    page.wait_for_selector('input[name="title"], h1')
    _shot(page, '20_ride_new_form')

    ride_date = (date.today() + timedelta(days=8)).strftime('%Y-%m-%d')
    page.fill('input[name="title"]', 'Saturday Road Ride â€” A Group')
    page.fill('input[name="date"]', ride_date)
    page.fill('input[name="time"]', '08:00')
    page.fill('input[name="meeting_location"]', 'Hunterwoods Shopping Center')
    page.fill('input[name="distance_miles"]', '42')
    page.fill('input[name="elevation_feet"]', '2400')

    # Pace select
    pace_select = page.locator('select[name="pace_category"]')
    if pace_select.count() > 0:
        pace_select.select_option('A')

    # Ride type select
    type_select = page.locator('select[name="ride_type"]')
    if type_select.count() > 0:
        type_select.select_option('road')

    _shot(page, '21_ride_new_filled')
    page.click('button[type="submit"], input[type="submit"]')
    page.wait_for_load_state('networkidle')
    _shot(page, '22_after_ride_created')

    # â”€â”€ Ride creation: gravel ride â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    page.goto(f'{base}/admin/clubs/{slug}/rides/new')
    page.wait_for_selector('input[name="title"]')

    gravel_date = (date.today() + timedelta(days=9)).strftime('%Y-%m-%d')
    page.fill('input[name="title"]', 'Sunday Gravel Adventure')
    page.fill('input[name="date"]', gravel_date)
    page.fill('input[name="time"]', '08:30')
    page.fill('input[name="meeting_location"]', 'Fountainhead Regional Park')
    page.fill('input[name="distance_miles"]', '35')
    page.fill('input[name="elevation_feet"]', '3200')

    pace_select = page.locator('select[name="pace_category"]')
    if pace_select.count() > 0:
        pace_select.select_option('B')
    type_select = page.locator('select[name="ride_type"]')
    if type_select.count() > 0:
        type_select.select_option('gravel')

    _shot(page, '23_ride_new_gravel_filled')
    page.click('button[type="submit"], input[type="submit"]')
    page.wait_for_load_state('networkidle')

    # â”€â”€ Team management page â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    page.goto(f'{base}/admin/clubs/{slug}/team')
    page.wait_for_selector('h1, .card')
    _shot(page, '24_team_page')

    # Add ride manager
    identifier_input = page.locator('input[name="identifier"]').first
    role_select = page.locator('select[name="role"]').first
    if identifier_input.count() > 0 and role_select.count() > 0:
        identifier_input.fill('ridemgr@wf.example.com')
        role_select.select_option('ride_manager')
        page.locator('form:has(input[name="identifier"]) button[type="submit"]').first.click()
        page.wait_for_load_state('networkidle')
        _shot(page, '25_team_add_ridemgr')

    # Add full admin
    page.goto(f'{base}/admin/clubs/{slug}/team')
    page.wait_for_selector('input[name="identifier"]')
    identifier_input = page.locator('input[name="identifier"]').first
    role_select = page.locator('select[name="role"]').first
    if identifier_input.count() > 0:
        identifier_input.fill('fulladmin2@wf.example.com')
        role_select.select_option('admin')
        page.locator('form:has(input[name="identifier"]) button[type="submit"]').first.click()
        page.wait_for_load_state('networkidle')
        _shot(page, '26_team_add_full_admin')

    # â”€â”€ Ride manager creates a ride â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    _login_user(page, base, 'ridemgr@wf.example.com')
    page.goto(f'{base}/admin/clubs/{slug}/rides/new')
    page.wait_for_selector('input[name="title"]')

    rm_date = (date.today() + timedelta(days=3)).strftime('%Y-%m-%d')
    page.fill('input[name="title"]', 'Ride Manager Tuesday Special')
    page.fill('input[name="date"]', rm_date)
    page.fill('input[name="time"]', '18:00')
    page.fill('input[name="meeting_location"]', 'The Bike Lane')
    page.fill('input[name="distance_miles"]', '22')

    pace_select = page.locator('select[name="pace_category"]')
    if pace_select.count() > 0:
        pace_select.select_option('C')

    page.click('button[type="submit"], input[type="submit"]')
    page.wait_for_load_state('networkidle')
    _shot(page, '27_ridemgr_created_ride')

    # Ride manager blocked from settings
    page.goto(f'{base}/admin/clubs/{slug}/settings')
    page.wait_for_load_state('networkidle')
    _shot(page, '28_ridemgr_settings_blocked')

    page.close()
    context.close()


# â”€â”€ Scenario C: Membership approval workflow â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def test_scenario_c_membership_approval_workflow(server_info, browser):
    """
    Two users join a manual-approval club; admin approves one and rejects other.

    Screenshots:
      30_joiner_a_join       â€” club home for joiner A (join button visible)
      31_joiner_a_pending    â€” club home after joining (pending state)
      32_joiner_b_pending    â€” club home for joiner B after joining
      33_admin_pending_list  â€” admin team page showing both pending requests
      34_after_approve       â€” team page after approving joiner A
      35_after_reject        â€” team page after rejecting joiner B
      36_approved_member     â€” joiner A views club home as approved member
      37_approved_ride_list  â€” joiner A views ride list as member
    """
    base = server_info['base']
    context = browser.new_context()
    page = context.new_page()

    # Set up a manual-approval club via the founder account
    _login_user(page, base, 'founder@wf.example.com')

    # Create a new manual-approval club via the wizard
    page.goto(f'{base}/clubs/create')
    page.wait_for_selector('input[name="name"]')
    page.fill('input[name="name"]', 'Stricty CC')
    page.fill('input[name="city"]', 'McLean')
    page.fill('input[name="state"]', 'VA')
    page.fill('input[name="zip_code"]', '22101')

    # Navigate to privacy step and select "Members Only"
    page.locator('#step-1 button.btn-paceline').click()
    page.wait_for_timeout(400)

    # Click the private/members-only card if it exists
    private_card = page.locator('#step-2 .privacy-card').nth(1)  # second card = members only
    if private_card.count() > 0:
        private_card.click()
        page.wait_for_timeout(200)

    # Navigate through remaining steps using step-specific selectors
    for step_id in ['#step-2', '#step-3', '#step-4']:
        btn = page.locator(f'{step_id} button.btn-paceline')
        if btn.count() > 0:
            btn.click()
            page.wait_for_timeout(400)

    page.locator('#step-5 button[type="submit"]').click()
    page.wait_for_load_state('networkidle')

    # Determine the new club's slug from the URL
    current_url = page.url
    parts = current_url.rstrip('/').split('/')
    strict_slug = parts[-1] if len(parts) >= 2 and 'clubs' in parts else 'stricty-cc'

    # Force join_approval=manual via settings (wizard defaults may vary)
    page.goto(f'{base}/admin/clubs/{strict_slug}/settings')
    page.wait_for_selector('select[name="join_approval"], input[name="name"]')
    join_select = page.locator('select[name="join_approval"]')
    if join_select.count() > 0:
        join_select.select_option('manual')
    req_mem = page.locator('input[name="require_membership"]')
    if req_mem.count() > 0:
        req_mem.check()
    page.click('button[type="submit"], input[type="submit"]')
    page.wait_for_load_state('networkidle')

    # â”€â”€ Joiner A joins â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    _login_user(page, base, 'joiner_a@wf.example.com')
    page.goto(f'{base}/clubs/{strict_slug}/')
    page.wait_for_selector('h1')
    _shot(page, '30_joiner_a_club_home')

    join_btn = page.locator('form[action*="/join"] button').first
    if join_btn.count() > 0:
        join_btn.click()
        page.wait_for_load_state('networkidle')
    _shot(page, '31_joiner_a_pending')

    # â”€â”€ Joiner B joins â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    _login_user(page, base, 'joiner_b@wf.example.com')
    page.goto(f'{base}/clubs/{strict_slug}/')
    page.wait_for_selector('h1')
    join_btn = page.locator('form[action*="/join"] button').first
    if join_btn.count() > 0:
        join_btn.click()
        page.wait_for_load_state('networkidle')
    _shot(page, '32_joiner_b_pending')

    # â”€â”€ Admin views pending list â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    _login_user(page, base, 'founder@wf.example.com')
    page.goto(f'{base}/admin/clubs/{strict_slug}/team')
    page.wait_for_selector('h1, .card')
    _shot(page, '33_admin_pending_list')

    # Approve joiner A (first approve button)
    approve_btns = page.locator(
        'form[action*="/approve"] button, '
        'button:has-text("Approve")'
    )
    if approve_btns.count() > 0:
        approve_btns.first.click()
        page.wait_for_load_state('networkidle')
        _shot(page, '34_after_approve_joiner_a')

    # Reject joiner B (first reject button remaining)
    reject_btns = page.locator(
        'form[action*="/reject"] button, '
        'button:has-text("Reject"), button:has-text("Deny")'
    )
    if reject_btns.count() > 0:
        reject_btns.first.click()
        page.wait_for_load_state('networkidle')
        _shot(page, '35_after_reject_joiner_b')

    # â”€â”€ Approved member views club â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    _login_user(page, base, 'joiner_a@wf.example.com')
    page.goto(f'{base}/clubs/{strict_slug}/')
    page.wait_for_load_state('networkidle')
    _shot(page, '36_approved_member_club_home')

    page.goto(f'{base}/clubs/{strict_slug}/rides/')
    page.wait_for_load_state('networkidle')
    _shot(page, '37_approved_member_ride_list')

    page.close()
    context.close()





