"""
Shared pytest fixtures for the Cycling Clubs test suite.

Uses an in-memory SQLite database — no running PostgreSQL needed.
Weather API calls are patched so tests don't require network access.
"""
import pytest
from datetime import date, time, timedelta
from unittest.mock import patch

from app import create_app
from app.extensions import db as _db
from app.models import (User, Club, ClubMembership, ClubAdmin, ClubWaiver,
                         WaiverSignature, Ride, RideSignup)


# ── Test configuration ────────────────────────────────────────────────────────

class TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False
    SECRET_KEY = 'test-secret-key'
    COOKIE_SECURE = False
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = 'Lax'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    STRAVA_CLIENT_ID = None
    STRAVA_CLIENT_SECRET = None
    STRAVA_CLUB_ID = None
    STRAVA_CLUB_REFRESH_TOKEN = None
    UPLOAD_FOLDER = '/tmp/paceline_test_uploads'
    SPACES_BUCKET = ''


# ── Core fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture(scope='function')
def app():
    application = create_app(TestConfig)
    with application.app_context():
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()


@pytest.fixture(scope='function')
def client(app):
    return app.test_client()


@pytest.fixture(scope='function')
def db(app):
    return _db


# ── User fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def admin_user(db):
    """Global superadmin user."""
    from app.extensions import bcrypt
    user = User(
        username='superadmin',
        email='admin@test.com',
        password_hash=bcrypt.generate_password_hash('password123').decode(),
        is_admin=True,
    )
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def regular_user(db):
    """Non-admin user."""
    from app.extensions import bcrypt
    user = User(
        username='rider',
        email='rider@test.com',
        password_hash=bcrypt.generate_password_hash('password123').decode(),
        is_admin=False,
        zip_code='20191',
    )
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def second_user(db):
    """A second non-admin user."""
    from app.extensions import bcrypt
    user = User(
        username='rider2',
        email='rider2@test.com',
        password_hash=bcrypt.generate_password_hash('password123').decode(),
        is_admin=False,
    )
    db.session.add(user)
    db.session.commit()
    return user


# ── Club fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def sample_club(db):
    """A basic active, visible club."""
    club = Club(
        slug='test-club',
        name='Test Cycling Club',
        description='A club for testing.',
        city='Reston', state='VA', zip_code='20191',
        lat=38.9376, lng=-77.3476,
        is_hidden=False,
    )
    db.session.add(club)
    db.session.commit()
    return club


@pytest.fixture
def second_club(db):
    """A second club for multi-club tests."""
    club = Club(
        slug='other-club',
        name='Other Cycling Club',
        city='McLean', state='VA', zip_code='22101',
        is_hidden=False,
    )
    db.session.add(club)
    db.session.commit()
    return club


@pytest.fixture
def club_admin_user(db, sample_club):
    """A user who is admin of sample_club."""
    from app.extensions import bcrypt
    user = User(
        username='clubadmin',
        email='clubadmin@test.com',
        password_hash=bcrypt.generate_password_hash('password123').decode(),
        is_admin=False,
    )
    db.session.add(user)
    db.session.commit()
    db.session.add(ClubAdmin(user_id=user.id, club_id=sample_club.id))
    db.session.commit()
    return user


@pytest.fixture
def club_waiver(db, sample_club):
    """A waiver for sample_club."""
    waiver = ClubWaiver(
        club_id=sample_club.id,
        year=date.today().year,
        title='Test Club Waiver',
        body='I agree to ride safely and wear a helmet.',
    )
    db.session.add(waiver)
    db.session.commit()
    return waiver


# ── Ride fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def sample_rides(db, sample_club):
    """
    Three rides placed in next week so they are always in the future regardless
    of what day the tests run.
    """
    today = date.today()
    # Next Monday is always at least 1 day away; if today is Monday, skip to the Monday after
    next_monday = today + timedelta(days=7 - today.weekday())

    rides = [
        Ride(
            club_id=sample_club.id,
            title='Tuesday A Ride',
            date=next_monday + timedelta(days=1),
            time=time(17, 0),
            meeting_location='Hunterwoods Shopping Center',
            distance_miles=38.0,
            elevation_feet=2100,
            pace_category='A',
            ride_type='road',
            ride_leader='Dave K.',
        ),
        Ride(
            club_id=sample_club.id,
            title='Wednesday B Ride',
            date=next_monday + timedelta(days=2),
            time=time(18, 0),
            meeting_location='The Bike Lane',
            distance_miles=25.0,
            pace_category='B',
            ride_type='road',
        ),
        Ride(
            club_id=sample_club.id,
            title='Thursday C Ride',
            date=next_monday + timedelta(days=3),
            time=time(18, 30),
            meeting_location='Lake Newport',
            distance_miles=20.0,
            pace_category='C',
            ride_type='road',
            is_cancelled=True,
        ),
    ]
    for r in rides:
        db.session.add(r)
    db.session.commit()
    return rides


# ── Weather mock ──────────────────────────────────────────────────────────────

FAKE_WEATHER = {
    'description': 'Partly cloudy',
    'emoji': '⛅',
    'severity': 0,
    'temp_f': 68,
    'wind_mph': 10,
    'precip_prob': 10,
    'aqi': 42,
    'aqi_label': 'Good',
    'warning': False,
    'warning_reasons': [],
}


@pytest.fixture
def mock_weather():
    """
    Patches get_weather_for_rides in all route modules so tests don't
    depend on the Open-Meteo API or network availability.
    """
    def _fake(rides):
        return {r.id: dict(FAKE_WEATHER) for r in rides}

    targets = [
        'app.routes.clubs.get_weather_for_rides',
        'app.routes.main.get_weather_for_rides',
    ]
    patches = [patch(t, side_effect=_fake) for t in targets]
    mocks = [p.start() for p in patches]
    yield mocks
    for p in patches:
        p.stop()


# ── Auth helpers ──────────────────────────────────────────────────────────────

def login(client, email='rider@test.com', password='password123'):
    return client.post('/auth/login', data={
        'email': email, 'password': password,
    }, follow_redirects=True)


def logout(client):
    return client.post('/auth/logout', follow_redirects=True)
