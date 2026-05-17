"""
Tests for the friend/follow system.

Rules:
- Friendships are bidirectional and require both users to accept.
- Only the addressee can accept or decline.
- Only accepted friends can see each other's "Friends Riding Soon" rides.
- Users can turn off friend_ride_signup email notifications.
"""
import pytest
from datetime import date, time, timedelta
from unittest.mock import patch
from app.models import User, UserFriend, Ride, RideSignup
from app.extensions import db
from tests.conftest import login


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def third_user(db):
    from app.extensions import bcrypt
    user = User(
        username='rider3',
        email='rider3@test.com',
        password_hash=bcrypt.generate_password_hash('password123').decode(),
    )
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def accepted_friendship(db, regular_user, second_user):
    """Pre-existing accepted friendship between regular_user and second_user."""
    row = UserFriend(
        requester_id=regular_user.id,
        addressee_id=second_user.id,
        status='accepted',
    )
    db.session.add(row)
    db.session.commit()
    return row


@pytest.fixture
def pending_request(db, regular_user, second_user):
    """Pending request: regular_user → second_user."""
    row = UserFriend(
        requester_id=regular_user.id,
        addressee_id=second_user.id,
        status='pending',
    )
    db.session.add(row)
    db.session.commit()
    return row


@pytest.fixture
def club_ride(db, sample_club, regular_user):
    """An upcoming public club ride."""
    ride = Ride(
        club_id=sample_club.id,
        title='Saturday Spin',
        date=date.today() + timedelta(days=3),
        time=time(8, 0),
        meeting_location='Parking lot',
        distance_miles=30.0,
        pace_category='B',
        ride_type='road',
        created_by=regular_user.id,
    )
    db.session.add(ride)
    db.session.commit()
    return ride


# ── Public profile page ───────────────────────────────────────────────────────

class TestPublicProfileFriendUI:
    def test_shows_add_friend_button_for_stranger(self, client, regular_user, second_user):
        login(client)
        resp = client.get(f'/users/{second_user.username}')
        assert resp.status_code == 200
        assert b'Add Friend' in resp.data

    def test_shows_pending_sent_for_requester(self, client, regular_user, second_user, pending_request):
        login(client)
        resp = client.get(f'/users/{second_user.username}')
        assert b'Friend Request Sent' in resp.data

    def test_shows_accept_decline_for_addressee(self, client, regular_user, second_user, pending_request):
        login(client, email=second_user.email)
        resp = client.get(f'/users/{regular_user.username}')
        assert b'Accept' in resp.data
        assert b'Decline' in resp.data

    def test_shows_friends_status_for_accepted(self, client, regular_user, second_user, accepted_friendship):
        login(client)
        resp = client.get(f'/users/{second_user.username}')
        assert b'Friends' in resp.data
        assert b'Remove Friend' in resp.data

    def test_own_profile_no_friend_buttons(self, client, regular_user):
        login(client)
        resp = client.get(f'/users/{regular_user.username}')
        assert b'Add Friend' not in resp.data
        assert b'Friend Request Sent' not in resp.data


# ── Send friend request ───────────────────────────────────────────────────────

class TestSendFriendRequest:
    def test_can_send_request(self, client, regular_user, second_user):
        login(client)
        resp = client.post(
            f'/users/{second_user.username}/friend-request',
            follow_redirects=True,
        )
        assert resp.status_code == 200
        row = UserFriend.query.filter_by(
            requester_id=regular_user.id,
            addressee_id=second_user.id,
        ).first()
        assert row is not None
        assert row.status == 'pending'

    def test_cannot_send_to_self(self, client, regular_user):
        login(client)
        resp = client.post(
            f'/users/{regular_user.username}/friend-request',
            follow_redirects=True,
        )
        assert b'yourself' in resp.data
        assert UserFriend.query.count() == 0

    def test_duplicate_request_shows_info(self, client, regular_user, second_user, pending_request):
        login(client)
        resp = client.post(
            f'/users/{second_user.username}/friend-request',
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert UserFriend.query.count() == 1  # no duplicate

    def test_can_resend_after_declined(self, client, db, regular_user, second_user):
        row = UserFriend(requester_id=regular_user.id, addressee_id=second_user.id, status='declined')
        db.session.add(row)
        db.session.commit()
        login(client)
        client.post(f'/users/{second_user.username}/friend-request', follow_redirects=True)
        db.session.refresh(row)
        assert row.status == 'pending'


# ── Accept / decline ──────────────────────────────────────────────────────────

class TestAcceptDeclineRequest:
    def test_addressee_can_accept(self, client, regular_user, second_user, pending_request):
        login(client, email=second_user.email)
        client.post(f'/friends/{pending_request.id}/accept', follow_redirects=True)
        db.session.refresh(pending_request)
        assert pending_request.status == 'accepted'

    def test_non_addressee_cannot_accept(self, client, regular_user, second_user, pending_request, third_user):
        login(client, email=third_user.email)
        resp = client.post(f'/friends/{pending_request.id}/accept')
        assert resp.status_code == 403

    def test_addressee_can_decline(self, client, regular_user, second_user, pending_request):
        login(client, email=second_user.email)
        client.post(f'/friends/{pending_request.id}/decline', follow_redirects=True)
        db.session.refresh(pending_request)
        assert pending_request.status == 'declined'


# ── Remove friend ─────────────────────────────────────────────────────────────

class TestRemoveFriend:
    def test_can_remove_friend(self, client, regular_user, second_user, accepted_friendship):
        login(client)
        client.post(f'/friends/{second_user.id}/remove', follow_redirects=True)
        assert UserFriend.query.filter_by(id=accepted_friendship.id).first() is None

    def test_either_side_can_remove(self, client, regular_user, second_user, accepted_friendship):
        login(client, email=second_user.email)
        resp = client.post(f'/friends/{regular_user.id}/remove', follow_redirects=True)
        assert resp.status_code == 200
        assert UserFriend.query.count() == 0


# ── User model helpers ────────────────────────────────────────────────────────

class TestUserFriendHelpers:
    def test_friend_status_none(self, app, regular_user, second_user):
        with app.app_context():
            u = User.query.get(regular_user.id)
            o = User.query.get(second_user.id)
            assert u.friend_status(o) == 'none'

    def test_friend_status_pending_sent(self, app, regular_user, second_user, pending_request):
        with app.app_context():
            u = User.query.get(regular_user.id)
            o = User.query.get(second_user.id)
            assert u.friend_status(o) == 'pending_sent'

    def test_friend_status_pending_received(self, app, regular_user, second_user, pending_request):
        with app.app_context():
            u = User.query.get(second_user.id)
            o = User.query.get(regular_user.id)
            assert u.friend_status(o) == 'pending_received'

    def test_friend_status_accepted(self, app, regular_user, second_user, accepted_friendship):
        with app.app_context():
            u = User.query.get(regular_user.id)
            o = User.query.get(second_user.id)
            assert u.friend_status(o) == 'accepted'

    def test_accepted_friend_ids(self, app, regular_user, second_user, accepted_friendship):
        with app.app_context():
            u = User.query.get(regular_user.id)
            ids = u.accepted_friend_ids()
            assert second_user.id in ids

    def test_accepted_friend_ids_bidirectional(self, app, regular_user, second_user, accepted_friendship):
        """accepted_friend_ids works regardless of who sent the request."""
        with app.app_context():
            u = User.query.get(second_user.id)
            ids = u.accepted_friend_ids()
            assert regular_user.id in ids


# ── Dashboard: Friends Riding Soon ────────────────────────────────────────────

class TestDashboardFriendsRides:
    def _sign_up(self, db, user, ride):
        db.session.add(RideSignup(ride_id=ride.id, user_id=user.id))
        db.session.commit()

    def test_friends_rides_section_appears(
            self, client, db, regular_user, second_user, sample_club, club_ride,
            accepted_friendship):
        # second_user signs up for club_ride; regular_user is a member
        from app.models import ClubMembership
        db.session.add(ClubMembership(user_id=regular_user.id, club_id=sample_club.id, status='active'))
        self._sign_up(db, second_user, club_ride)
        login(client)
        with patch('app.weather.get_weather_for_rides', return_value={}):
            resp = client.get('/')
        assert b'Friends Riding Soon' in resp.data
        assert b'Saturday Spin' in resp.data

    def test_friends_rides_hidden_without_friendship(
            self, client, db, regular_user, second_user, sample_club, club_ride):
        from app.models import ClubMembership
        db.session.add(ClubMembership(user_id=regular_user.id, club_id=sample_club.id, status='active'))
        self._sign_up(db, second_user, club_ride)
        login(client)
        with patch('app.weather.get_weather_for_rides', return_value={}):
            resp = client.get('/')
        assert b'Friends Riding Soon' not in resp.data

    def test_private_club_ride_hidden_from_non_member_friend(
            self, client, db, regular_user, second_user, sample_club, club_ride,
            accepted_friendship):
        sample_club.is_private = True
        db.session.commit()
        self._sign_up(db, second_user, club_ride)
        login(client)
        with patch('app.weather.get_weather_for_rides', return_value={}):
            resp = client.get('/')
        assert b'Friends Riding Soon' not in resp.data

    def test_pending_friend_requests_on_dashboard(
            self, client, regular_user, second_user, pending_request):
        login(client, email=second_user.email)
        with patch('app.weather.get_weather_for_rides', return_value={}):
            resp = client.get('/')
        assert b'Friend Requests' in resp.data
        assert b'rider' in resp.data  # requester username


# ── Notification preference ───────────────────────────────────────────────────

class TestFriendRideSignupNotification:
    def test_notification_sent_to_friend(
            self, client, db, regular_user, second_user, sample_club, club_ride,
            accepted_friendship):
        from app.models import ClubMembership
        db.session.add(ClubMembership(user_id=second_user.id, club_id=sample_club.id, status='active'))
        db.session.commit()
        login(client, email=second_user.email)
        with patch('app.email.send_friend_ride_notification') as mock_notify:
            client.post(
                f'/clubs/{sample_club.slug}/rides/{club_ride.id}/signup',
                data={},
                follow_redirects=True,
            )
        mock_notify.assert_called_once()
        args = mock_notify.call_args[0]
        assert args[0].id == regular_user.id   # recipient
        assert args[1].id == second_user.id    # signer
        assert args[2].id == club_ride.id      # ride

    def test_notification_skipped_when_opted_out(
            self, client, db, regular_user, second_user, sample_club, club_ride,
            accepted_friendship):
        from app.models import ClubMembership
        regular_user.email_preferences = {'friend_ride_signup': False}
        db.session.add(ClubMembership(user_id=second_user.id, club_id=sample_club.id, status='active'))
        db.session.commit()
        login(client, email=second_user.email)
        with patch('app.email._send') as mock_send:
            client.post(
                f'/clubs/{sample_club.slug}/rides/{club_ride.id}/signup',
                data={},
                follow_redirects=True,
            )
        mock_send.assert_not_called()
