"""Tests for GPX route export endpoint."""
import pytest
from unittest.mock import patch, MagicMock
from datetime import date, time, timedelta

from app.models import Ride
from app.extensions import db


def _make_ride(db, club, route_url=None):
    today = date.today()
    ride = Ride(
        club_id=club.id,
        title='GPX Test Ride',
        date=today + timedelta(days=3),
        time=time(17, 0),
        meeting_location='Test Location',
        distance_miles=30.0,
        pace_category='B',
        route_url=route_url,
    )
    db.session.add(ride)
    db.session.commit()
    return ride


SAMPLE_GPX = b"""<?xml version="1.0"?>
<gpx version="1.1" creator="RideWithGPS">
  <trk><name>Test Route</name><trkseg>
    <trkpt lat="38.95" lon="-77.35"><ele>100</ele></trkpt>
  </trkseg></trk>
</gpx>"""


def test_gpx_no_route_returns_404(client, sample_club):
    """Ride with no route URL returns 404."""
    ride = _make_ride(db, sample_club, route_url=None)
    resp = client.get(f'/clubs/{sample_club.slug}/rides/{ride.id}/gpx')
    assert resp.status_code == 404


def test_gpx_non_rwgps_url_returns_404(client, sample_club):
    """Ride with a non-RideWithGPS URL returns 404 (no route ID to proxy)."""
    ride = _make_ride(db, sample_club, route_url='https://www.strava.com/routes/12345')
    resp = client.get(f'/clubs/{sample_club.slug}/rides/{ride.id}/gpx')
    assert resp.status_code == 404


def test_gpx_rwgps_proxied(client, sample_club):
    """Ride with RideWithGPS URL proxies the GPX file."""
    ride = _make_ride(db, sample_club, route_url='https://ridewithgps.com/routes/98765')

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = SAMPLE_GPX

    with patch('app.routes.clubs.http_requests.get', return_value=mock_resp) as mock_get:
        resp = client.get(f'/clubs/{sample_club.slug}/rides/{ride.id}/gpx')

    assert resp.status_code == 200
    assert resp.content_type.startswith('application/gpx+xml')
    assert b'<gpx' in resp.data
    assert 'attachment' in resp.headers['Content-Disposition']
    assert '.gpx' in resp.headers['Content-Disposition']
    # Verify it called the correct RideWithGPS URL
    mock_get.assert_called_once()
    call_url = mock_get.call_args[0][0]
    assert '98765' in call_url
    assert 'ridewithgps.com' in call_url


def test_gpx_upstream_not_found(client, sample_club):
    """Returns 404 when RideWithGPS returns non-200."""
    ride = _make_ride(db, sample_club, route_url='https://ridewithgps.com/routes/99999')

    mock_resp = MagicMock()
    mock_resp.status_code = 404

    with patch('app.routes.clubs.http_requests.get', return_value=mock_resp):
        resp = client.get(f'/clubs/{sample_club.slug}/rides/{ride.id}/gpx')

    assert resp.status_code == 404


def test_gpx_upstream_timeout(client, sample_club):
    """Returns 503 when RideWithGPS request times out."""
    import requests as real_requests
    ride = _make_ride(db, sample_club, route_url='https://ridewithgps.com/routes/11111')

    with patch('app.routes.clubs.http_requests.get',
               side_effect=real_requests.RequestException('timeout')):
        resp = client.get(f'/clubs/{sample_club.slug}/rides/{ride.id}/gpx')

    assert resp.status_code == 503


def test_gpx_filename_derived_from_title(client, sample_club):
    """GPX filename is derived from the ride title."""
    ride = _make_ride(db, sample_club, route_url='https://ridewithgps.com/routes/55555')
    ride.title = 'Tuesday A Ride'
    db.session.commit()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = SAMPLE_GPX

    with patch('app.routes.clubs.http_requests.get', return_value=mock_resp):
        resp = client.get(f'/clubs/{sample_club.slug}/rides/{ride.id}/gpx')

    assert resp.status_code == 200
    cd = resp.headers['Content-Disposition']
    assert 'tuesday' in cd.lower()
    assert 'a-ride' in cd.lower()


def test_gpx_button_shown_on_ride_detail(client, sample_club, regular_user, mock_weather):
    """Download GPX button appears on ride detail for rides with a RideWithGPS route."""
    from tests.conftest import login
    ride = _make_ride(db, sample_club, route_url='https://ridewithgps.com/routes/42')
    login(client)
    resp = client.get(f'/clubs/{sample_club.slug}/rides/{ride.id}')
    assert resp.status_code == 200
    assert b'Download GPX' in resp.data


def test_gpx_button_hidden_without_route(client, sample_club, regular_user, mock_weather):
    """Download GPX button is absent when ride has no route URL."""
    from tests.conftest import login
    ride = _make_ride(db, sample_club, route_url=None)
    login(client)
    resp = client.get(f'/clubs/{sample_club.slug}/rides/{ride.id}')
    assert resp.status_code == 200
    assert b'Download GPX' not in resp.data
