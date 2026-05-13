"""
Workflow tests: New User Registration → Club Discovery → Join → Ride Signup

Documents and verifies the complete journey of a brand-new platform user.

NOTE: Flask's /auth/register route redirects to /auth/login after success (does
NOT auto-login). Tests must call login() explicitly after _register().
Flask's /auth/login short-circuits if already authenticated, so tests must call
logout() before switching to a different user.

Scenarios
---------
A  Auto-approval club (happy path)
   register → login → browse directory → view club → join (active) → sign waiver →
   view ride detail → sign up for ride → unsign

B  Manual-approval club — approved path
   register → login → join (pending) → ride signup blocked → admin approves →
   re-login → sign waiver → ride signup succeeds

C  Manual-approval club — rejected path
   register → login → join (pending) → admin rejects → membership deleted → no ride access

D  Private club — route protection
   non-member sees club on directory; ride hides RideWithGPS URL; GPX returns 403;
   after joining, route URL becomes visible

E  Profile completion
   register → login → update zip code + emergency contact → DB reflects changes
"""
import pytest
from datetime import date, time, timedelta
from tests.conftest import login, logout
from app.models import (
    User, Club, ClubMembership, ClubAdmin, ClubWaiver, WaiverSignature,
    Ride, RideSignup,
)
from app.extensions import db as _db


# ── Shared helpers ────────────────────────────────────────────────────────────

def _make_user(db, username, email, password='TestPass1!'):
    from app.extensions import bcrypt
    user = User(
        username=username, email=email,
        password_hash=bcrypt.generate_password_hash(password).decode(),
    )
    db.session.add(user)
    db.session.commit()
    return user


def _make_club(db, slug, name, **kwargs):
    club = Club(
        slug=slug, name=name,
        city='Reston', state='VA', zip_code='20191',
        lat=38.9376, lng=-77.3476,
        **kwargs,
    )
    db.session.add(club)
    db.session.commit()
    return club


def _make_waiver(db, club):
    w = ClubWaiver(
        club_id=club.id, year=date.today().year,
        title='Annual Riding Waiver',
        body='I understand and accept the inherent risks of cycling.',
    )
    db.session.add(w)
    db.session.commit()
    return w


def _make_ride(db, club, title='Morning B Ride', days_ahead=7, **kwargs):
    ride = Ride(
        club_id=club.id, title=title,
        date=date.today() + timedelta(days=days_ahead),
        time=time(9, 0),
        meeting_location='Town Square Parking Lot',
        distance_miles=25.0,
        pace_category='B',
        ride_type='road',
        **kwargs,
    )
    db.session.add(ride)
    db.session.commit()
    return ride


def _register(client, username, email, password='TestPass1!'):
    """Create account via registration form. Does NOT log in — call login() separately."""
    return client.post('/auth/register', data={
        'username': username,
        'email': email,
        'password': password,
        'confirm_password': password,
        'policy_ack': 'y',
    }, follow_redirects=True)


def _switch_user(client, email, password='TestPass1!'):
    """Logout current user then login as a different user."""
    logout(client)
    return login(client, email, password)


# ── Scenario A: Auto-approval club, happy path ────────────────────────────────

def test_scenario_a_auto_club_full_happy_path(client, db, mock_weather):
    """
    Auto-approval club: complete round-trip from registration to signup and cancel.

    Step 1:  Register new account → User row exists in DB
    Step 2:  Login explicitly (register does not auto-login)
    Step 3:  GET /clubs/ → club name visible in directory listing
    Step 4:  GET /clubs/<slug>/ → club home page loads
    Step 5:  POST /clubs/<slug>/join → ClubMembership created with status='active'
    Step 6:  POST /clubs/<slug>/waiver → WaiverSignature row created
    Step 7:  GET /clubs/<slug>/rides/<id> → ride detail page loads with title
    Step 8:  POST /clubs/<slug>/rides/<id>/signup → RideSignup row created
    Step 9:  POST /clubs/<slug>/rides/<id>/unsignup → RideSignup row deleted
    """
    club = _make_club(db, 'rbc', 'Reston Bike Club',
                      join_approval='auto', require_membership=True)
    _make_waiver(db, club)
    ride = _make_ride(db, club, title='Saturday Morning B Ride')

    # Step 1: Register (user created but NOT logged in)
    resp = _register(client, 'alice', 'alice@test.com')
    assert resp.status_code == 200
    user = User.query.filter_by(email='alice@test.com').first()
    assert user is not None, 'User not created after registration'

    # Step 2: Login explicitly
    login(client, 'alice@test.com', 'TestPass1!')

    # Step 3: Club directory
    resp = client.get('/clubs/')
    assert resp.status_code == 200
    assert b'Reston Bike Club' in resp.data, 'Club should appear in directory'

    # Step 4: Club home page
    resp = client.get(f'/clubs/{club.slug}/')
    assert resp.status_code == 200
    assert b'Reston Bike Club' in resp.data

    # Step 5: Join club (auto-approval → immediately active)
    resp = client.post(f'/clubs/{club.slug}/join', follow_redirects=True)
    assert resp.status_code == 200
    m = ClubMembership.query.filter_by(user_id=user.id, club_id=club.id).first()
    assert m is not None, 'Membership not created after join'
    assert m.status == 'active', f'Expected active membership, got {m.status!r}'

    # Step 6: Sign annual waiver
    resp = client.post(f'/clubs/{club.slug}/waiver',
                       data={'agree': '1'}, follow_redirects=True)
    assert resp.status_code == 200
    sig = WaiverSignature.query.filter_by(user_id=user.id, club_id=club.id).first()
    assert sig is not None, 'Waiver signature not recorded'

    # Step 7: Ride detail page
    resp = client.get(f'/clubs/{club.slug}/rides/{ride.id}')
    assert resp.status_code == 200
    assert b'Saturday Morning B Ride' in resp.data

    # Step 8: Sign up for ride
    resp = client.post(f'/clubs/{club.slug}/rides/{ride.id}/signup',
                       follow_redirects=True)
    assert resp.status_code == 200
    signup = RideSignup.query.filter_by(user_id=user.id, ride_id=ride.id).first()
    assert signup is not None, 'RideSignup not created'

    # Step 9: Unsign (cancel) from ride
    resp = client.post(f'/clubs/{club.slug}/rides/{ride.id}/unsignup',
                       follow_redirects=True)
    assert resp.status_code == 200
    signup = RideSignup.query.filter_by(user_id=user.id, ride_id=ride.id).first()
    assert signup is None, 'Signup should be deleted after unsign'


# ── Scenario B: Manual-approval club — pending → approved → signup ─────────────

def test_scenario_b_manual_club_pending_then_approved(client, db, mock_weather):
    """
    Manual-approval club: user waits pending until admin approves.

    Step 1:  Register + login → join manual club → status='pending'
    Step 2:  Attempt ride signup while pending → blocked (require_membership=True)
    Step 3:  Switch to admin → approve membership → status='active'
    Step 4:  Switch back to user → sign waiver + sign up for ride → succeeds
    """
    club = _make_club(db, 'nvcc', 'Northern Virginia Cycling Club',
                      join_approval='manual', require_membership=True)
    admin = _make_user(db, 'nvcc_admin', 'nvcc_admin@test.com')
    db.session.add(ClubAdmin(user_id=admin.id, club_id=club.id, role='admin'))
    db.session.commit()
    _make_waiver(db, club)
    ride = _make_ride(db, club, title='NVCC Tuesday Ride')

    # Step 1: Register + login + join → pending
    _register(client, 'bob', 'bob@test.com')
    user = User.query.filter_by(email='bob@test.com').first()
    login(client, 'bob@test.com', 'TestPass1!')

    resp = client.post(f'/clubs/{club.slug}/join', follow_redirects=True)
    assert resp.status_code == 200
    m = ClubMembership.query.filter_by(user_id=user.id, club_id=club.id).first()
    assert m is not None
    assert m.status == 'pending', f'Expected pending status, got {m.status!r}'

    # Step 2: Ride signup blocked for pending member
    resp = client.post(f'/clubs/{club.slug}/rides/{ride.id}/signup',
                       follow_redirects=True)
    assert resp.status_code == 200
    signup = RideSignup.query.filter_by(user_id=user.id, ride_id=ride.id).first()
    assert signup is None, 'Pending member should not be able to sign up for rides'

    # Step 3: Switch to admin → approve membership
    _switch_user(client, 'nvcc_admin@test.com')
    resp = client.post(f'/admin/clubs/{club.slug}/members/{user.id}/approve',
                       follow_redirects=True)
    assert resp.status_code == 200
    _db.session.expire(m)
    assert m.status == 'active', f'Expected active after approval, got {m.status!r}'

    # Step 4: Switch back to bob → sign waiver + sign up
    _switch_user(client, 'bob@test.com')
    client.post(f'/clubs/{club.slug}/waiver',
                data={'agree': '1'}, follow_redirects=True)
    resp = client.post(f'/clubs/{club.slug}/rides/{ride.id}/signup',
                       follow_redirects=True)
    assert resp.status_code == 200
    signup = RideSignup.query.filter_by(user_id=user.id, ride_id=ride.id).first()
    assert signup is not None, 'Approved member should be able to sign up for rides'


# ── Scenario C: Manual-approval club — rejected path ─────────────────────────

def test_scenario_c_manual_club_rejected(client, db, mock_weather):
    """
    Manual-approval club: admin rejects join request → membership deleted.

    Step 1:  Register + login + join manual club → status='pending'
    Step 2:  Switch to admin → reject → ClubMembership row deleted
    Step 3:  Switch back to user → ride signup blocked (no membership)
    """
    club = _make_club(db, 'dcvelo', 'DC Velo',
                      join_approval='manual', require_membership=True)
    admin = _make_user(db, 'dcvelo_admin', 'dcvelo_admin@test.com')
    db.session.add(ClubAdmin(user_id=admin.id, club_id=club.id, role='admin'))
    db.session.commit()
    ride = _make_ride(db, club, title='DC Velo Wednesday Ride')

    # Step 1: Register + login + join → pending
    _register(client, 'carol', 'carol@test.com')
    user = User.query.filter_by(email='carol@test.com').first()
    login(client, 'carol@test.com', 'TestPass1!')

    client.post(f'/clubs/{club.slug}/join', follow_redirects=True)
    m = ClubMembership.query.filter_by(user_id=user.id, club_id=club.id).first()
    assert m is not None and m.status == 'pending'

    # Step 2: Switch to admin → reject
    _switch_user(client, 'dcvelo_admin@test.com')
    resp = client.post(f'/admin/clubs/{club.slug}/members/{user.id}/reject',
                       follow_redirects=True)
    assert resp.status_code == 200
    m = ClubMembership.query.filter_by(user_id=user.id, club_id=club.id).first()
    assert m is None, 'Membership row should be deleted on rejection'

    # Step 3: Switch back to carol → no signup possible after rejection
    _switch_user(client, 'carol@test.com')
    client.post(f'/clubs/{club.slug}/rides/{ride.id}/signup', follow_redirects=True)
    signup = RideSignup.query.filter_by(user_id=user.id, ride_id=ride.id).first()
    assert signup is None, 'Rejected user should not be able to sign up'


# ── Scenario D: Private club — route protection ───────────────────────────────

def test_scenario_d_private_club_hides_route_from_non_member(client, db, mock_weather):
    """
    Private club: non-members see the club on the directory but ride detail
    hides the RideWithGPS route URL, and GPX download returns 403.
    After joining (auto-approval), the route URL becomes visible.

    Step 1:  Login + GET /clubs/ → private club appears in directory
    Step 2:  GET /clubs/<slug>/rides/<id> → rwgps URL not in response body
    Step 3:  GET /clubs/<slug>/rides/<id>/gpx → 403 Forbidden
    Step 4:  POST /clubs/<slug>/join → active member
    Step 5:  GET /clubs/<slug>/rides/<id> → rwgps URL now visible
    """
    club = _make_club(db, 'privatecc', 'Secret Cycling Club',
                      is_private=True, join_approval='auto')
    ride = _make_ride(db, club, title='Secret Group Ride',
                      route_url='https://ridewithgps.com/routes/99999')

    _register(client, 'dave', 'dave@test.com')
    user = User.query.filter_by(email='dave@test.com').first()
    login(client, 'dave@test.com', 'TestPass1!')

    # Step 1: Club visible on directory despite being private
    resp = client.get('/clubs/')
    assert b'Secret Cycling Club' in resp.data

    # Step 2: Ride detail page hides route URL from non-members
    resp = client.get(f'/clubs/{club.slug}/rides/{ride.id}')
    assert resp.status_code == 200
    assert b'ridewithgps.com/routes/99999' not in resp.data, \
        'Route URL should be hidden from non-members of a private club'

    # Step 3: GPX download blocked
    resp = client.get(f'/clubs/{club.slug}/rides/{ride.id}/gpx')
    assert resp.status_code == 403, \
        f'GPX should return 403 for non-members, got {resp.status_code}'

    # Step 4: Join club (auto-approval → active)
    resp = client.post(f'/clubs/{club.slug}/join', follow_redirects=True)
    assert resp.status_code == 200
    m = ClubMembership.query.filter_by(user_id=user.id, club_id=club.id).first()
    assert m.status == 'active'

    # Step 5: Route URL now visible to active member
    resp = client.get(f'/clubs/{club.slug}/rides/{ride.id}')
    assert b'ridewithgps.com/routes/99999' in resp.data, \
        'Route URL should be visible to active members'


# ── Scenario E: Profile completion ───────────────────────────────────────────

def test_scenario_e_new_user_updates_profile(client, db):
    """
    New user completes their profile with zip code and emergency contact info.

    Step 1:  Register + login → user has no zip or emergency contact
    Step 2:  POST /auth/profile with zip_code + emergency contact fields
    Step 3:  DB row updated with new values
    """
    # Step 1: Register with minimal data, then login
    _register(client, 'erin', 'erin@test.com')
    user = User.query.filter_by(email='erin@test.com').first()
    assert user is not None
    assert user.zip_code is None
    login(client, 'erin@test.com', 'TestPass1!')

    # Step 2: Update profile
    resp = client.post('/auth/profile', data={
        'username': 'erin',
        'email': 'erin@test.com',
        'zip_code': '20191',
        'emergency_contact_name': 'Frank Doe',
        'emergency_contact_phone': '703-555-0199',
    }, follow_redirects=True)
    assert resp.status_code == 200

    # Step 3: DB reflects updates
    _db.session.expire(user)
    assert user.zip_code == '20191', 'Zip code should be saved'
    assert user.emergency_contact_name == 'Frank Doe', 'Emergency contact name should be saved'
    assert user.emergency_contact_phone == '703-555-0199', 'Emergency contact phone should be saved'
