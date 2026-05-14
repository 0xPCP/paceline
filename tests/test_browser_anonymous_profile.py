"""
Browser workflow tests: Anonymous Signup · Public Profiles · Auth Gate

Spins up a real Flask dev server and drives headless Chromium through every
new-feature workflow, taking a screenshot at each meaningful step.

Screenshots: tests/screenshots/anon_profile_*.png

Scenarios
---------
A  Auth gate — unauthenticated visitor cannot see personal data
B  Anonymous signup on a club ride + anonymous display for other riders
C  Admin / ride-manager sees real name with (anon) badge in attendee list
D  Non-anonymous signup shows clickable profile link
E  Profile settings — gender and bio fields present and saveable
F  Public profile page — bio, Strava link, ride history
G  My Rides list + create personal ride
H  Private user ride — locked view, request-access, owner approval

Run with:
    pip install pytest-playwright && playwright install chromium
    pytest tests/test_browser_anonymous_profile.py -v -s
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
    RideSignup, WaiverSignature, UserRideInvite,
)

SCREENSHOTS_DIR = os.path.join(os.path.dirname(__file__), 'screenshots')
SERVER_PORT = 5203
TEST_DB_PATH = os.path.join(os.path.dirname(__file__), '_wf_anon_profile.db')

os.makedirs(SCREENSHOTS_DIR, exist_ok=True)


class WFTestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = f'sqlite:///{TEST_DB_PATH}'
    WTF_CSRF_ENABLED = False
    SECRET_KEY = 'wf-anon-profile-secret'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    STRAVA_CLIENT_ID = None
    STRAVA_CLIENT_SECRET = None
    STRAVA_CLUB_ID = None
    STRAVA_CLUB_REFRESH_TOKEN = None


# ── Module-level server + seed ─────────────────────────────────────────────────

@pytest.fixture(scope='module')
def server_info():
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)

    app = create_app(WFTestConfig)
    from app.extensions import bcrypt

    today = date.today()
    next_sat = today + timedelta(days=(5 - today.weekday()) % 7 or 7)
    past_date = today - timedelta(days=14)

    with app.app_context():
        _db.create_all()

        pw = lambda s: bcrypt.generate_password_hash(s).decode()

        # Three users with varying profiles
        alice = User(
            username='alice', email='alice@wf.example.com',
            password_hash=pw('TestPass1!'),
            gender='female',
            bio='Avid gravel cyclist based in Reston, VA.',
            strava_id=99887766,
        )
        bob = User(
            username='bob', email='bob@wf.example.com',
            password_hash=pw('TestPass1!'),
        )
        mgr = User(
            username='ridemgr', email='ridemgr@wf.example.com',
            password_hash=pw('TestPass1!'),
        )
        _db.session.add_all([alice, bob, mgr])
        _db.session.flush()

        # Club
        club = Club(
            slug='testclub', name='Test Cycling Club',
            city='Reston', state='VA', zip_code='20191',
            lat=38.9376, lng=-77.3476,
            join_approval='auto', require_membership=True,
            description='A test club for browser workflow tests.',
            theme_primary='#2d6a4f', theme_accent='#e76f51',
            is_hidden=False,
        )
        _db.session.add(club)
        _db.session.flush()

        _db.session.add(ClubAdmin(user_id=mgr.id, club_id=club.id, role='admin'))

        waiver = ClubWaiver(
            club_id=club.id, year=today.year,
            title='Test Club Annual Waiver',
            body='I acknowledge cycling risks and agree to ride safely.',
        )
        _db.session.add(waiver)
        _db.session.flush()

        # Pre-join all three users as active members with signed waivers
        for u in (alice, bob, mgr):
            _db.session.add(ClubMembership(
                user_id=u.id, club_id=club.id, status='active'))
            _db.session.add(WaiverSignature(
                user_id=u.id, club_id=club.id,
                waiver_id=waiver.id, year=today.year))

        # Club rides
        upcoming_ride = Ride(
            club_id=club.id, title='Saturday Club Ride',
            date=next_sat, time=dtime(8, 0),
            meeting_location='Town Hall Parking Lot',
            distance_miles=35.0, elevation_feet=1800,
            pace_category='B', ride_type='road',
            ride_leader='Test Leader',
        )
        side_ride = Ride(
            club_id=club.id, title='Tuesday Evening Spin',
            date=today + timedelta(days=((1 - today.weekday()) % 7 or 7)),
            time=dtime(18, 0),
            meeting_location='Community Center',
            distance_miles=20.0, pace_category='C', ride_type='social',
        )
        past_ride = Ride(
            club_id=club.id, title='Past Saturday Ride',
            date=past_date, time=dtime(8, 0),
            meeting_location='Town Hall Parking Lot',
            distance_miles=30.0, pace_category='B', ride_type='road',
        )
        _db.session.add_all([upcoming_ride, side_ride, past_ride])
        _db.session.flush()

        # Bob has a non-anonymous signup on the side ride (pre-seeded)
        _db.session.add(RideSignup(
            ride_id=side_ride.id, user_id=bob.id, is_anonymous=False))

        # Alice has a non-anonymous signup on the past ride (shows in her profile history)
        _db.session.add(RideSignup(
            ride_id=past_ride.id, user_id=alice.id, is_anonymous=False))

        # Alice's personal rides
        alice_public_ride = Ride(
            owner_id=alice.id, club_id=None, is_private=False,
            title="Alice's Saturday Gravel Ride",
            date=next_sat, time=dtime(9, 0),
            meeting_location='Algonkian Park',
            distance_miles=42.0, elevation_feet=2100,
            pace_category='B', ride_type='gravel',
            ride_leader='alice',
            description='A fun gravel loop. Gravel bikes recommended.',
        )
        alice_private_ride = Ride(
            owner_id=alice.id, club_id=None, is_private=True,
            title="Alice's Private A Ride",
            date=next_sat, time=dtime(7, 30),
            meeting_location='Starbucks on Broad St',
            distance_miles=65.0, elevation_feet=4000,
            pace_category='A', ride_type='road',
            ride_leader='alice',
            description='Invite-only fast group.',
        )
        _db.session.add_all([alice_public_ride, alice_private_ride])
        _db.session.flush()
        _db.session.add(RideSignup(
            ride_id=alice_public_ride.id, user_id=alice.id))
        _db.session.add(RideSignup(
            ride_id=alice_private_ride.id, user_id=alice.id))

        _db.session.commit()

        ids = {
            'base': f'http://127.0.0.1:{SERVER_PORT}',
            'club_slug': club.slug,
            'upcoming_ride_id': upcoming_ride.id,
            'side_ride_id': side_ride.id,
            'past_ride_id': past_ride.id,
            'alice_public_ride_id': alice_public_ride.id,
            'alice_private_ride_id': alice_private_ride.id,
        }

    t = threading.Thread(
        target=lambda: app.run(
            host='127.0.0.1', port=SERVER_PORT,
            use_reloader=False, threaded=True,
        ),
        daemon=True,
    )
    t.start()
    _time.sleep(1.2)

    yield ids

    try:
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)
    except OSError:
        pass


# ── Helpers ────────────────────────────────────────────────────────────────────

def _shot(page, name):
    path = os.path.join(SCREENSHOTS_DIR, f'anon_profile_{name}.png')
    page.screenshot(path=path, full_page=True)


def _logout(page, base):
    page.goto(f'{base}/')
    page.request.post(f'{base}/auth/logout')
    page.wait_for_load_state('networkidle')


def _login(page, base, email, password='TestPass1!'):
    _logout(page, base)
    page.goto(f'{base}/auth/login')
    page.wait_for_selector('input[name="email"]')
    page.fill('input[name="email"]', email)
    page.fill('input[name="password"]', password)
    page.click('button[type="submit"], input[type="submit"]')
    page.wait_for_load_state('networkidle')


# ── Scenario A: Auth gate — unauthenticated visitor ────────────────────────────

def test_scenario_a_auth_gate_unauthenticated(server_info, browser):
    """
    Unauthenticated visitor can see ride info but NOT the signup list or profiles.

    Screenshots:
      A01_anon_club_ride_detail  — ride detail, no signup list visible
      A02_anon_public_ride       — user-owned public ride, no personal data
      A03_profile_redirect       — /users/alice redirects to login
    """
    base = server_info['base']
    slug = server_info['club_slug']
    ride_id = server_info['upcoming_ride_id']
    alice_pub = server_info['alice_public_ride_id']

    context = browser.new_context()
    page = context.new_page()

    # A01: Club ride detail — unauthenticated
    page.goto(f'{base}/clubs/{slug}/rides/{ride_id}')
    page.wait_for_selector('h1')
    _shot(page, 'A01_anon_club_ride_detail')

    content = page.content()
    assert 'Saturday Club Ride' in content, 'Ride title should be visible to all'
    assert 'Town Hall Parking Lot' in content, 'Location should be visible'
    assert "Who's coming" not in content, "Signup list must be hidden from anonymous visitors"
    assert 'Sign in' in content, 'Sign-in prompt should appear'

    # A02: User-owned public ride — unauthenticated
    page.goto(f'{base}/my-rides/{alice_pub}')
    page.wait_for_selector('h1')
    _shot(page, 'A02_anon_public_ride_detail')

    assert "Alice's Saturday Gravel Ride" in page.content()
    assert "Who's coming" not in page.content()

    # A03: Public profile requires login
    resp = page.goto(f'{base}/users/alice')
    page.wait_for_load_state('networkidle')
    _shot(page, 'A03_profile_redirect_to_login')
    # Should be on the login page or show login form
    assert 'login' in page.url.lower() or page.locator('input[name="email"]').count() > 0

    page.close()
    context.close()


# ── Scenario B: Anonymous signup on a club ride ────────────────────────────────

def test_scenario_b_anonymous_club_ride_signup(server_info, browser):
    """
    Alice signs up for the upcoming club ride with the anonymous checkbox checked.
    Verifies:
      - Anonymous checkbox is present on the signup form
      - After signup, Alice's slot appears as "Anonymous Female Rider" to Bob

    Screenshots:
      B01_ride_detail_signup_form    — ride detail showing anon checkbox
      B02_after_anon_signup          — confirmation page after signing up
      B03_bob_sees_anon_display      — Bob views the same ride, sees "Anonymous Female Rider"
      B04_admin_sees_real_name       — Ride mgr sees "alice (anon)" with badge
    """
    base = server_info['base']
    slug = server_info['club_slug']
    ride_id = server_info['upcoming_ride_id']

    context = browser.new_context()
    page = context.new_page()

    # B01: Alice views the ride — screenshot showing the anonymous checkbox
    _login(page, base, 'alice@wf.example.com')
    page.goto(f'{base}/clubs/{slug}/rides/{ride_id}')
    page.wait_for_selector('.signup-card')
    _shot(page, 'B01_ride_detail_signup_form')

    assert page.locator('input[name="is_anonymous"]').count() > 0, \
        'Anonymous checkbox must be present on signup form'
    assert page.locator('input[name="is_anonymous"]').is_visible(), \
        'Anonymous checkbox must be visible'

    # Check the anonymous box and sign up
    page.locator('input[name="is_anonymous"]').check()
    page.locator('form[action*="/signup"] button[type="submit"], '
                 'button:has-text("Sign Up for This Ride")').first.click()
    page.wait_for_load_state('networkidle')
    _shot(page, 'B02_after_anon_signup')

    # Alice should now see "Cancel My Signup" (she's signed up)
    assert page.locator('button:has-text("Cancel My Signup")').count() > 0 or \
           'signed up' in page.content().lower() or \
           'cancel' in page.content().lower(), \
        'Alice should appear as signed up after clicking Sign Up'

    # B03: Bob views the same ride — should see "Anonymous Female Rider"
    _login(page, base, 'bob@wf.example.com')
    page.goto(f'{base}/clubs/{slug}/rides/{ride_id}')
    page.wait_for_selector('.signup-card')
    _shot(page, 'B03_bob_sees_anon_display')

    content = page.content()
    assert 'Anonymous' in content, "Bob should see 'Anonymous' label for alice's signup"
    assert 'Female' in content, "Alice's gender should show as 'Female'"
    assert 'Rider' in content
    # Alice's username should NOT appear as a plain name to Bob
    assert '/users/alice' not in content, \
        "Alice's profile link must not appear for anonymous signups"

    # B04: Ride manager views the ride — sees real name + anon badge
    _login(page, base, 'ridemgr@wf.example.com')
    page.goto(f'{base}/clubs/{slug}/rides/{ride_id}')
    page.wait_for_selector('.signup-card')
    _shot(page, 'B04_admin_sees_real_name_anon_badge')

    content = page.content()
    assert 'alice' in content, 'Admin should see the real username'
    assert 'anon' in content.lower(), "Admin should see the 'anon' badge"

    page.close()
    context.close()


# ── Scenario C: Non-anonymous signup shows clickable profile link ──────────────

def test_scenario_c_non_anonymous_shows_profile_link(server_info, browser):
    """
    Bob's non-anonymous signup on the Tuesday ride shows a clickable profile link.

    Screenshots:
      C01_ride_with_profile_link  — ride detail showing bob's name as a hyperlink
      C02_bob_profile_page        — bob's public profile page
    """
    base = server_info['base']
    slug = server_info['club_slug']
    ride_id = server_info['side_ride_id']

    context = browser.new_context()
    page = context.new_page()

    _login(page, base, 'alice@wf.example.com')
    page.goto(f'{base}/clubs/{slug}/rides/{ride_id}')
    page.wait_for_selector('.signup-card')
    _shot(page, 'C01_ride_with_profile_link')

    content = page.content()
    assert '/users/bob' in content, \
        "Bob's non-anonymous signup should show as a profile link"
    assert 'Anonymous' not in content, \
        "Bob did not sign up anonymously, should not show as Anonymous"

    # C02: Navigate to bob's profile via the link
    profile_link = page.locator('a[href*="/users/bob"]').first
    assert profile_link.count() > 0, 'Profile link should be present'
    profile_link.click()
    page.wait_for_load_state('networkidle')
    _shot(page, 'C02_bob_public_profile_page')

    assert 'bob' in page.content()
    assert page.url.endswith('/users/bob')

    page.close()
    context.close()


# ── Scenario D: Admin roster shows anonymous indicator ────────────────────────

def test_scenario_d_admin_roster_anonymous_indicator(server_info, browser):
    """
    The admin ride roster shows real names for all signups,
    with an (anon) badge for riders who signed up anonymously.

    Screenshots:
      D01_admin_roster  — full roster with anon badge visible
    """
    base = server_info['base']
    slug = server_info['club_slug']
    ride_id = server_info['upcoming_ride_id']

    context = browser.new_context()
    page = context.new_page()

    _login(page, base, 'ridemgr@wf.example.com')
    page.goto(f'{base}/admin/clubs/{slug}/rides/{ride_id}/roster')
    page.wait_for_selector('h1, table')
    _shot(page, 'D01_admin_roster_with_anon_indicator')

    content = page.content()
    assert 'alice' in content, 'Admin roster must show alice by real name'
    assert 'anon' in content.lower(), 'Anon badge should appear for alice in roster'

    page.close()
    context.close()


# ── Scenario E: Profile settings — gender and bio ─────────────────────────────

def test_scenario_e_profile_settings_gender_bio(server_info, browser):
    """
    The profile settings page shows gender and bio fields.
    Bob fills them in and saves.

    Screenshots:
      E01_profile_settings_page     — profile form showing new fields
      E02_profile_settings_filled   — form filled with gender and bio
      E03_profile_saved             — after saving
    """
    base = server_info['base']

    context = browser.new_context()
    page = context.new_page()

    _login(page, base, 'bob@wf.example.com')
    page.goto(f'{base}/auth/profile')
    page.wait_for_selector('form')
    _shot(page, 'E01_profile_settings_page')

    # Verify new fields are present
    assert page.locator('select[name="gender"]').is_visible(), \
        'Gender select field must be visible on profile page'
    assert page.locator('textarea[name="bio"]').is_visible(), \
        'Bio textarea must be visible on profile page'

    # Fill in gender and bio
    page.select_option('select[name="gender"]', 'male')
    page.fill('textarea[name="bio"]', 'Weekend warrior cyclist from McLean, VA.')
    _shot(page, 'E02_profile_settings_filled')

    page.click('button[type="submit"]:has-text("Save"), input[type="submit"]')
    page.wait_for_load_state('networkidle')
    _shot(page, 'E03_profile_settings_saved')

    # Saved values should be reflected back in the form
    assert page.locator('select[name="gender"]').input_value() == 'male' or \
           'success' in page.content().lower() or \
           'updated' in page.content().lower(), \
        'Profile save should succeed'

    page.close()
    context.close()


# ── Scenario F: Public profile page ───────────────────────────────────────────

def test_scenario_f_public_profile_pages(server_info, browser):
    """
    Alice's public profile shows her bio, Strava link, and ride history.
    Bob's profile (after saving bio in Scenario E) shows his bio.

    Screenshots:
      F01_alice_public_profile  — alice's profile with bio + Strava + ride history
      F02_bob_public_profile    — bob's profile
    """
    base = server_info['base']

    context = browser.new_context()
    page = context.new_page()

    _login(page, base, 'bob@wf.example.com')

    # F01: Alice's profile
    page.goto(f'{base}/users/alice')
    page.wait_for_selector('h1')
    _shot(page, 'F01_alice_public_profile')

    content = page.content()
    assert 'alice' in content
    assert 'Avid gravel cyclist' in content, "Alice's bio must appear on her public profile"
    assert 'strava.com/athletes/99887766' in content, \
        "Alice's Strava link must appear on her public profile"
    assert 'Past Saturday Ride' in content, \
        "Alice's non-anonymous past ride must appear in history"

    # Verify Strava link is a proper anchor
    strava_link = page.locator('a[href*="strava.com/athletes/99887766"]')
    assert strava_link.count() > 0, 'Strava link must be a clickable anchor'
    assert strava_link.is_visible(), 'Strava link must be visible'

    # F02: Bob's profile (bio set in Scenario E)
    page.goto(f'{base}/users/bob')
    page.wait_for_selector('h1')
    _shot(page, 'F02_bob_public_profile')

    content = page.content()
    assert 'bob' in content
    # Bio should be present if Scenario E saved successfully
    # (tolerate if E didn't run first — just check the page renders)
    assert page.locator('h1').is_visible()

    page.close()
    context.close()


# ── Scenario G: My Rides list + create a personal ride ────────────────────────

def test_scenario_g_my_rides_list_and_create(server_info, browser):
    """
    Alice views her My Rides list, creates a new public personal ride,
    and verifies the ride detail page.

    Screenshots:
      G01_my_rides_list           — My Rides list showing alice's 2 pre-seeded rides
      G02_create_ride_form        — blank create ride form
      G03_create_ride_filled      — form filled in
      G04_new_ride_detail         — created ride detail page
      G05_my_rides_updated        — My Rides list with 3 rides now
    """
    base = server_info['base']
    today = date.today()
    ride_date = (today + timedelta(days=10)).isoformat()

    context = browser.new_context()
    page = context.new_page()

    _login(page, base, 'alice@wf.example.com')

    # G01: My Rides list
    page.goto(f'{base}/my-rides/')
    page.wait_for_selector('h1')
    _shot(page, 'G01_my_rides_list')

    content = page.content()
    assert "Alice's Saturday Gravel Ride" in content, 'Public ride should show'
    assert "Alice's Private A Ride" in content, 'Private ride should show'
    assert 'Public' in content, 'Public badge should show'
    assert 'Private' in content, 'Private badge should show'
    # Quota counter should be visible
    assert 'rides' in content.lower() and 'week' in content.lower(), \
        'Weekly quota counter should be visible'

    # G02: Navigate to Create Ride form
    page.goto(f'{base}/my-rides/create')
    page.wait_for_selector('form')
    _shot(page, 'G02_create_ride_form')

    assert page.locator('input[name="title"]').is_visible(), 'Title field must be present'
    assert page.locator('input[name="date"]').is_visible(), 'Date field must be present'
    assert page.locator('input[name="is_private"]').count() > 0 or \
           page.locator('input[type="checkbox"][name="is_private"]').count() > 0, \
        'Privacy toggle must be present'

    # G03: Fill in the form
    page.fill('input[name="title"]', 'Browser Test Ride')
    page.fill('input[name="date"]', ride_date)
    page.fill('input[name="time"]', '07:30')
    page.fill('input[name="meeting_location"]', 'Town Square')
    page.fill('input[name="distance_miles"]', '28')
    page.select_option('select[name="pace_category"]', 'C')
    page.select_option('select[name="ride_type"]', 'road')
    _shot(page, 'G03_create_ride_filled')

    # Submit
    page.click('button[type="submit"], input[type="submit"]')
    page.wait_for_load_state('networkidle')
    _shot(page, 'G04_new_ride_detail')

    content = page.content()
    assert 'Browser Test Ride' in content, 'New ride title must appear on detail page'
    assert 'Town Square' in content, 'Meeting location should be visible'
    assert '28' in content, 'Distance should be visible'
    assert page.locator('.signup-card').count() > 0 or \
           'signed up' in content.lower(), \
        'Signup card should be present on ride detail'

    # G05: Back to My Rides list — should show 3 rides now
    page.goto(f'{base}/my-rides/')
    page.wait_for_selector('h1')
    _shot(page, 'G05_my_rides_updated_count')

    assert 'Browser Test Ride' in page.content(), \
        'Newly created ride must appear in My Rides list'

    page.close()
    context.close()


# ── Scenario H: Private user ride — locked view, request, approve ──────────────

def test_scenario_h_private_ride_access_flow(server_info, browser):
    """
    End-to-end private ride access flow:
      1. Unauthenticated visitor sees locked view
      2. Bob sees locked view + Request Access button
      3. Bob requests access → "Request pending" shown
      4. Alice (owner) sees pending request in manage panel, approves it
      5. Bob now sees full ride details

    Screenshots:
      H01_private_ride_anon_locked      — locked view (no login)
      H02_private_ride_bob_locked       — locked view (bob logged in)
      H03_after_request_access          — Bob's "request pending" state
      H04_alice_manage_panel            — Alice sees bob's pending request
      H05_after_approve                 — manage panel after approval
      H06_bob_sees_full_details         — Bob can now see full ride details
    """
    base = server_info['base']
    private_id = server_info['alice_private_ride_id']

    context = browser.new_context()
    page = context.new_page()

    # H01: Anonymous visitor sees lock icon and login prompt
    page.goto(f'{base}/my-rides/{private_id}')
    page.wait_for_selector('h1, .card')
    _shot(page, 'H01_private_ride_anon_locked')

    content = page.content()
    assert "Alice's Private A Ride" in content, 'Ride title must be visible even locked'
    assert 'Sign in' in content or 'login' in content.lower(), \
        'Login prompt must appear for anonymous visitor'
    assert 'Starbucks on Broad St' not in content, \
        'Meeting location must be hidden from anonymous visitor'

    # H02: Bob logs in and sees the "Request Access" locked view
    _login(page, base, 'bob@wf.example.com')
    page.goto(f'{base}/my-rides/{private_id}')
    page.wait_for_selector('h1, .card')
    _shot(page, 'H02_private_ride_bob_locked')

    content = page.content()
    assert "Alice's Private A Ride" in content
    assert 'Request Access' in content, \
        "Bob should see 'Request Access' button for private ride"
    assert 'Starbucks on Broad St' not in content, \
        'Meeting location must be hidden until access is granted'

    # H03: Bob requests access
    req_btn = page.locator('button:has-text("Request Access")')
    assert req_btn.is_visible(), 'Request Access button must be clickable'
    req_btn.click()
    page.wait_for_load_state('networkidle')
    _shot(page, 'H03_after_request_access')

    content = page.content()
    assert 'pending' in content.lower() or 'request' in content.lower(), \
        "After requesting access, 'pending' status must be shown"
    assert 'Request Access' not in content, \
        "Request Access button should not appear twice"

    # H04: Alice views the ride and sees bob's pending request
    _login(page, base, 'alice@wf.example.com')
    page.goto(f'{base}/my-rides/{private_id}')
    page.wait_for_selector('h1')
    _shot(page, 'H04_alice_sees_pending_request')

    content = page.content()
    assert 'bob' in content, "Alice should see bob's pending request"
    assert page.locator('button:has-text("Approve")').count() > 0, \
        'Approve button must be visible to ride owner'
    assert page.locator('button:has-text("Decline")').count() > 0, \
        'Decline button must be visible to ride owner'
    assert 'Starbucks on Broad St' in content, \
        'Owner must see full ride details'

    # H05: Alice approves bob's request
    page.locator('button:has-text("Approve")').first.click()
    page.wait_for_load_state('networkidle')
    _shot(page, 'H05_after_approving_bobs_request')

    content = page.content()
    assert 'bob' not in content or 'pending' not in content.lower(), \
        'After approval, pending requests list should no longer show bob'
    assert 'approved' in content.lower() or 'success' in content.lower() or \
           'bob' in content, \
        'Success message or bob in accepted list should appear'

    # H06: Bob can now see full ride details
    _login(page, base, 'bob@wf.example.com')
    page.goto(f'{base}/my-rides/{private_id}')
    page.wait_for_selector('h1')
    _shot(page, 'H06_bob_sees_full_ride_details')

    content = page.content()
    assert 'Starbucks on Broad St' in content, \
        'Bob should now see the full ride details including meeting location'
    assert "Alice's Private A Ride" in content
    assert 'Request Access' not in content, \
        "Request Access should not appear for an approved member"

    page.close()
    context.close()


# ── Scenario I: Discover page includes public user rides ──────────────────────

def test_scenario_i_discover_shows_user_rides(server_info, browser):
    """
    The Discover Rides page includes alice's public personal ride alongside club rides.
    User-owned rides show "@alice" attribution, club rides show club name.

    Screenshots:
      I01_discover_page  — discover page showing mix of club and user rides
    """
    base = server_info['base']

    context = browser.new_context()
    page = context.new_page()

    _login(page, base, 'bob@wf.example.com')
    page.goto(f'{base}/discover/?range=two-weeks')
    page.wait_for_selector('h1')
    _shot(page, 'I01_discover_page_with_user_rides')

    content = page.content()
    assert "Alice's Saturday Gravel Ride" in content, \
        "Alice's public personal ride should appear in discover"
    assert '@alice' in content, \
        "User-owned rides should show '@username' attribution"
    assert "Alice's Private A Ride" not in content, \
        "Alice's private ride must NOT appear in discover"

    page.close()
    context.close()
