"""
Tests for membership-gated ride signups, join approval modes,
pending membership state, and private club route protection.
"""
from datetime import date, timedelta

import pytest
from tests.conftest import login, logout
from app.models import Club, ClubMembership, ClubAdmin


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def membership_club(db):
    """Club that requires membership to sign up for rides, auto-approve."""
    club = Club(
        slug='members-only',
        name='Members Only Club',
        city='Reston', state='VA',
        require_membership=True,
        join_approval='auto',
        is_hidden=False,
    )
    db.session.add(club)
    db.session.commit()
    return club


@pytest.fixture
def manual_approval_club(db):
    """Club that requires membership with manual admin approval."""
    club = Club(
        slug='manual-club',
        name='Manual Approval Club',
        city='Reston', state='VA',
        require_membership=True,
        join_approval='manual',
        is_hidden=False,
    )
    db.session.add(club)
    db.session.commit()
    return club


@pytest.fixture
def private_club(db):
    """Private club — route details hidden from non-members."""
    club = Club(
        slug='private-club',
        name='Private Cycling Club',
        city='Reston', state='VA',
        is_private=True,
        is_hidden=False,
    )
    db.session.add(club)
    db.session.commit()
    return club


@pytest.fixture
def club_admin(db, membership_club, club_admin_user):
    """club_admin_user gets admin role on membership_club."""
    from app.models import ClubAdmin
    db.session.add(ClubAdmin(user_id=club_admin_user.id, club_id=membership_club.id, role='admin'))
    db.session.commit()
    return club_admin_user


@pytest.fixture
def manual_club_admin(db, manual_approval_club):
    """Separate admin user for manual_approval_club."""
    from app.extensions import bcrypt
    from app.models import User
    user = User(
        username='manual_admin',
        email='manual_admin@test.com',
        password_hash=bcrypt.generate_password_hash('password123').decode(),
    )
    db.session.add(user)
    db.session.commit()
    db.session.add(ClubAdmin(user_id=user.id, club_id=manual_approval_club.id, role='admin'))
    db.session.commit()
    return user


@pytest.fixture
def member_ride(db, membership_club):
    """A ride on membership_club."""
    from datetime import date, time, timedelta
    from app.models import Ride
    ride = Ride(
        club_id=membership_club.id,
        title='Members-Only Tuesday Ride',
        date=date.today() + timedelta(days=3),
        time=time(17, 0),
        meeting_location='Test Location',
        distance_miles=25.0,
        pace_category='B',
    )
    db.session.add(ride)
    db.session.commit()
    return ride


@pytest.fixture
def private_ride(db, private_club):
    """A ride on the private club with a RideWithGPS route."""
    from datetime import date, time, timedelta
    from app.models import Ride
    ride = Ride(
        club_id=private_club.id,
        title='Private Club Ride',
        date=date.today() + timedelta(days=3),
        time=time(8, 0),
        meeting_location='Secret Location',
        distance_miles=40.0,
        pace_category='A',
        route_url='https://ridewithgps.com/routes/35103917',
    )
    db.session.add(ride)
    db.session.commit()
    return ride


# ── Club settings — membership section ───────────────────────────────────────

def test_settings_saves_require_membership(client, db, sample_club, club_admin_user):
    login(client, email='clubadmin@test.com')
    r = client.post(f'/admin/clubs/{sample_club.slug}/settings', data={
        'name': sample_club.name,
        'description': '',
        'city': '', 'state': '', 'zip_code': '', 'address': '',
        'website': '', 'contact_email': '', 'logo_url': '',
        'theme_primary': '', 'theme_accent': '', 'banner_url': '',
        'strava_club_id': '',
        'require_membership': 'y',
        'join_approval': 'auto',
        'cancel_rain_prob': '80', 'cancel_wind_mph': '35',
        'cancel_temp_min_f': '28', 'cancel_temp_max_f': '100',
    }, follow_redirects=True)
    assert r.status_code == 200
    db.session.refresh(sample_club)
    assert sample_club.require_membership is True
    assert sample_club.join_approval == 'auto'


def test_settings_saves_manual_approval(client, db, sample_club, club_admin_user):
    login(client, email='clubadmin@test.com')
    client.post(f'/admin/clubs/{sample_club.slug}/settings', data={
        'name': sample_club.name,
        'description': '', 'city': '', 'state': '', 'zip_code': '', 'address': '',
        'website': '', 'contact_email': '', 'logo_url': '',
        'theme_primary': '', 'theme_accent': '', 'banner_url': '',
        'strava_club_id': '',
        'require_membership': 'y',
        'join_approval': 'manual',
        'cancel_rain_prob': '80', 'cancel_wind_mph': '35',
        'cancel_temp_min_f': '28', 'cancel_temp_max_f': '100',
    }, follow_redirects=True)
    db.session.refresh(sample_club)
    assert sample_club.join_approval == 'manual'


def test_settings_saves_paid_dues_configuration(client, db, sample_club, club_admin_user):
    login(client, email='clubadmin@test.com')
    r = client.post(f'/admin/clubs/{sample_club.slug}/settings', data={
        'name': sample_club.name,
        'description': '', 'city': '', 'state': '', 'zip_code': '', 'address': '',
        'website': '', 'contact_email': '', 'logo_url': '',
        'theme_primary': '', 'theme_accent': '', 'banner_url': '',
        'strava_club_id': '',
        'require_membership': 'y',
        'join_approval': 'auto',
        'membership_dues_required': 'y',
        'membership_duration_months': '12',
        'cancel_rain_prob': '80', 'cancel_wind_mph': '35',
        'cancel_temp_min_f': '28', 'cancel_temp_max_f': '100',
    }, follow_redirects=True)
    assert r.status_code == 200
    db.session.refresh(sample_club)
    assert sample_club.membership_dues_required is True
    assert sample_club.membership_dues_mode == 'stripe_connect'
    assert sample_club.membership_duration_months == 12


# ── Auto-approve join flow ────────────────────────────────────────────────────

def test_auto_approve_join_creates_active_membership(client, db, membership_club, regular_user):
    login(client)
    r = client.post(f'/clubs/{membership_club.slug}/join', follow_redirects=True)
    assert r.status_code == 200
    row = ClubMembership.query.filter_by(user_id=regular_user.id, club_id=membership_club.id).first()
    assert row is not None
    assert row.status == 'active'


def test_auto_approve_join_shows_success_flash(client, db, membership_club, regular_user):
    login(client)
    r = client.post(f'/clubs/{membership_club.slug}/join', follow_redirects=True)
    assert b"joined" in r.data.lower()


def test_paid_dues_join_creates_pending_payment_membership(client, db, membership_club, regular_user):
    membership_club.membership_dues_required = True
    db.session.commit()
    login(client)
    r = client.post(f'/clubs/{membership_club.slug}/join', follow_redirects=True)
    row = ClubMembership.query.filter_by(user_id=regular_user.id, club_id=membership_club.id).first()
    assert r.status_code == 200
    assert row is not None
    assert row.status == 'pending_payment'


def test_admin_confirms_paid_dues_activates_membership(client, db, membership_club, club_admin, regular_user):
    membership_club.membership_dues_required = True
    membership_club.membership_duration_months = 6
    db.session.add(ClubMembership(user_id=regular_user.id, club_id=membership_club.id, status='pending_payment'))
    db.session.commit()

    login(client, email='clubadmin@test.com')
    r = client.post(
        f'/admin/clubs/{membership_club.slug}/members/{regular_user.id}/confirm-dues',
        follow_redirects=True,
    )
    row = ClubMembership.query.filter_by(user_id=regular_user.id, club_id=membership_club.id).first()
    assert r.status_code == 200
    assert row.status == 'active'
    assert row.dues_paid_until is not None
    assert row.dues_confirmed_by_id == club_admin.id


# ── Manual approval join flow ─────────────────────────────────────────────────

def test_manual_approval_join_creates_pending_membership(client, db, manual_approval_club, regular_user):
    login(client)
    client.post(f'/clubs/{manual_approval_club.slug}/join', follow_redirects=True)
    row = ClubMembership.query.filter_by(user_id=regular_user.id, club_id=manual_approval_club.id).first()
    assert row is not None
    assert row.status == 'pending'


def test_manual_approval_join_shows_pending_flash(client, db, manual_approval_club, regular_user):
    login(client)
    r = client.post(f'/clubs/{manual_approval_club.slug}/join', follow_redirects=True)
    assert b'pending' in r.data.lower() or b'admin will review' in r.data.lower()


def test_pending_member_sees_pending_approval_button(client, db, manual_approval_club, regular_user):
    db.session.add(ClubMembership(user_id=regular_user.id, club_id=manual_approval_club.id, status='pending'))
    db.session.commit()
    login(client)
    r = client.get(f'/clubs/{manual_approval_club.slug}/')
    assert b'Pending Approval' in r.data
    assert b'Join Club' not in r.data


def test_active_member_sees_leave_button(client, db, manual_approval_club, regular_user):
    db.session.add(ClubMembership(user_id=regular_user.id, club_id=manual_approval_club.id, status='active'))
    db.session.commit()
    login(client)
    r = client.get(f'/clubs/{manual_approval_club.slug}/')
    assert b'Leave Club' in r.data


# ── Membership model helpers ──────────────────────────────────────────────────

def test_is_active_member_of_true_for_active(db, sample_club, regular_user):
    db.session.add(ClubMembership(user_id=regular_user.id, club_id=sample_club.id, status='active'))
    db.session.commit()
    assert regular_user.is_active_member_of(sample_club) is True


def test_is_active_member_of_false_for_pending(db, sample_club, regular_user):
    db.session.add(ClubMembership(user_id=regular_user.id, club_id=sample_club.id, status='pending'))
    db.session.commit()
    assert regular_user.is_active_member_of(sample_club) is False


def test_is_pending_member_of_true_for_pending(db, sample_club, regular_user):
    db.session.add(ClubMembership(user_id=regular_user.id, club_id=sample_club.id, status='pending'))
    db.session.commit()
    assert regular_user.is_pending_member_of(sample_club) is True


def test_is_pending_member_of_false_for_active(db, sample_club, regular_user):
    db.session.add(ClubMembership(user_id=regular_user.id, club_id=sample_club.id, status='active'))
    db.session.commit()
    assert regular_user.is_pending_member_of(sample_club) is False


# ── Ride signup membership gate ───────────────────────────────────────────────

def test_non_member_blocked_from_signup(client, db, membership_club, member_ride, regular_user):
    login(client)
    r = client.post(f'/clubs/{membership_club.slug}/rides/{member_ride.id}/signup',
                    follow_redirects=True)
    assert r.status_code == 200
    # Should redirect to club home with warning, not sign up
    from app.models import RideSignup
    signup = RideSignup.query.filter_by(ride_id=member_ride.id, user_id=regular_user.id).first()
    assert signup is None


def test_pending_member_blocked_from_signup(client, db, membership_club, member_ride, regular_user):
    db.session.add(ClubMembership(user_id=regular_user.id, club_id=membership_club.id, status='pending'))
    db.session.commit()
    login(client)
    client.post(f'/clubs/{membership_club.slug}/rides/{member_ride.id}/signup',
                follow_redirects=True)
    from app.models import RideSignup
    signup = RideSignup.query.filter_by(ride_id=member_ride.id, user_id=regular_user.id).first()
    assert signup is None


def test_active_member_can_signup(client, db, membership_club, member_ride, regular_user):
    db.session.add(ClubMembership(user_id=regular_user.id, club_id=membership_club.id, status='active'))
    db.session.commit()
    login(client)
    r = client.post(f'/clubs/{membership_club.slug}/rides/{member_ride.id}/signup',
                    follow_redirects=True)
    assert r.status_code == 200
    from app.models import RideSignup
    signup = RideSignup.query.filter_by(ride_id=member_ride.id, user_id=regular_user.id).first()
    assert signup is not None


def test_expired_paid_membership_cannot_signup(client, db, membership_club, member_ride, regular_user):
    db.session.add(ClubMembership(
        user_id=regular_user.id,
        club_id=membership_club.id,
        status='active',
        dues_paid_until=date.today() - timedelta(days=1),
    ))
    db.session.commit()
    login(client)
    client.post(f'/clubs/{membership_club.slug}/rides/{member_ride.id}/signup',
                follow_redirects=True)
    from app.models import RideSignup
    signup = RideSignup.query.filter_by(ride_id=member_ride.id, user_id=regular_user.id).first()
    assert signup is None


def test_ride_detail_shows_membership_warning_for_non_member(client, db, membership_club, member_ride, regular_user):
    login(client)
    r = client.get(f'/clubs/{membership_club.slug}/rides/{member_ride.id}')
    assert r.status_code == 200
    assert b'must be an active member' in r.data or b'join' in r.data.lower()


# ── Admin approval/rejection ──────────────────────────────────────────────────

def test_admin_approves_pending_member(client, db, manual_approval_club, manual_club_admin, regular_user):
    db.session.add(ClubMembership(user_id=regular_user.id, club_id=manual_approval_club.id, status='pending'))
    db.session.commit()
    login(client, email='manual_admin@test.com')
    r = client.post(f'/admin/clubs/{manual_approval_club.slug}/members/{regular_user.id}/approve',
                    follow_redirects=True)
    assert r.status_code == 200
    row = ClubMembership.query.filter_by(user_id=regular_user.id, club_id=manual_approval_club.id).first()
    assert row.status == 'active'


def test_admin_rejects_pending_member(client, db, manual_approval_club, manual_club_admin, regular_user):
    db.session.add(ClubMembership(user_id=regular_user.id, club_id=manual_approval_club.id, status='pending'))
    db.session.commit()
    login(client, email='manual_admin@test.com')
    r = client.post(f'/admin/clubs/{manual_approval_club.slug}/members/{regular_user.id}/reject',
                    follow_redirects=True)
    assert r.status_code == 200
    row = ClubMembership.query.filter_by(user_id=regular_user.id, club_id=manual_approval_club.id).first()
    assert row is None


def test_team_page_shows_pending_section(client, db, manual_approval_club, manual_club_admin, regular_user):
    db.session.add(ClubMembership(user_id=regular_user.id, club_id=manual_approval_club.id, status='pending'))
    db.session.commit()
    login(client, email='manual_admin@test.com')
    r = client.get(f'/admin/clubs/{manual_approval_club.slug}/team')
    assert r.status_code == 200
    assert b'Pending Requests' in r.data or b'pending' in r.data.lower()


# ── Private club route hiding ─────────────────────────────────────────────────

def test_private_club_hides_route_from_non_member(client, db, private_club, private_ride, regular_user):
    login(client)
    r = client.get(f'/clubs/{private_club.slug}/rides/{private_ride.id}')
    assert r.status_code == 200
    assert b'Route details are available to club members only' in r.data


def test_private_club_shows_route_to_active_member(client, db, private_club, private_ride, regular_user):
    db.session.add(ClubMembership(user_id=regular_user.id, club_id=private_club.id, status='active'))
    db.session.commit()
    login(client)
    r = client.get(f'/clubs/{private_club.slug}/rides/{private_ride.id}')
    assert r.status_code == 200
    assert b'Route details are available to club members only' not in r.data


def test_private_club_hides_route_from_pending_member(client, db, private_club, private_ride, regular_user):
    db.session.add(ClubMembership(user_id=regular_user.id, club_id=private_club.id, status='pending'))
    db.session.commit()
    login(client)
    r = client.get(f'/clubs/{private_club.slug}/rides/{private_ride.id}')
    assert r.status_code == 200
    assert b'Route details are available to club members only' in r.data


def test_private_club_gpx_blocked_for_non_member(client, db, private_club, private_ride, regular_user):
    login(client)
    r = client.get(f'/clubs/{private_club.slug}/rides/{private_ride.id}/gpx')
    assert r.status_code == 403


def test_private_club_gpx_allowed_for_active_member(client, db, private_club, private_ride, regular_user):
    db.session.add(ClubMembership(user_id=regular_user.id, club_id=private_club.id, status='active'))
    db.session.commit()
    login(client)
    # Route to GPX proxies RideWithGPS — just check it doesn't 403
    r = client.get(f'/clubs/{private_club.slug}/rides/{private_ride.id}/gpx')
    assert r.status_code != 403


# ── Member count only counts active ──────────────────────────────────────────

def test_member_count_excludes_pending(db, sample_club, regular_user, second_user):
    db.session.add(ClubMembership(user_id=regular_user.id, club_id=sample_club.id, status='active'))
    db.session.add(ClubMembership(user_id=second_user.id,  club_id=sample_club.id, status='pending'))
    db.session.commit()
    assert sample_club.member_count == 1


def test_member_count_excludes_expired_paid_membership(db, sample_club, regular_user, second_user):
    db.session.add(ClubMembership(user_id=regular_user.id, club_id=sample_club.id, status='active'))
    db.session.add(ClubMembership(
        user_id=second_user.id,
        club_id=sample_club.id,
        status='active',
        dues_paid_until=date.today() - timedelta(days=1),
    ))
    db.session.commit()
    assert sample_club.member_count == 1
