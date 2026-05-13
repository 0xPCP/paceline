"""Tests for the Leaflet club map page and /api/clubs/map-data endpoint."""
import json
import pytest
from datetime import date, time, timedelta
from tests.conftest import login


def test_map_page_renders(client, sample_club):
    resp = client.get('/clubs/map/')
    assert resp.status_code == 200
    assert b'leaflet' in resp.data.lower()
    # Club data is now server-side embedded JSON, not a client-side fetch
    assert sample_club.slug.encode() in resp.data


def test_map_page_embeds_club_coords(client, sample_club):
    """Club lat/lng is embedded in the page as JSON when the club is geocoded."""
    resp = client.get('/clubs/map/')
    assert resp.status_code == 200
    assert str(sample_club.lat).encode() in resp.data
    assert str(sample_club.lng).encode() in resp.data


def test_map_page_excludes_ungeocoded_clubs(client, sample_club):
    """A club without lat/lng is not embedded in the page data."""
    sample_club.lat = None
    sample_club.lng = None
    from app.extensions import db
    db.session.commit()

    resp = client.get('/clubs/map/')
    assert resp.status_code == 200
    assert sample_club.slug.encode() not in resp.data


def test_map_data_no_coords(client, sample_club):
    """Club without lat/lng is excluded from map data."""
    sample_club.lat = None
    sample_club.lng = None
    from app.extensions import db
    db.session.commit()

    resp = client.get('/api/clubs/map-data')
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, list)
    assert all(c['id'] != sample_club.id for c in data)


def test_map_data_with_coords(client, sample_club):
    """Club with lat/lng appears in map data with correct shape."""
    resp = client.get('/api/clubs/map-data')
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data) == 1
    club_data = data[0]
    assert club_data['id'] == sample_club.id
    assert club_data['slug'] == sample_club.slug
    assert abs(club_data['lat'] - sample_club.lat) < 0.001
    assert abs(club_data['lng'] - sample_club.lng) < 0.001
    assert 'members' in club_data
    assert 'upcoming' in club_data
    assert 'url' in club_data
    assert club_data['is_member'] is False


def test_map_data_member_flag(client, app, sample_club, regular_user):
    """is_member flag is True for clubs the logged-in user has joined."""
    from app.models import ClubMembership
    from app.extensions import db
    db.session.add(ClubMembership(user_id=regular_user.id, club_id=sample_club.id))
    db.session.commit()

    login(client)
    resp = client.get('/api/clubs/map-data')
    data = resp.get_json()
    assert data[0]['is_member'] is True


def test_map_data_inactive_club_excluded(client, sample_club):
    """Inactive clubs are not included in map data."""
    sample_club.is_active = False
    from app.extensions import db
    db.session.commit()

    resp = client.get('/api/clubs/map-data')
    data = resp.get_json()
    assert all(c['id'] != sample_club.id for c in data)


def test_map_data_upcoming_count(client, sample_club, sample_rides):
    """upcoming count reflects non-cancelled future rides for the club."""
    resp = client.get('/api/clubs/map-data')
    data = resp.get_json()
    assert len(data) == 1
    # sample_rides has 2 non-cancelled future rides
    assert data[0]['upcoming'] == 2


# ── Rides-this-week layer ─────────────────────────────────────────────────────

def _make_club_ride(db, club, days_ahead=2, cancelled=False, title='Test Ride'):
    """Create a club ride N days from today."""
    from app.models import Ride
    ride = Ride(
        club_id=club.id,
        title=title,
        date=date.today() + timedelta(days=days_ahead),
        time=time(7, 0),
        meeting_location='Secret Parking Lot',
        distance_miles=30.0,
        pace_category='B',
        ride_type='road',
        is_cancelled=cancelled,
    )
    db.session.add(ride)
    db.session.commit()
    return ride


def test_map_rides_hidden_from_anonymous(client, db, sample_club):
    """Unauthenticated visitors get an empty rides array."""
    _make_club_ride(db, sample_club)
    resp = client.get('/clubs/map/')
    assert resp.status_code == 200
    # The rides data attribute should be an empty JSON array
    assert b'data-rides="[]"' in resp.data


def test_map_rides_visible_for_authenticated(client, db, sample_club, regular_user):
    """Logged-in users see upcoming club rides embedded in the map page."""
    ride = _make_club_ride(db, sample_club, title='Morning B Ride')
    login(client)
    resp = client.get('/clubs/map/')
    assert resp.status_code == 200
    assert b'Morning B Ride' in resp.data


def test_map_rides_excludes_personal_rides(client, db, sample_club, regular_user):
    """User-owned (non-club) rides are not included in the rides layer."""
    from app.models import Ride
    personal = Ride(
        owner_id=regular_user.id,
        title='My Personal Ride',
        date=date.today() + timedelta(days=1),
        time=time(8, 0),
        meeting_location='My House',
        distance_miles=20.0,
        pace_category='B',
        ride_type='road',
    )
    db.session.add(personal)
    db.session.commit()
    login(client)
    resp = client.get('/clubs/map/')
    assert resp.status_code == 200
    assert b'My Personal Ride' not in resp.data


def test_map_rides_excludes_cancelled(client, db, sample_club, regular_user):
    """Cancelled club rides are not shown."""
    _make_club_ride(db, sample_club, title='Cancelled Ride', cancelled=True)
    login(client)
    resp = client.get('/clubs/map/')
    assert resp.status_code == 200
    assert b'Cancelled Ride' not in resp.data


def test_map_rides_excludes_past_rides(client, db, sample_club, regular_user):
    """Rides that already happened are not shown."""
    _make_club_ride(db, sample_club, days_ahead=-1, title='Yesterday Ride')
    login(client)
    resp = client.get('/clubs/map/')
    assert resp.status_code == 200
    assert b'Yesterday Ride' not in resp.data


def test_map_rides_excludes_beyond_week(client, db, sample_club, regular_user):
    """Rides more than 7 days out are not shown."""
    _make_club_ride(db, sample_club, days_ahead=8, title='Future Ride')
    login(client)
    resp = client.get('/clubs/map/')
    assert resp.status_code == 200
    assert b'Future Ride' not in resp.data


def test_map_rides_excludes_ungeocoded_club(client, db, sample_club, regular_user):
    """Rides whose club has no lat/lng are omitted (no map pin possible)."""
    sample_club.lat = None
    sample_club.lng = None
    db.session.commit()
    _make_club_ride(db, sample_club, title='No Coords Ride')
    login(client)
    resp = client.get('/clubs/map/')
    assert resp.status_code == 200
    assert b'No Coords Ride' not in resp.data


def test_map_rides_meeting_location_not_exposed(client, db, sample_club, regular_user):
    """The specific meeting address is never embedded in the page data."""
    _make_club_ride(db, sample_club)  # meeting_location='Secret Parking Lot'
    login(client)
    resp = client.get('/clubs/map/')
    assert resp.status_code == 200
    assert b'Secret Parking Lot' not in resp.data


def test_map_rides_sign_in_prompt_for_anonymous(client, db, sample_club):
    """Anonymous visitors see a sign-in link instead of a rides toggle button."""
    resp = client.get('/clubs/map/')
    assert resp.status_code == 200
    assert b'auth/login' in resp.data
    assert b'Rides This Week' in resp.data


def test_map_header_controls_use_visible_light_background_buttons(client, sample_club):
    """Map header controls sit on a light header; avoid white outline buttons."""
    resp = client.get('/clubs/map/')
    assert resp.status_code == 200
    assert b'id="map-controls"' in resp.data
    assert b'btn-outline-light' not in resp.data
    assert resp.data.count(b'btn-map-secondary') >= 2


def test_authenticated_map_rides_toggle_uses_visible_button(client, sample_club, regular_user):
    login(client)
    resp = client.get('/clubs/map/')
    assert resp.status_code == 200
    assert b'id="layer-rides" class="btn btn-map-secondary"' in resp.data
    assert b'btn-outline-light' not in resp.data
