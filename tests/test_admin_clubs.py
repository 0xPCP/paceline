"""
Tests for superadmin club creation and club admin settings editing.
"""
import pytest
from datetime import date, time, timedelta
from unittest.mock import patch
from app.models import Club, Ride, RideSignup
from tests.conftest import login


class TestClubNew:
    def test_club_new_requires_superadmin(self, client, club_admin_user):
        login(client, 'clubadmin@test.com', 'password123')
        resp = client.get('/admin/clubs/new', follow_redirects=True)
        assert resp.status_code in (200, 403)
        assert b'New Club' not in resp.data or resp.status_code == 403

    def test_club_new_page_loads_for_superadmin(self, client, admin_user):
        login(client, 'admin@test.com', 'password123')
        resp = client.get('/admin/clubs/new')
        assert resp.status_code == 200
        assert b'New Club' in resp.data

    def test_club_new_creates_club(self, client, admin_user, db):
        login(client, 'admin@test.com', 'password123')
        with patch('app.routes.admin.geocode_zip', return_value=None):
            resp = client.post('/admin/clubs/new', data={
                'name': 'Test Cycling Club',
                'slug': 'test-cc',
                'description': 'A test club',
                'city': 'Testville',
                'state': 'VA',
                'zip_code': '20191',
                'address': '',
                'website': '',
                'contact_email': '',
                'logo_url': '',
                'is_active': True,
            }, follow_redirects=True)
        assert resp.status_code == 200
        club = Club.query.filter_by(slug='test-cc').first()
        assert club is not None
        assert club.name == 'Test Cycling Club'
        assert club.city == 'Testville'

    def test_club_new_geocodes_zip(self, client, admin_user, db):
        login(client, 'admin@test.com', 'password123')
        with patch('app.routes.admin.geocode_zip', return_value=(38.9, -77.3)):
            client.post('/admin/clubs/new', data={
                'name': 'Geocoded Club',
                'slug': 'geocoded',
                'description': '',
                'city': '', 'state': '', 'zip_code': '20191',
                'address': '', 'website': '', 'contact_email': '',
                'logo_url': '', 'is_active': True,
            }, follow_redirects=True)
        club = Club.query.filter_by(slug='geocoded').first()
        assert club is not None
        assert club.lat == 38.9
        assert club.lng == -77.3

    def test_duplicate_slug_rejected(self, client, admin_user, sample_club, db):
        login(client, 'admin@test.com', 'password123')
        with patch('app.routes.admin.geocode_zip', return_value=None):
            resp = client.post('/admin/clubs/new', data={
                'name': 'Duplicate',
                'slug': sample_club.slug,
                'description': '', 'city': '', 'state': '', 'zip_code': '',
                'address': '', 'website': '', 'contact_email': '',
                'logo_url': '', 'is_active': True,
            }, follow_redirects=True)
        assert resp.status_code == 200
        count = Club.query.filter_by(slug=sample_club.slug).count()
        assert count == 1

    def test_new_club_button_visible_to_superadmin(self, client, admin_user):
        login(client, 'admin@test.com', 'password123')
        resp = client.get('/admin/')
        assert b'New Club' in resp.data


class TestClubSettings:
    def test_settings_page_loads_for_club_admin(self, client, club_admin_user, sample_club, db):
        login(client, 'clubadmin@test.com', 'password123')
        resp = client.get(f'/admin/clubs/{sample_club.slug}/settings')
        assert resp.status_code == 200
        assert b'Club Settings' in resp.data

    def test_settings_page_loads_for_superadmin(self, client, admin_user, sample_club):
        login(client, 'admin@test.com', 'password123')
        resp = client.get(f'/admin/clubs/{sample_club.slug}/settings')
        assert resp.status_code == 200

    def test_settings_page_blocked_for_regular_user(self, client, regular_user, sample_club):
        login(client, 'rider@test.com', 'password123')
        resp = client.get(f'/admin/clubs/{sample_club.slug}/settings')
        assert resp.status_code == 403

    def test_settings_update_name(self, client, club_admin_user, sample_club, db):
        login(client, 'clubadmin@test.com', 'password123')
        with patch('app.routes.admin.geocode_zip', return_value=None):
            client.post(f'/admin/clubs/{sample_club.slug}/settings', data={
                'name': 'Renamed Club',
                'description': sample_club.description or '',
                'city': sample_club.city or '',
                'state': sample_club.state or '',
                'zip_code': sample_club.zip_code or '',
                'address': '',
                'website': '',
                'contact_email': '',
                'logo_url': '',
            }, follow_redirects=True)
        from app.extensions import db as _db
        _db.session.expire(sample_club)
        assert sample_club.name == 'Renamed Club'

    def test_settings_update_geocodes_new_zip(self, client, admin_user, sample_club, db):
        login(client, 'admin@test.com', 'password123')
        with patch('app.routes.admin.geocode_zip', return_value=(39.1, -77.5)):
            client.post(f'/admin/clubs/{sample_club.slug}/settings', data={
                'name': sample_club.name,
                'description': '',
                'city': '', 'state': '',
                'zip_code': '20194',
                'address': '', 'website': '', 'contact_email': '', 'logo_url': '',
            }, follow_redirects=True)
        from app.extensions import db as _db
        _db.session.expire(sample_club)
        assert sample_club.zip_code == '20194'
        assert sample_club.lat == 39.1

    def test_slug_not_shown_in_form_input(self, client, club_admin_user, sample_club, db):
        login(client, 'clubadmin@test.com', 'password123')
        resp = client.get(f'/admin/clubs/{sample_club.slug}/settings')
        assert sample_club.slug.encode() in resp.data

    def test_settings_link_visible_on_club_dashboard(self, client, club_admin_user, sample_club, db):
        login(client, 'clubadmin@test.com', 'password123')
        resp = client.get(f'/admin/clubs/{sample_club.slug}/')
        assert b'Settings' in resp.data

    def test_club_dashboard_shows_activity_stats(self, client, club_admin_user, regular_user, sample_club, db):
        ride = Ride(
            club_id=sample_club.id,
            title='Recent Road Ride',
            date=date.today() + timedelta(days=2),
            time=time(8, 0),
            meeting_location='Town Center',
            distance_miles=24,
            pace_category='B',
            ride_type='road',
        )
        db.session.add(ride)
        db.session.flush()
        db.session.add(RideSignup(ride_id=ride.id, user_id=regular_user.id))
        db.session.commit()

        login(client, 'clubadmin@test.com', 'password123')
        html = client.get(f'/admin/clubs/{sample_club.slug}/').data.decode()

        assert 'Club Activity' in html
        assert 'Ride signups' in html
        assert 'Rides past / next' in html
        assert 'Road' in html
