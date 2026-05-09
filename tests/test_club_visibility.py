"""
Tests for club hide/unhide feature.

Hidden clubs are excluded from all public listings (directory, map, discover,
API) and return 404 on their public URL. Club admins control visibility via
the settings toggle.
"""
import pytest
from app.models import Club, ClubAdmin, ClubMembership
from app.extensions import db
from tests.conftest import login


@pytest.fixture
def hidden_club(db):
    club = Club(
        slug='hidden-club',
        name='Hidden Cycling Club',
        city='Reston', state='VA', zip_code='20191',
        lat=38.9376, lng=-77.3476,
        is_hidden=True,
    )
    db.session.add(club)
    db.session.commit()
    return club


@pytest.fixture
def hidden_club_admin(db, hidden_club):
    from app.extensions import bcrypt
    user = __import__('app.models', fromlist=['User']).User(
        username='hiddenclubboss',
        email='hiddenclubboss@test.com',
        password_hash=bcrypt.generate_password_hash('password123').decode(),
        is_admin=False,
    )
    db.session.add(user)
    db.session.commit()
    db.session.add(ClubAdmin(user_id=user.id, club_id=hidden_club.id, role='admin'))
    db.session.add(ClubMembership(user_id=user.id, club_id=hidden_club.id, status='active'))
    db.session.commit()
    return user


# ── Directory ─────────────────────────────────────────────────────────────────

def test_hidden_club_absent_from_directory(client, hidden_club):
    r = client.get('/clubs/')
    assert r.status_code == 200
    assert b'Hidden Cycling Club' not in r.data


def test_visible_club_in_directory(client, sample_club):
    r = client.get('/clubs/')
    assert r.status_code == 200
    assert b'Test Cycling Club' in r.data


# ── Public club page ───────────────────────────────────────────────────────────

def test_hidden_club_page_returns_404(client, hidden_club):
    r = client.get('/clubs/hidden-club/')
    assert r.status_code == 404


def test_visible_club_page_accessible(client, sample_club):
    r = client.get('/clubs/test-club/')
    assert r.status_code == 200


# ── Map page ──────────────────────────────────────────────────────────────────

def test_hidden_club_absent_from_map(client, hidden_club):
    r = client.get('/clubs/map/')
    assert r.status_code == 200
    assert b'Hidden Cycling Club' not in r.data


# ── Map API ───────────────────────────────────────────────────────────────────

def test_hidden_club_absent_from_api(client, hidden_club):
    r = client.get('/api/clubs/map-data')
    assert r.status_code == 200
    data = r.get_json()
    names = [f['name'] for f in data]
    assert 'Hidden Cycling Club' not in names


def test_visible_geocoded_club_in_api(client, sample_club):
    r = client.get('/api/clubs/map-data')
    assert r.status_code == 200
    data = r.get_json()
    names = [f['name'] for f in data]
    assert 'Test Cycling Club' in names


# ── Discover page ─────────────────────────────────────────────────────────────

def test_hidden_club_rides_absent_from_discover(client, db, hidden_club):
    from datetime import date, time, timedelta
    from app.models import Ride
    ride = Ride(
        club_id=hidden_club.id,
        title='Hidden Club Ride',
        date=date.today() + timedelta(days=2),
        time=time(8, 0),
        meeting_location='Somewhere',
        distance_miles=20.0,
        pace_category='B',
    )
    db.session.add(ride)
    db.session.commit()
    r = client.get('/discover/')
    assert r.status_code == 200
    assert b'Hidden Club Ride' not in r.data


# ── New club defaults to hidden ───────────────────────────────────────────────

def test_new_club_defaults_to_hidden(db):
    club = Club(slug='brand-new', name='Brand New Club')
    db.session.add(club)
    db.session.commit()
    assert club.is_hidden is True


# ── Admin settings toggle ─────────────────────────────────────────────────────

def test_club_admin_can_unhide_club(client, db, hidden_club, hidden_club_admin):
    login(client, 'hiddenclubboss@test.com', 'password123')
    r = client.post(
        f'/admin/clubs/hidden-club/settings',
        data={
            'name': hidden_club.name,
            'join_approval': 'auto',
            'is_hidden': '',          # unchecked = False in BooleanField
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    db.session.refresh(hidden_club)
    assert hidden_club.is_hidden is False


def test_club_admin_can_hide_visible_club(client, db, sample_club, club_admin_user):
    login(client, 'clubadmin@test.com', 'password123')
    r = client.post(
        f'/admin/clubs/test-club/settings',
        data={
            'name': sample_club.name,
            'join_approval': 'auto',
            'is_hidden': 'y',         # checked = True
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    db.session.refresh(sample_club)
    assert sample_club.is_hidden is True
