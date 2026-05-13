"""
Workflow tests: Club Creator → Setup → Ride Management → Team Management → Membership

Documents the complete journey of a user who creates and operates a cycling club.

NOTE: Flask's /auth/register redirects to /auth/login after success (no auto-login).
Flask's /auth/login short-circuits if already authenticated. Always call logout()
before switching to a different user via the _switch_user() helper.

Branches
--------
A  Club creation via wizard
   register → login → POST /clubs/create → club row + admin role + member created

B  Club settings customization
   Update join_approval, require_membership, theme colors via /admin/clubs/<slug>/settings

C  Ride creation (multiple types)
   Create road, gravel, and training rides; verify each appears on calendar

D  Team management — ride manager
   ride_manager can create rides; cannot access /settings (403) or /team/add (403)

E  Team management — full admin add + remove
   Add second full admin → settings accessible; remove → access revoked

F  Membership management — approve + reject
   Approve one pending member (can sign up); reject another (membership deleted)

G  Full end-to-end scenario
   create club → configure → create rides → add ride manager → member approval → signup
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
        title='Club Annual Waiver',
        body='I agree to participate safely and accept the risks of cycling.',
    )
    db.session.add(w)
    db.session.commit()
    return w


def _make_ride(db, club, title='Test Ride', pace='B', ride_type='road', days_ahead=7):
    ride = Ride(
        club_id=club.id, title=title,
        date=date.today() + timedelta(days=days_ahead),
        time=time(9, 0),
        meeting_location='Town Square',
        distance_miles=25.0,
        pace_category=pace,
        ride_type=ride_type,
    )
    db.session.add(ride)
    db.session.commit()
    return ride


def _ride_form_data(title='New Ride', pace='B', ride_type='road', days_ahead=7):
    """Return POST data dict for the admin ride creation form."""
    return {
        'title': title,
        'date': (date.today() + timedelta(days=days_ahead)).strftime('%Y-%m-%d'),
        'time': '09:00',
        'meeting_location': 'Community Center Parking Lot',
        'distance_miles': '25.0',
        'elevation_feet': '800',
        'pace_category': pace,
        'ride_type': ride_type,
    }


def _register(client, username, email, password='TestPass1!'):
    """Create account via form. Does NOT log in — call login() separately."""
    return client.post('/auth/register', data={
        'username': username, 'email': email,
        'password': password, 'confirm_password': password,
        'policy_ack': 'y',
    }, follow_redirects=True)


def _switch_user(client, email, password='TestPass1!'):
    """Logout current user then login as a different user."""
    logout(client)
    return login(client, email, password)


# ── Branch A: Club creation via wizard ────────────────────────────────────────

def test_branch_a_create_club_via_wizard(client, db):
    """
    Logged-in user submits the club creation form.

    Step 1:  Register + login
    Step 2:  POST /clubs/create with name, location, and Forest theme
    Step 3:  Club row created with correct slug and theme_primary color
    Step 4:  Creator has a ClubAdmin row with role='admin'
    Step 5:  Creator has an active ClubMembership
    Step 6:  Club appears in /clubs/ directory
    Step 7:  Admin dashboard at /admin/clubs/<slug>/ returns 200
    """
    _register(client, 'founder', 'founder@test.com')
    user = User.query.filter_by(email='founder@test.com').first()
    login(client, 'founder@test.com', 'TestPass1!')

    # Step 2: Submit club creation form
    resp = client.post('/clubs/create', data={
        'name': 'Blue Ridge Cyclists',
        'city': 'Reston', 'state': 'VA', 'zip_code': '20191',
        'is_private': '0',
        'theme_preset': 'forest',
        'theme_primary': '#2d6a4f',
        'theme_accent': '#e76f51',
        'description': 'A club for cyclists who love the Blue Ridge trails.',
        'contact_email': 'info@blueridgecyclists.com',
        'logo_url': '',
        'banner_url': '',
    }, follow_redirects=True)
    assert resp.status_code == 200

    # Step 3: Club created with correct data
    club = Club.query.filter_by(name='Blue Ridge Cyclists').first()
    assert club is not None, 'Club row not created'
    assert club.slug == 'blue-ridge-cyclists', f'Unexpected slug: {club.slug!r}'
    assert club.theme_primary == '#2d6a4f'

    # Step 4: Creator is a full admin
    admin_row = ClubAdmin.query.filter_by(user_id=user.id, club_id=club.id).first()
    assert admin_row is not None, 'Creator should have a ClubAdmin row'
    assert admin_row.role == 'admin', f'Expected admin role, got {admin_row.role!r}'

    # Step 5: Creator is an active member
    m = ClubMembership.query.filter_by(user_id=user.id, club_id=club.id).first()
    assert m is not None and m.status == 'active', 'Creator should be an active member'

    # Step 6: Club appears in directory
    resp = client.get('/clubs/')
    assert b'Blue Ridge Cyclists' in resp.data

    # Step 7: Admin dashboard accessible
    resp = client.get(f'/admin/clubs/{club.slug}/')
    assert resp.status_code == 200


# ── Branch B: Settings customization ─────────────────────────────────────────

def test_branch_b_customize_club_settings(client, db):
    """
    Club admin updates membership and theme settings.

    Step 1:  Create club + admin user; login
    Step 2:  POST /admin/clubs/<slug>/settings — change join_approval to manual
             and enable require_membership
    Step 3:  DB reflects new join_approval and require_membership values
    Step 4:  Theme color update reflected in DB
    """
    user = _make_user(db, 'mgr', 'mgr@test.com')
    club = _make_club(db, 'speedsters', 'Speedsters CC',
                      join_approval='auto', require_membership=False)
    db.session.add(ClubAdmin(user_id=user.id, club_id=club.id, role='admin'))
    db.session.commit()

    login(client, 'mgr@test.com', 'TestPass1!')

    # Steps 2–4: Submit settings form
    resp = client.post(f'/admin/clubs/{club.slug}/settings', data={
        'name': 'Speedsters CC',
        'city': 'Reston', 'state': 'VA', 'zip_code': '20191',
        'contact_email': 'info@speedsters.cc',
        'join_approval': 'manual',
        'require_membership': 'y',  # BooleanField — any truthy value = True
        'theme_primary': '#1a5276',
        'theme_accent': '#f39c12',
        'description': 'A fast club.',
        'tagline': 'Ride Hard',
        'address': '',
        'logo_url': '',
        'banner_url': '',
    }, follow_redirects=True)
    assert resp.status_code == 200

    # Step 3: Verify DB
    _db.session.refresh(club)
    assert club.join_approval == 'manual', \
        f'Expected join_approval=manual, got {club.join_approval!r}'
    assert club.require_membership is True

    # Step 4: Theme color
    assert club.theme_primary == '#1a5276', \
        f'Expected theme_primary=#1a5276, got {club.theme_primary!r}'


# ── Branch C: Create multiple ride types ─────────────────────────────────────

def test_branch_c_admin_creates_multiple_ride_types(client, db, mock_weather):
    """
    Club admin creates a road ride, a gravel ride, and a training ride.

    For each: POST /admin/clubs/<slug>/rides/new → Ride row created with correct
    pace_category and ride_type → all rides appear on the calendar.
    """
    user = _make_user(db, 'rdmgr', 'rdmgr@test.com')
    club = _make_club(db, 'multicycle', 'Multi-Ride Club')
    db.session.add(ClubAdmin(user_id=user.id, club_id=club.id, role='admin'))
    db.session.commit()

    login(client, 'rdmgr@test.com', 'TestPass1!')

    ride_specs = [
        ('Saturday Road Ride',      'A', 'road',     8),
        ('Sunday Gravel Adventure', 'B', 'gravel',   9),
        ('Tuesday Training Ride',   'C', 'training', 2),
    ]

    for title, pace, rtype, days in ride_specs:
        resp = client.post(
            f'/admin/clubs/{club.slug}/rides/new',
            data=_ride_form_data(title=title, pace=pace, ride_type=rtype,
                                  days_ahead=days),
            follow_redirects=True,
        )
        assert resp.status_code == 200, f'Ride creation failed for {title!r}'
        r = Ride.query.filter_by(club_id=club.id, title=title).first()
        assert r is not None, f'Ride {title!r} not in DB after creation'
        assert r.pace_category == pace
        assert r.ride_type == rtype

    # All three rides appear on the calendar
    resp = client.get(f'/clubs/{club.slug}/rides/')
    for title, _, _, _ in ride_specs:
        assert title.encode() in resp.data, f'{title!r} not found on calendar page'


# ── Branch D: Ride manager — limited access ───────────────────────────────────

def test_branch_d_ride_manager_limited_access(client, db, mock_weather):
    """
    A ride manager can create rides but cannot access settings or team management.

    Step 1:  Login as full admin → add ride_manager via /admin/clubs/<slug>/team/add
    Step 2:  ClubAdmin row created with role='ride_manager'
    Step 3:  Switch to ride manager → create a ride (200, ride exists in DB)
    Step 4:  Ride manager requests /admin/clubs/<slug>/settings → 403
    Step 5:  Ride manager posts to /admin/clubs/<slug>/team/add → 403
    """
    full_admin = _make_user(db, 'fulladmin', 'fulladmin@test.com')
    ride_mgr = _make_user(db, 'ridemgr', 'ridemgr@test.com')
    club = _make_club(db, 'gateclub', 'Gate Test Club')
    db.session.add(ClubAdmin(user_id=full_admin.id, club_id=club.id, role='admin'))
    db.session.commit()

    # Step 1: Full admin adds ride manager
    login(client, 'fulladmin@test.com', 'TestPass1!')
    resp = client.post(f'/admin/clubs/{club.slug}/team/add', data={
        'identifier': 'ridemgr@test.com',
        'role': 'ride_manager',
    }, follow_redirects=True)
    assert resp.status_code == 200

    # Step 2: Verify ClubAdmin row
    row = ClubAdmin.query.filter_by(user_id=ride_mgr.id, club_id=club.id).first()
    assert row is not None, 'ClubAdmin row not created for ride manager'
    assert row.role == 'ride_manager', f'Expected ride_manager role, got {row.role!r}'

    # Step 3: Switch to ride manager, create a ride
    _switch_user(client, 'ridemgr@test.com')
    resp = client.post(
        f'/admin/clubs/{club.slug}/rides/new',
        data=_ride_form_data(title='Ride Manager Ride'),
        follow_redirects=True,
    )
    assert resp.status_code == 200
    r = Ride.query.filter_by(club_id=club.id, title='Ride Manager Ride').first()
    assert r is not None, 'Ride manager should be able to create rides'

    # Step 4: Ride manager cannot access club settings
    resp = client.get(f'/admin/clubs/{club.slug}/settings')
    assert resp.status_code in (302, 403), \
        f'Ride manager should be denied settings access, got {resp.status_code}'

    # Step 5: Ride manager cannot add team members
    resp = client.post(f'/admin/clubs/{club.slug}/team/add', data={
        'identifier': 'anyone@test.com',
        'role': 'ride_manager',
    })
    assert resp.status_code in (302, 403), \
        f'Ride manager should be denied team/add access, got {resp.status_code}'


# ── Branch E: Full admin add + remove ────────────────────────────────────────

def test_branch_e_add_and_remove_full_admin(client, db):
    """
    Owner adds a second full admin; that admin can access settings.
    Owner removes the second admin; settings access is revoked.

    Step 1:  Login as owner → add second user as role='admin'
    Step 2:  Switch to second admin → GET /admin/clubs/<slug>/settings → 200
    Step 3:  Switch back to owner → remove second admin (uses ClubAdmin.id)
    Step 4:  ClubAdmin row deleted
    Step 5:  Switch to second admin → GET /admin/clubs/<slug>/settings → 302/403
    """
    owner = _make_user(db, 'owner', 'owner@test.com')
    second = _make_user(db, 'second', 'second@test.com')
    club = _make_club(db, 'permclub', 'Permission Test Club')
    db.session.add(ClubAdmin(user_id=owner.id, club_id=club.id, role='admin'))
    db.session.commit()

    # Step 1: Add second admin
    login(client, 'owner@test.com', 'TestPass1!')
    resp = client.post(f'/admin/clubs/{club.slug}/team/add', data={
        'identifier': 'second@test.com',
        'role': 'admin',
    }, follow_redirects=True)
    assert resp.status_code == 200
    row = ClubAdmin.query.filter_by(user_id=second.id, club_id=club.id).first()
    assert row is not None and row.role == 'admin', 'Second admin not created'

    # Step 2: Second admin can access settings
    _switch_user(client, 'second@test.com')
    resp = client.get(f'/admin/clubs/{club.slug}/settings')
    assert resp.status_code == 200, 'Full admin should be able to access settings'

    # Step 3: Owner removes second admin (route uses ClubAdmin.id, not user.id)
    _switch_user(client, 'owner@test.com')
    resp = client.post(
        f'/admin/clubs/{club.slug}/team/{row.id}/remove',
        follow_redirects=True,
    )
    assert resp.status_code == 200

    # Step 4: ClubAdmin row deleted
    row = ClubAdmin.query.filter_by(user_id=second.id, club_id=club.id).first()
    assert row is None, 'ClubAdmin row should be deleted after removal'

    # Step 5: Access revoked
    _switch_user(client, 'second@test.com')
    resp = client.get(f'/admin/clubs/{club.slug}/settings')
    assert resp.status_code in (302, 403), \
        f'Removed admin should no longer access settings, got {resp.status_code}'


# ── Branch F: Membership management — approve + reject ───────────────────────

def test_branch_f_approve_and_reject_members(client, db, mock_weather):
    """
    Admin approves one pending member (can sign up) and rejects another
    (membership deleted).

    Step 1:  Login as user_a → join manual club → pending
    Step 2:  Switch to user_b → join manual club → pending
    Step 3:  Switch to admin → approve user_a → status='active'
    Step 4:  Admin rejects user_b → membership row deleted
    Step 5:  Switch to user_a → sign waiver + sign up → succeeds
    Step 6:  Switch to user_b → signup blocked (no membership)
    """
    admin = _make_user(db, 'clubowner', 'clubowner@test.com')
    user_a = _make_user(db, 'user_a', 'user_a@test.com')
    user_b = _make_user(db, 'user_b', 'user_b@test.com')
    club = _make_club(db, 'manualclub', 'Manual Approval Club',
                      join_approval='manual', require_membership=True)
    db.session.add(ClubAdmin(user_id=admin.id, club_id=club.id, role='admin'))
    db.session.commit()
    _make_waiver(db, club)
    ride = _make_ride(db, club, title='Club Saturday Ride')

    # Step 1: user_a joins → pending
    login(client, 'user_a@test.com', 'TestPass1!')
    client.post(f'/clubs/{club.slug}/join', follow_redirects=True)
    ma = ClubMembership.query.filter_by(user_id=user_a.id, club_id=club.id).first()
    assert ma is not None and ma.status == 'pending'

    # Step 2: user_b joins → pending
    _switch_user(client, 'user_b@test.com')
    client.post(f'/clubs/{club.slug}/join', follow_redirects=True)
    mb = ClubMembership.query.filter_by(user_id=user_b.id, club_id=club.id).first()
    assert mb is not None and mb.status == 'pending'

    # Step 3: Admin approves user_a
    _switch_user(client, 'clubowner@test.com')
    resp = client.post(
        f'/admin/clubs/{club.slug}/members/{user_a.id}/approve',
        follow_redirects=True,
    )
    assert resp.status_code == 200
    _db.session.refresh(ma)
    assert ma.status == 'active', f'Expected active after approval, got {ma.status!r}'

    # Step 4: Admin rejects user_b
    resp = client.post(
        f'/admin/clubs/{club.slug}/members/{user_b.id}/reject',
        follow_redirects=True,
    )
    assert resp.status_code == 200
    mb = ClubMembership.query.filter_by(user_id=user_b.id, club_id=club.id).first()
    assert mb is None, 'Rejected membership should be deleted'

    # Step 5: user_a signs waiver + signs up
    _switch_user(client, 'user_a@test.com')
    client.post(f'/clubs/{club.slug}/waiver',
                data={'agree': '1'}, follow_redirects=True)
    resp = client.post(
        f'/clubs/{club.slug}/rides/{ride.id}/signup',
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert RideSignup.query.filter_by(
        user_id=user_a.id, ride_id=ride.id).first() is not None, \
        'Approved member should be able to sign up'

    # Step 6: user_b cannot sign up
    _switch_user(client, 'user_b@test.com')
    client.post(f'/clubs/{club.slug}/rides/{ride.id}/signup', follow_redirects=True)
    assert RideSignup.query.filter_by(
        user_id=user_b.id, ride_id=ride.id).first() is None, \
        'Rejected user should not be able to sign up'


# ── Branch G: Full end-to-end lifecycle ──────────────────────────────────────

def test_branch_g_full_club_lifecycle(client, db, mock_weather):
    """
    Complete club lifecycle integrating all branches.

    create club → configure (manual, require_membership) → create 3 rides →
    add ride manager → ride manager creates ride → member joins (pending) →
    admin approves → member signs waiver + signs up for ride
    """
    rm_user = _make_user(db, 'grm', 'grm@test.com')
    member = _make_user(db, 'gmember', 'gmember@test.com')

    # ── G.1: Create club via wizard ───────────────────────────────────────────
    _register(client, 'gFounder', 'gfounder@test.com')
    founder = User.query.filter_by(email='gfounder@test.com').first()
    login(client, 'gfounder@test.com', 'TestPass1!')

    resp = client.post('/clubs/create', data={
        'name': 'Grand Tour CC',
        'city': 'Reston', 'state': 'VA', 'zip_code': '20191',
        'is_private': '0',
        'theme_preset': 'ocean',
        'theme_primary': '#1a5276',
        'theme_accent': '#f39c12',
        'description': 'A club for ambitious cyclists.',
        'contact_email': '',
        'logo_url': '',
        'banner_url': '',
    }, follow_redirects=True)
    assert resp.status_code == 200
    club = Club.query.filter_by(name='Grand Tour CC').first()
    assert club is not None, 'Club not created'

    # ── G.2: Configure settings ────────────────────────────────────────────────
    resp = client.post(f'/admin/clubs/{club.slug}/settings', data={
        'name': 'Grand Tour CC',
        'city': 'Reston', 'state': 'VA', 'zip_code': '20191',
        'contact_email': '',
        'join_approval': 'manual',
        'require_membership': 'y',
        'theme_primary': '#1a5276',
        'theme_accent': '#f39c12',
        'description': 'A club for ambitious cyclists.',
        'tagline': 'Ride Far, Ride Together',
        'address': '',
        'logo_url': '',
        'banner_url': '',
    }, follow_redirects=True)
    assert resp.status_code == 200
    _db.session.refresh(club)
    assert club.join_approval == 'manual'
    assert club.require_membership is True
    _make_waiver(db, club)

    # ── G.3: Create 3 rides ────────────────────────────────────────────────────
    for title, pace, rtype, days in [
        ('Sunday Road A Group',   'A', 'road',     7),
        ('Saturday Gravel Loop',  'B', 'gravel',   8),
        ('Wednesday Training',    'C', 'training', 3),
    ]:
        resp = client.post(
            f'/admin/clubs/{club.slug}/rides/new',
            data=_ride_form_data(title=title, pace=pace, ride_type=rtype,
                                  days_ahead=days),
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert Ride.query.filter_by(club_id=club.id, title=title).first() is not None

    # ── G.4: Add ride manager and have them create a ride ─────────────────────
    resp = client.post(f'/admin/clubs/{club.slug}/team/add', data={
        'identifier': 'grm@test.com',
        'role': 'ride_manager',
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert ClubAdmin.query.filter_by(
        user_id=rm_user.id, club_id=club.id).first() is not None

    _switch_user(client, 'grm@test.com')
    resp = client.post(
        f'/admin/clubs/{club.slug}/rides/new',
        data=_ride_form_data(title='RM Thursday Ride', days_ahead=4),
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert Ride.query.filter_by(
        club_id=club.id, title='RM Thursday Ride').first() is not None

    # ── G.5: Member joins → pending → approved → signs up ────────────────────
    _switch_user(client, 'gmember@test.com')
    client.post(f'/clubs/{club.slug}/join', follow_redirects=True)
    m = ClubMembership.query.filter_by(
        user_id=member.id, club_id=club.id).first()
    assert m is not None and m.status == 'pending', \
        f'Expected pending membership, got {getattr(m, "status", None)!r}'

    # Founder approves
    _switch_user(client, 'gfounder@test.com')
    resp = client.post(
        f'/admin/clubs/{club.slug}/members/{member.id}/approve',
        follow_redirects=True,
    )
    assert resp.status_code == 200
    _db.session.refresh(m)
    assert m.status == 'active'

    # Member signs waiver + signs up for road ride
    _switch_user(client, 'gmember@test.com')
    client.post(f'/clubs/{club.slug}/waiver',
                data={'agree': '1'}, follow_redirects=True)
    road_ride = Ride.query.filter_by(
        club_id=club.id, title='Sunday Road A Group').first()
    resp = client.post(
        f'/clubs/{club.slug}/rides/{road_ride.id}/signup',
        follow_redirects=True,
    )
    assert resp.status_code == 200
    signup = RideSignup.query.filter_by(
        user_id=member.id, ride_id=road_ride.id).first()
    assert signup is not None, 'Approved member should be able to sign up for rides'
