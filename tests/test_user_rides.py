"""Tests for the user-ride feature: creation quota, access control, invite/request flow."""
import pytest
from datetime import date, time, timedelta

from app.extensions import db as _db
from app.models import Ride, RideSignup, UserRideInvite
from tests.conftest import login, logout

TODAY = date.today()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ride_date_in_week(offset=1):
    """Return a date within the current calendar week (or offset days from today)."""
    return TODAY + timedelta(days=offset) if (TODAY + timedelta(days=offset)).isocalendar()[1] == TODAY.isocalendar()[1] else TODAY


def _make_ride(db, owner, **kwargs):
    """Directly create a user-owned ride row and auto-signup the owner."""
    defaults = dict(
        owner_id=owner.id,
        club_id=None,
        title='Test Ride',
        date=TODAY + timedelta(days=1),
        time=time(9, 0),
        meeting_location='City Park',
        distance_miles=20.0,
        pace_category='B',
        ride_type='road',
        is_private=False,
        is_cancelled=False,
    )
    defaults.update(kwargs)
    ride = Ride(**defaults)
    db.session.add(ride)
    db.session.flush()
    db.session.add(RideSignup(ride_id=ride.id, user_id=owner.id))
    db.session.commit()
    return ride


def _form_data(**kwargs):
    data = dict(
        title='Saturday Spin',
        date=(TODAY + timedelta(days=2)).isoformat(),
        time='09:00',
        meeting_location='Town Square',
        distance_miles='25.0',
        elevation_feet='',
        max_riders='',
        pace_category='B',
        ride_type='road',
        ride_leader='',
        route_url='',
        video_url='',
        description='',
        is_private='',
    )
    data.update(kwargs)
    return data


# ── Create ────────────────────────────────────────────────────────────────────

class TestCreate:
    def test_create_requires_login(self, client):
        rv = client.post('/my-rides/create', data=_form_data(), follow_redirects=False)
        assert rv.status_code in (302, 401)
        assert b'/auth/login' in rv.data or rv.location.endswith('/auth/login') or '/auth/login' in rv.location

    def test_create_success(self, client, db, regular_user):
        login(client, 'rider@test.com')
        rv = client.post('/my-rides/create', data=_form_data(garmin_groupride_code='456789'), follow_redirects=True)
        assert rv.status_code == 200
        ride = Ride.query.filter_by(owner_id=regular_user.id).first()
        assert ride is not None
        assert ride.title == 'Saturday Spin'
        assert ride.garmin_groupride_code == '456789'
        # Creator auto-signed up
        signup = RideSignup.query.filter_by(ride_id=ride.id, user_id=regular_user.id).first()
        assert signup is not None

    def test_create_multi_pace_ride(self, client, db, regular_user):
        login(client, 'rider@test.com')
        rv = client.post('/my-rides/create', data=_form_data(
            pace_category='B',
            is_multi_pace='y',
            multi_pace_a='y',
            multi_pace_b='y',
            multi_pace_c='y',
        ), follow_redirects=True)
        assert rv.status_code == 200
        ride = Ride.query.filter_by(owner_id=regular_user.id).first()
        assert ride.is_multi_pace is True
        assert ride.pace_category == 'A'
        assert ride.pace_categories == ['A', 'B', 'C']
        assert b'A / B / C groups on the same course' in rv.data

    def test_create_multi_pace_requires_two_groups(self, client, db, regular_user):
        login(client, 'rider@test.com')
        rv = client.post('/my-rides/create', data=_form_data(
            is_multi_pace='y',
            multi_pace_b='y',
        ), follow_redirects=True)
        assert rv.status_code == 200
        assert b'Select at least two pace groups' in rv.data
        assert Ride.query.filter_by(owner_id=regular_user.id).count() == 0

    def test_create_private_ride(self, client, db, regular_user):
        login(client, 'rider@test.com')
        rv = client.post('/my-rides/create', data=_form_data(is_private='y'), follow_redirects=True)
        assert rv.status_code == 200
        ride = Ride.query.filter_by(owner_id=regular_user.id).first()
        assert ride.is_private is True

    def test_quota_enforced_on_get(self, client, db, regular_user):
        """GET /my-rides/create redirects when quota is full."""
        for i in range(7):
            _make_ride(db, regular_user, date=TODAY)
        login(client, 'rider@test.com')
        rv = client.get('/my-rides/create', follow_redirects=False)
        assert rv.status_code == 302
        assert '/my-rides' in rv.location

    def test_quota_enforced_on_post(self, client, db, regular_user):
        """POST to create is rejected when quota is full."""
        for i in range(7):
            _make_ride(db, regular_user, date=TODAY)
        login(client, 'rider@test.com')
        rv = client.post('/my-rides/create', data=_form_data(), follow_redirects=True)
        assert rv.status_code == 200
        # No new ride should have been created
        assert Ride.query.filter_by(owner_id=regular_user.id).count() == 7

    def test_quota_ignores_other_weeks(self, client, db, regular_user):
        """Rides from previous weeks don't count toward this week's quota."""
        week_start = TODAY - timedelta(days=TODAY.weekday())
        # Place 7 rides in last week
        last_week_start = week_start - timedelta(days=7)
        for i in range(7):
            _make_ride(db, regular_user, date=last_week_start + timedelta(days=i))
        login(client, 'rider@test.com')
        # GET should succeed (quota = 0 this week)
        rv = client.get('/my-rides/create')
        assert rv.status_code == 200

    def test_quota_only_counts_own_rides(self, client, db, regular_user, second_user):
        """Other users' rides don't count toward the current user's quota."""
        for i in range(7):
            _make_ride(db, second_user, date=TODAY)
        login(client, 'rider@test.com')
        rv = client.get('/my-rides/create')
        assert rv.status_code == 200


# ── Edit / Delete ─────────────────────────────────────────────────────────────

class TestEditDelete:
    def test_owner_can_edit(self, client, db, regular_user):
        ride = _make_ride(db, regular_user)
        login(client, 'rider@test.com')
        rv = client.post(f'/my-rides/{ride.id}/edit', data=_form_data(title='Updated Ride', garmin_groupride_code='567890'),
                         follow_redirects=True)
        assert rv.status_code == 200
        db.session.refresh(ride)
        assert ride.title == 'Updated Ride'
        assert ride.garmin_groupride_code == '567890'

    def test_owner_can_delete(self, client, db, regular_user):
        ride = _make_ride(db, regular_user)
        ride_id = ride.id
        login(client, 'rider@test.com')
        rv = client.post(f'/my-rides/{ride_id}/delete', follow_redirects=True)
        assert rv.status_code == 200
        assert Ride.query.get(ride_id) is None

    def test_non_owner_cannot_edit(self, client, db, regular_user, second_user):
        ride = _make_ride(db, regular_user)
        login(client, 'rider2@test.com')
        rv = client.post(f'/my-rides/{ride.id}/edit', data=_form_data(title='Hijacked'),
                         follow_redirects=False)
        assert rv.status_code == 404
        db.session.refresh(ride)
        assert ride.title == 'Test Ride'

    def test_non_owner_cannot_delete(self, client, db, regular_user, second_user):
        ride = _make_ride(db, regular_user)
        ride_id = ride.id
        login(client, 'rider2@test.com')
        rv = client.post(f'/my-rides/{ride_id}/delete', follow_redirects=False)
        assert rv.status_code == 404
        assert Ride.query.get(ride_id) is not None


# ── Public ride signup ────────────────────────────────────────────────────────

class TestPublicSignup:
    def test_detail_visible_to_all(self, client, db, regular_user):
        ride = _make_ride(db, regular_user, is_private=False)
        rv = client.get(f'/my-rides/{ride.id}')
        assert rv.status_code == 200
        assert b'Test Ride' in rv.data

    def test_other_user_can_signup(self, client, db, regular_user, second_user):
        ride = _make_ride(db, regular_user, is_private=False)
        login(client, 'rider2@test.com')
        rv = client.post(f'/my-rides/{ride.id}/signup', follow_redirects=True)
        assert rv.status_code == 200
        assert RideSignup.query.filter_by(ride_id=ride.id, user_id=second_user.id).first() is not None

    def test_other_user_can_unsignup(self, client, db, regular_user, second_user):
        ride = _make_ride(db, regular_user, is_private=False)
        _db.session.add(RideSignup(ride_id=ride.id, user_id=second_user.id))
        _db.session.commit()
        login(client, 'rider2@test.com')
        rv = client.post(f'/my-rides/{ride.id}/unsignup', follow_redirects=True)
        assert rv.status_code == 200
        assert RideSignup.query.filter_by(ride_id=ride.id, user_id=second_user.id).first() is None

    def test_owner_cannot_unsignup_own_ride(self, client, db, regular_user):
        ride = _make_ride(db, regular_user, is_private=False)
        login(client, 'rider@test.com')
        rv = client.post(f'/my-rides/{ride.id}/unsignup', follow_redirects=True)
        assert rv.status_code == 200
        assert b"can&#39;t leave your own ride" in rv.data or b"can't leave" in rv.data

    def test_full_ride_blocks_signup(self, client, db, regular_user, second_user):
        ride = _make_ride(db, regular_user, is_private=False, max_riders=1)
        login(client, 'rider2@test.com')
        rv = client.post(f'/my-rides/{ride.id}/signup', follow_redirects=True)
        assert rv.status_code == 200
        assert RideSignup.query.filter_by(ride_id=ride.id, user_id=second_user.id).first() is None

    def test_private_ride_blocks_signup(self, client, db, regular_user, second_user):
        ride = _make_ride(db, regular_user, is_private=True)
        login(client, 'rider2@test.com')
        rv = client.post(f'/my-rides/{ride.id}/signup', follow_redirects=True)
        assert rv.status_code == 200
        assert RideSignup.query.filter_by(ride_id=ride.id, user_id=second_user.id).first() is None

    def test_signed_up_rider_can_add_blank_garmin_groupride_code(self, client, db, regular_user, second_user):
        ride = _make_ride(db, regular_user, is_private=False)
        db.session.add(RideSignup(ride_id=ride.id, user_id=second_user.id))
        db.session.commit()
        login(client, 'rider2@test.com')
        rv = client.post(
            f'/my-rides/{ride.id}/groupride-code',
            data={'garmin_groupride_code': '654321'},
            follow_redirects=True,
        )
        assert rv.status_code == 200
        db.session.refresh(ride)
        assert ride.garmin_groupride_code == '654321'

    def test_signed_up_rider_cannot_overwrite_garmin_groupride_code(self, client, db, regular_user, second_user):
        ride = _make_ride(db, regular_user, is_private=False, garmin_groupride_code='111222')
        db.session.add(RideSignup(ride_id=ride.id, user_id=second_user.id))
        db.session.commit()
        login(client, 'rider2@test.com')
        rv = client.post(
            f'/my-rides/{ride.id}/groupride-code',
            data={'garmin_groupride_code': '654321'},
            follow_redirects=False,
        )
        assert rv.status_code == 403
        db.session.refresh(ride)
        assert ride.garmin_groupride_code == '111222'

    def test_owner_can_clear_garmin_groupride_code(self, client, db, regular_user):
        ride = _make_ride(db, regular_user, garmin_groupride_code='111222')
        login(client, 'rider@test.com')
        rv = client.post(
            f'/my-rides/{ride.id}/groupride-code',
            data={'garmin_groupride_code': ''},
            follow_redirects=True,
        )
        assert rv.status_code == 200
        db.session.refresh(ride)
        assert ride.garmin_groupride_code is None


# ── Private ride access control ───────────────────────────────────────────────

class TestPrivateAccess:
    def test_anonymous_sees_locked_view(self, client, db, regular_user):
        ride = _make_ride(db, regular_user, is_private=True)
        rv = client.get(f'/my-rides/{ride.id}')
        assert rv.status_code == 200
        assert b'Private ride' in rv.data or b'Request Access' in rv.data or b'locked' in rv.data.lower()
        assert b'City Park' not in rv.data  # meeting location hidden

    def test_unauthenticated_user_sees_locked_view(self, client, db, regular_user):
        ride = _make_ride(db, regular_user, is_private=True)
        rv = client.get(f'/my-rides/{ride.id}')
        assert rv.status_code == 200
        assert b'City Park' not in rv.data

    def test_request_access_creates_invite(self, client, db, regular_user, second_user):
        ride = _make_ride(db, regular_user, is_private=True)
        login(client, 'rider2@test.com')
        rv = client.post(f'/my-rides/{ride.id}/request-access', follow_redirects=True)
        assert rv.status_code == 200
        inv = UserRideInvite.query.filter_by(ride_id=ride.id, user_id=second_user.id).first()
        assert inv is not None
        assert inv.status == 'requested'

    def test_duplicate_request_shows_pending_message(self, client, db, regular_user, second_user):
        ride = _make_ride(db, regular_user, is_private=True)
        _db.session.add(UserRideInvite(ride_id=ride.id, user_id=second_user.id, status='requested'))
        _db.session.commit()
        login(client, 'rider2@test.com')
        rv = client.post(f'/my-rides/{ride.id}/request-access', follow_redirects=True)
        assert rv.status_code == 200
        assert b'pending' in rv.data.lower()

    def test_owner_approves_request(self, client, db, regular_user, second_user):
        ride = _make_ride(db, regular_user, is_private=True)
        inv = UserRideInvite(ride_id=ride.id, user_id=second_user.id, status='requested')
        _db.session.add(inv)
        _db.session.commit()
        login(client, 'rider@test.com')
        rv = client.post(f'/my-rides/{ride.id}/invites/{inv.id}/approve', follow_redirects=True)
        assert rv.status_code == 200
        _db.session.refresh(inv)
        assert inv.status == 'accepted'
        assert RideSignup.query.filter_by(ride_id=ride.id, user_id=second_user.id).first() is not None

    def test_owner_declines_request(self, client, db, regular_user, second_user):
        ride = _make_ride(db, regular_user, is_private=True)
        inv = UserRideInvite(ride_id=ride.id, user_id=second_user.id, status='requested')
        _db.session.add(inv)
        _db.session.commit()
        login(client, 'rider@test.com')
        rv = client.post(f'/my-rides/{ride.id}/invites/{inv.id}/decline', follow_redirects=True)
        assert rv.status_code == 200
        _db.session.refresh(inv)
        assert inv.status == 'declined'

    def test_owner_invites_user(self, client, db, regular_user, second_user):
        ride = _make_ride(db, regular_user, is_private=True)
        login(client, 'rider@test.com')
        rv = client.post(f'/my-rides/{ride.id}/invite',
                         data={'identifier': 'rider2'},
                         follow_redirects=True)
        assert rv.status_code == 200
        inv = UserRideInvite.query.filter_by(ride_id=ride.id, user_id=second_user.id).first()
        assert inv is not None
        assert inv.status == 'invited'

    def test_invited_user_can_accept(self, client, db, regular_user, second_user):
        ride = _make_ride(db, regular_user, is_private=True)
        inv = UserRideInvite(ride_id=ride.id, user_id=second_user.id, status='invited')
        _db.session.add(inv)
        _db.session.commit()
        login(client, 'rider2@test.com')
        rv = client.post(f'/my-rides/{ride.id}/invites/{inv.id}/accept', follow_redirects=True)
        assert rv.status_code == 200
        _db.session.refresh(inv)
        assert inv.status == 'accepted'
        assert RideSignup.query.filter_by(ride_id=ride.id, user_id=second_user.id).first() is not None

    def test_accepted_user_sees_details(self, client, db, regular_user, second_user):
        ride = _make_ride(db, regular_user, is_private=True)
        _db.session.add(UserRideInvite(ride_id=ride.id, user_id=second_user.id, status='accepted'))
        _db.session.add(RideSignup(ride_id=ride.id, user_id=second_user.id))
        _db.session.commit()
        login(client, 'rider2@test.com')
        rv = client.get(f'/my-rides/{ride.id}')
        assert rv.status_code == 200
        assert b'City Park' in rv.data  # meeting location visible

    def test_non_owner_cannot_invite(self, client, db, regular_user, second_user):
        ride = _make_ride(db, regular_user, is_private=True)
        login(client, 'rider2@test.com')
        rv = client.post(f'/my-rides/{ride.id}/invite',
                         data={'identifier': 'rider'},
                         follow_redirects=False)
        assert rv.status_code == 404

    def test_accepting_outstanding_invite_via_request_access(self, client, db, regular_user, second_user):
        """If owner already invited the user and they hit request-access, it auto-accepts."""
        ride = _make_ride(db, regular_user, is_private=True)
        inv = UserRideInvite(ride_id=ride.id, user_id=second_user.id, status='invited')
        _db.session.add(inv)
        _db.session.commit()
        login(client, 'rider2@test.com')
        rv = client.post(f'/my-rides/{ride.id}/request-access', follow_redirects=True)
        assert rv.status_code == 200
        _db.session.refresh(inv)
        assert inv.status == 'accepted'


# ── Discover page ─────────────────────────────────────────────────────────────

class TestDiscover:
    def test_discover_includes_public_user_rides(self, client, db, regular_user, mock_weather):
        ride = _make_ride(db, regular_user, is_private=False, title='Public User Ride')
        rv = client.get('/discover/?source=all')
        assert rv.status_code == 200
        assert b'Public User Ride' in rv.data

    def test_discover_excludes_private_user_rides(self, client, db, regular_user, mock_weather):
        ride = _make_ride(db, regular_user, is_private=True, title='Secret Ride')
        rv = client.get('/discover/?source=all')
        assert rv.status_code == 200
        assert b'Secret Ride' not in rv.data


# ── My Rides list ─────────────────────────────────────────────────────────────

class TestListRides:
    def test_list_shows_own_rides(self, client, db, regular_user):
        ride = _make_ride(db, regular_user, title='My Personal Ride')
        login(client, 'rider@test.com')
        rv = client.get('/my-rides/')
        assert rv.status_code == 200
        assert b'My Personal Ride' in rv.data

    def test_list_hidden_from_unauthenticated(self, client):
        rv = client.get('/my-rides/', follow_redirects=False)
        assert rv.status_code == 302
        assert '/auth/login' in rv.location

    def test_quota_badge_shown_when_full(self, client, db, regular_user):
        for i in range(7):
            _make_ride(db, regular_user, date=TODAY)
        login(client, 'rider@test.com')
        rv = client.get('/my-rides/')
        assert rv.status_code == 200
        assert b'Weekly limit reached' in rv.data
