"""
Tests for virtual ride creation, discovery, and display.

Virtual rides:
- can be created by club admins (marked is_virtual=True)
- can be created by users from /my-rides/create
- appear on /virtual/ discovery page
- excluded from map data (club map only shows clubs, not rides)
- meeting_location is optional when is_virtual=True
- meeting_location is required when is_virtual=False
"""
import pytest
from datetime import date, time, timedelta
from unittest.mock import patch
from app.models import Club, Ride, RideSignup
from app.extensions import db
from tests.conftest import login


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def virtual_club_ride(db, sample_club, regular_user):
    ride = Ride(
        club_id=sample_club.id,
        title='Zwift Wednesday',
        date=date.today() + timedelta(days=3),
        time=time(19, 0),
        distance_miles=20.0,
        pace_category='B',
        ride_type='training',
        is_virtual=True,
        virtual_platform='zwift',
        virtual_platform_url='https://www.zwift.com/events/view/12345',
        created_by=regular_user.id,
    )
    db.session.add(ride)
    db.session.commit()
    return ride


@pytest.fixture
def virtual_user_ride(db, regular_user):
    ride = Ride(
        owner_id=regular_user.id,
        club_id=None,
        is_private=False,
        title='Rouvy Friday',
        date=date.today() + timedelta(days=5),
        time=time(18, 0),
        distance_miles=15.0,
        pace_category='C',
        ride_type='social',
        is_virtual=True,
        virtual_platform='rouvy',
        virtual_platform_url='https://rouvy.com/virtual-routes/example',
        ride_leader='rider',
        created_by=regular_user.id,
    )
    db.session.add(ride)
    db.session.commit()
    return ride


@pytest.fixture
def physical_ride(db, sample_club, regular_user):
    ride = Ride(
        club_id=sample_club.id,
        title='Saturday Road Ride',
        date=date.today() + timedelta(days=2),
        time=time(8, 0),
        meeting_location='Lake Newport parking lot',
        distance_miles=30.0,
        pace_category='B',
        ride_type='road',
        is_virtual=False,
        created_by=regular_user.id,
    )
    db.session.add(ride)
    db.session.commit()
    return ride


# ── Discovery page ────────────────────────────────────────────────────────────

class TestVirtualDiscovery:
    def test_page_returns_200(self, client):
        resp = client.get('/virtual/')
        assert resp.status_code == 200

    def test_shows_virtual_club_ride(self, client, virtual_club_ride):
        resp = client.get('/virtual/')
        assert b'Zwift Wednesday' in resp.data

    def test_shows_virtual_user_ride(self, client, virtual_user_ride):
        resp = client.get('/virtual/')
        assert b'Rouvy Friday' in resp.data

    def test_physical_rides_not_shown(self, client, physical_ride):
        resp = client.get('/virtual/')
        assert b'Saturday Road Ride' not in resp.data

    def test_platform_filter_zwift(self, client, virtual_club_ride, virtual_user_ride):
        resp = client.get('/virtual/?platform=zwift')
        html = resp.data.decode()
        assert 'Zwift Wednesday' in html
        assert 'Rouvy Friday' not in html

    def test_platform_filter_rouvy(self, client, virtual_club_ride, virtual_user_ride):
        resp = client.get('/virtual/?platform=rouvy')
        html = resp.data.decode()
        assert 'Rouvy Friday' in html
        assert 'Zwift Wednesday' not in html

    def test_pace_filter(self, client, virtual_club_ride, virtual_user_ride):
        resp = client.get('/virtual/?pace=B')
        html = resp.data.decode()
        assert 'Zwift Wednesday' in html
        assert 'Rouvy Friday' not in html

    def test_private_user_rides_excluded(self, client, db, regular_user):
        private_virtual = Ride(
            owner_id=regular_user.id,
            is_private=True,
            title='Private Virtual Ride',
            date=date.today() + timedelta(days=2),
            time=time(18, 0),
            distance_miles=10.0,
            pace_category='B',
            is_virtual=True,
            virtual_platform='zwift',
        )
        db.session.add(private_virtual)
        db.session.commit()
        resp = client.get('/virtual/')
        assert b'Private Virtual Ride' not in resp.data

    def test_cancelled_rides_excluded(self, client, db, virtual_club_ride):
        virtual_club_ride.is_cancelled = True
        db.session.commit()
        resp = client.get('/virtual/')
        assert b'Zwift Wednesday' not in resp.data

    def test_past_rides_excluded(self, client, db, regular_user):
        past = Ride(
            owner_id=regular_user.id,
            is_private=False,
            title='Past Virtual Ride',
            date=date.today() - timedelta(days=1),
            time=time(18, 0),
            distance_miles=10.0,
            pace_category='B',
            is_virtual=True,
        )
        db.session.add(past)
        db.session.commit()
        resp = client.get('/virtual/')
        assert b'Past Virtual Ride' not in resp.data

    def test_shows_join_link(self, client, virtual_club_ride):
        resp = client.get('/virtual/')
        assert b'Join on' in resp.data

    def test_shows_virtual_badge(self, client, virtual_club_ride):
        resp = client.get('/virtual/')
        assert b'Virtual' in resp.data


# ── Club ride detail: virtual display ─────────────────────────────────────────

class TestVirtualRideDetail:
    def test_shows_virtual_badge(self, client, sample_club, virtual_club_ride, mock_weather):
        resp = client.get(f'/clubs/test-club/rides/{virtual_club_ride.id}')
        assert b'Virtual' in resp.data

    def test_shows_join_link(self, client, sample_club, virtual_club_ride, mock_weather):
        resp = client.get(f'/clubs/test-club/rides/{virtual_club_ride.id}')
        assert b'Join on Platform' in resp.data
        assert b'zwift.com' in resp.data

    def test_no_meeting_location_shown_for_virtual(self, client, sample_club, virtual_club_ride, mock_weather):
        resp = client.get(f'/clubs/test-club/rides/{virtual_club_ride.id}')
        html = resp.data.decode()
        assert 'Meeting Location' not in html

    def test_physical_ride_still_shows_location(self, client, sample_club, physical_ride, mock_weather):
        resp = client.get(f'/clubs/test-club/rides/{physical_ride.id}')
        assert b'Lake Newport parking lot' in resp.data


# ── User ride: virtual fields in form and detail ──────────────────────────────

class TestUserVirtualRide:
    def test_create_virtual_ride(self, client, regular_user, db):
        login(client)
        resp = client.post('/my-rides/create', data={
            'title': 'My Zwift Ride',
            'date': (date.today() + timedelta(days=7)).isoformat(),
            'time': '18:00',
            'distance_miles': '20.0',
            'pace_category': 'B',
            'ride_type': 'training',
            'is_virtual': 'y',
            'virtual_platform': 'zwift',
            'virtual_platform_url': 'https://www.zwift.com/events/view/99999',
            'is_private': '',
        }, follow_redirects=True)
        assert resp.status_code == 200
        ride = Ride.query.filter_by(owner_id=regular_user.id, title='My Zwift Ride').first()
        assert ride is not None
        assert ride.is_virtual is True
        assert ride.virtual_platform == 'zwift'
        assert ride.meeting_location is None

    def test_create_physical_ride_without_location_fails(self, client, regular_user, db):
        login(client)
        resp = client.post('/my-rides/create', data={
            'title': 'My Road Ride',
            'date': (date.today() + timedelta(days=7)).isoformat(),
            'time': '08:00',
            'distance_miles': '30.0',
            'pace_category': 'B',
            'ride_type': 'road',
            'is_virtual': '',
        }, follow_redirects=True)
        assert b'Meeting location is required' in resp.data
        assert Ride.query.filter_by(title='My Road Ride').first() is None

    def test_virtual_user_ride_detail_shows_platform(self, client, virtual_user_ride, regular_user):
        resp = client.get(f'/my-rides/{virtual_user_ride.id}')
        html = resp.data.decode()
        assert 'Rouvy' in html
        assert 'Virtual' in html

    def test_virtual_user_ride_shows_join_button(self, client, virtual_user_ride):
        resp = client.get(f'/my-rides/{virtual_user_ride.id}')
        assert b'Join on Platform' in resp.data

    def test_virtual_user_ride_no_meeting_location_label(self, client, virtual_user_ride):
        resp = client.get(f'/my-rides/{virtual_user_ride.id}')
        assert b'Meeting Location' not in resp.data

    def test_virtual_user_ride_no_garmin_section(self, client, virtual_user_ride):
        resp = client.get(f'/my-rides/{virtual_user_ride.id}')
        assert b'Garmin GroupRide' not in resp.data

    def test_garmin_code_endpoint_returns_404_for_virtual_user_ride(
            self, client, virtual_user_ride, regular_user):
        login(client)
        resp = client.post(f'/my-rides/{virtual_user_ride.id}/groupride-code',
                           data={'garmin_groupride_code': '123456'})
        assert resp.status_code == 404


class TestVirtualClubRideNoGarmin:
    def test_virtual_club_ride_no_garmin_section(self, client, sample_club, virtual_club_ride, mock_weather):
        resp = client.get(f'/clubs/test-club/rides/{virtual_club_ride.id}')
        assert b'Garmin GroupRide' not in resp.data

    def test_garmin_code_endpoint_returns_404_for_virtual_club_ride(
            self, client, sample_club, virtual_club_ride, regular_user, mock_weather):
        login(client)
        resp = client.post(
            f'/clubs/test-club/rides/{virtual_club_ride.id}/groupride-code',
            data={'garmin_groupride_code': '123456'})
        assert resp.status_code == 404
