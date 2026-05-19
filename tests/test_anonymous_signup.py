"""Tests for anonymous ride signup, public profiles, and auth-gated personal info."""
import pytest
from datetime import date, time, timedelta

from app.extensions import db as _db
from app.models import Ride, RideSignup, User
from tests.conftest import login, logout

TODAY = date.today()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_club_ride(db, club, **kwargs):
    defaults = dict(
        club_id=club.id,
        title='Test Club Ride',
        date=TODAY + timedelta(days=3),
        time=time(9, 0),
        meeting_location='Town Hall',
        distance_miles=30.0,
        pace_category='B',
        ride_type='road',
        is_cancelled=False,
    )
    defaults.update(kwargs)
    ride = Ride(**defaults)
    db.session.add(ride)
    db.session.commit()
    return ride


def _make_user_ride(db, owner, **kwargs):
    defaults = dict(
        owner_id=owner.id,
        club_id=None,
        title='Personal Ride',
        date=TODAY + timedelta(days=2),
        time=time(8, 0),
        meeting_location='Park Entrance',
        distance_miles=20.0,
        pace_category='C',
        ride_type='social',
        is_private=False,
        is_cancelled=False,
    )
    defaults.update(kwargs)
    ride = Ride(**defaults)
    db.session.add(ride)
    db.session.flush()
    _db.session.add(RideSignup(ride_id=ride.id, user_id=owner.id))
    _db.session.commit()
    return ride


# ── Anonymous club ride signup ────────────────────────────────────────────────

class TestAnonymousClubSignup:
    def test_anonymous_signup_stores_flag(self, client, db, sample_club, regular_user):
        ride = _make_club_ride(db, sample_club)
        login(client, 'rider@test.com')
        client.post(f'/clubs/{sample_club.slug}/rides/{ride.id}/signup',
                    data={'is_anonymous': '1'})
        s = RideSignup.query.filter_by(ride_id=ride.id, user_id=regular_user.id).first()
        assert s is not None
        assert s.is_anonymous is True

    def test_non_anonymous_signup_default(self, client, db, sample_club, regular_user):
        ride = _make_club_ride(db, sample_club)
        login(client, 'rider@test.com')
        client.post(f'/clubs/{sample_club.slug}/rides/{ride.id}/signup', data={})
        s = RideSignup.query.filter_by(ride_id=ride.id, user_id=regular_user.id).first()
        assert s is not None
        assert s.is_anonymous is False

    def test_anonymous_rider_hidden_in_who_is_coming(self, client, db, sample_club,
                                                      regular_user, second_user):
        ride = _make_club_ride(db, sample_club)
        # regular_user signs up anonymously
        _db.session.add(RideSignup(ride_id=ride.id, user_id=regular_user.id, is_anonymous=True))
        _db.session.commit()
        # second_user views the ride (not an admin)
        login(client, 'rider2@test.com')
        rv = client.get(f'/clubs/{sample_club.slug}/rides/{ride.id}')
        assert rv.status_code == 200
        assert b'rider</a>' not in rv.data  # username not shown as link
        assert b'Anonymous' in rv.data
        assert b'Rider' in rv.data

    def test_admin_sees_real_name_for_anon_signup(self, client, db, sample_club,
                                                   regular_user, club_admin_user):
        ride = _make_club_ride(db, sample_club)
        _db.session.add(RideSignup(ride_id=ride.id, user_id=regular_user.id, is_anonymous=True))
        _db.session.commit()
        login(client, 'clubadmin@test.com')
        rv = client.get(f'/clubs/{sample_club.slug}/rides/{ride.id}')
        assert rv.status_code == 200
        assert b'rider' in rv.data      # real username shown to admin
        assert b'anon' in rv.data       # but marked as anonymous

    def test_non_anonymous_signup_shows_profile_link(self, client, db, sample_club,
                                                      regular_user, second_user):
        ride = _make_club_ride(db, sample_club)
        _db.session.add(RideSignup(ride_id=ride.id, user_id=regular_user.id, is_anonymous=False))
        _db.session.commit()
        login(client, 'rider2@test.com')
        rv = client.get(f'/clubs/{sample_club.slug}/rides/{ride.id}')
        assert rv.status_code == 200
        assert b'/users/rider' in rv.data  # profile link present

    def test_unauthenticated_cannot_see_signup_list(self, client, db, sample_club, regular_user):
        ride = _make_club_ride(db, sample_club)
        _db.session.add(RideSignup(ride_id=ride.id, user_id=regular_user.id))
        _db.session.commit()
        rv = client.get(f'/clubs/{sample_club.slug}/rides/{ride.id}')
        assert rv.status_code == 200
        assert b'Who\'s coming' not in rv.data
        assert b'Sign in</a> to see who' in rv.data


# ── Anonymous user ride signup ────────────────────────────────────────────────

class TestAnonymousUserRideSignup:
    def test_anonymous_signup_on_user_ride(self, client, db, regular_user, second_user):
        ride = _make_user_ride(db, regular_user)
        login(client, 'rider2@test.com')
        client.post(f'/my-rides/{ride.id}/signup', data={'is_anonymous': '1'})
        s = RideSignup.query.filter_by(ride_id=ride.id, user_id=second_user.id).first()
        assert s is not None
        assert s.is_anonymous is True

    def test_owner_sees_real_name_for_anon(self, client, db, regular_user, second_user):
        ride = _make_user_ride(db, regular_user)
        _db.session.add(RideSignup(ride_id=ride.id, user_id=second_user.id, is_anonymous=True))
        _db.session.commit()
        login(client, 'rider@test.com')
        rv = client.get(f'/my-rides/{ride.id}')
        assert rv.status_code == 200
        assert b'rider2' in rv.data
        assert b'anon' in rv.data

    def test_non_owner_sees_anonymous_display(self, client, db, regular_user, second_user):
        ride = _make_user_ride(db, regular_user)
        second_user.gender = 'female'
        _db.session.add(RideSignup(ride_id=ride.id, user_id=second_user.id, is_anonymous=True))
        _db.session.commit()
        # A third user views (create one inline)
        from app.extensions import bcrypt
        third = User(username='third', email='third@test.com',
                     password_hash=bcrypt.generate_password_hash('password123').decode())
        _db.session.add(third)
        _db.session.commit()
        login(client, 'third@test.com')
        rv = client.get(f'/my-rides/{ride.id}')
        assert rv.status_code == 200
        assert b'rider2' not in rv.data
        assert b'Anonymous Female Rider' in rv.data


# ── Public profile ─────────────────────────────────────────────────────────────

class TestPublicProfile:
    def test_public_profile_requires_login(self, client, db, regular_user):
        rv = client.get(f'/users/{regular_user.username}', follow_redirects=False)
        assert rv.status_code == 302
        assert '/auth/login' in rv.location

    def test_public_profile_shows_bio(self, client, db, regular_user, second_user):
        regular_user.bio = 'Avid gravel rider from Ashburn.'
        regular_user.profile_is_public = True
        _db.session.commit()
        login(client, 'rider2@test.com')
        rv = client.get(f'/users/rider')
        assert rv.status_code == 200
        assert b'Avid gravel rider from Ashburn.' in rv.data

    def test_public_profile_shows_strava_link(self, client, db, regular_user, second_user):
        regular_user.strava_id = 12345678
        regular_user.profile_is_public = True
        _db.session.commit()
        login(client, 'rider2@test.com')
        rv = client.get(f'/users/rider')
        assert rv.status_code == 200
        assert b'strava.com/athletes/12345678' in rv.data

    def test_public_profile_shows_public_rides(self, client, db, sample_club,
                                               regular_user, second_user):
        regular_user.profile_is_public = True
        past_date = TODAY - timedelta(days=10)
        ride = _make_club_ride(db, sample_club, date=past_date, title='Past Club Ride')
        _db.session.add(RideSignup(ride_id=ride.id, user_id=regular_user.id, is_anonymous=False))
        _db.session.commit()
        login(client, 'rider2@test.com')
        rv = client.get(f'/users/rider')
        assert rv.status_code == 200
        assert b'Past Club Ride' in rv.data

    def test_public_profile_hides_anonymous_rides(self, client, db, sample_club,
                                                  regular_user, second_user):
        regular_user.profile_is_public = True
        past_date = TODAY - timedelta(days=5)
        ride = _make_club_ride(db, sample_club, date=past_date, title='Secret Ride')
        _db.session.add(RideSignup(ride_id=ride.id, user_id=regular_user.id, is_anonymous=True))
        _db.session.commit()
        login(client, 'rider2@test.com')
        rv = client.get(f'/users/rider')
        assert rv.status_code == 200
        assert b'Secret Ride' not in rv.data

    def test_public_profile_404_for_unknown_user(self, client, db, regular_user):
        login(client, 'rider@test.com')
        rv = client.get('/users/nobody-exists')
        assert rv.status_code == 404


# ── Profile form: gender and bio ──────────────────────────────────────────────

class TestProfileGenderBio:
    def test_save_gender_and_bio(self, client, db, regular_user):
        login(client, 'rider@test.com')
        rv = client.post('/auth/profile', data={
            'username': 'rider',
            'email': 'rider@test.com',
            'zip_code': '',
            'gender': 'female',
            'bio': 'Gravel enthusiast.',
            'emergency_contact_name': '',
            'emergency_contact_phone': '',
        }, follow_redirects=True)
        assert rv.status_code == 200
        _db.session.refresh(regular_user)
        assert regular_user.gender == 'female'
        assert regular_user.bio == 'Gravel enthusiast.'

    def test_gender_affects_anonymous_display(self, client, db, sample_club, regular_user, second_user):
        regular_user.gender = 'male'
        _db.session.commit()
        ride = _make_club_ride(db, sample_club)
        _db.session.add(RideSignup(ride_id=ride.id, user_id=regular_user.id, is_anonymous=True))
        _db.session.commit()
        login(client, 'rider2@test.com')
        rv = client.get(f'/clubs/{sample_club.slug}/rides/{ride.id}')
        assert b'Anonymous Male Rider' in rv.data
