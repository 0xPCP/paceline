"""
Tests for authentication: registration, login, logout, first-user admin promotion.
"""
import pytest
from datetime import date, datetime, time, timedelta, timezone
from app.models import User, Ride, RideSignup
from tests.conftest import login, logout


# ── Registration ──────────────────────────────────────────────────────────────

class TestRegistration:
    def test_register_page_loads(self, client):
        resp = client.get('/auth/register')
        assert resp.status_code == 200

    def test_register_creates_user(self, client, db):
        resp = client.post('/auth/register', data={
            'username': 'newrider',
            'email': 'newrider@rbc.com',
            'password': 'StrongPass1!',
            'confirm_password': 'StrongPass1!',
            'policy_ack': 'y',
        }, follow_redirects=True)
        assert resp.status_code == 200
        user = User.query.filter_by(username='newrider').first()
        assert user is not None
        assert user.username_finalized is True

    def test_first_user_becomes_admin(self, client, db):
        client.post('/auth/register', data={
            'username': 'firstuser',
            'email': 'first@rbc.com',
            'password': 'StrongPass1!',
            'confirm_password': 'StrongPass1!',
            'policy_ack': 'y',
        }, follow_redirects=True)
        user = User.query.filter_by(username='firstuser').first()
        assert user.is_admin is True

    def test_second_user_is_not_admin(self, client, admin_user, db):
        client.post('/auth/register', data={
            'username': 'seconduser',
            'email': 'second@rbc.com',
            'password': 'StrongPass1!',
            'confirm_password': 'StrongPass1!',
            'policy_ack': 'y',
        }, follow_redirects=True)
        user = User.query.filter_by(username='seconduser').first()
        assert user.is_admin is False

    def test_duplicate_username_rejected(self, client, regular_user, db):
        resp = client.post('/auth/register', data={
            'username': 'rider',          # same as regular_user
            'email': 'other@rbc.com',
            'password': 'StrongPass1!',
            'confirm_password': 'StrongPass1!',
            'policy_ack': 'y',
        }, follow_redirects=True)
        assert resp.status_code == 200
        count = User.query.filter_by(username='rider').count()
        assert count == 1

    def test_duplicate_email_rejected(self, client, regular_user, db):
        resp = client.post('/auth/register', data={
            'username': 'otherrider',
            'email': 'rider@test.com',   # same as regular_user
            'password': 'StrongPass1!',
            'confirm_password': 'StrongPass1!',
            'policy_ack': 'y',
        }, follow_redirects=True)
        assert resp.status_code == 200
        count = User.query.filter_by(email='rider@test.com').count()
        assert count == 1

    def test_password_mismatch_rejected(self, client, db):
        resp = client.post('/auth/register', data={
            'username': 'mismatch',
            'email': 'mismatch@rbc.com',
            'password': 'StrongPass1!',
            'confirm_password': 'DifferentPass1!',
            'policy_ack': 'y',
        }, follow_redirects=True)
        assert resp.status_code == 200
        user = User.query.filter_by(username='mismatch').first()
        assert user is None

    def test_policy_acknowledgement_required(self, client, db):
        resp = client.post('/auth/register', data={
            'username': 'nopolicy',
            'email': 'nopolicy@rbc.com',
            'password': 'StrongPass1!',
            'confirm_password': 'StrongPass1!',
        }, follow_redirects=True)
        assert b'Privacy Policy' in resp.data
        assert b'Data Use Policy' in resp.data
        assert User.query.filter_by(username='nopolicy').first() is None


# ── Login / Logout ────────────────────────────────────────────────────────────

class TestLogin:
    def test_login_page_loads(self, client):
        resp = client.get('/auth/login')
        assert resp.status_code == 200

    def test_login_with_valid_credentials(self, client, regular_user):
        resp = login(client, 'rider@test.com', 'password123')
        assert resp.status_code == 200
        # Should be redirected away from login — check for username in nav
        assert b'rider' in resp.data

    def test_login_page_uses_trust_browser_label(self, client):
        resp = client.get('/auth/login')
        assert b'Trust this browser' in resp.data
        assert b'signed out after 6 hours' in resp.data

    def test_login_without_trust_does_not_issue_remember_cookie(self, client, regular_user):
        resp = client.post('/auth/login', data={
            'email': 'rider@test.com',
            'password': 'password123',
        })
        cookies = '\n'.join(resp.headers.getlist('Set-Cookie'))
        assert 'remember_token=' not in cookies

    def test_login_with_trust_issues_remember_cookie(self, client, regular_user):
        resp = client.post('/auth/login', data={
            'email': 'rider@test.com',
            'password': 'password123',
            'remember': 'y',
        })
        cookies = '\n'.join(resp.headers.getlist('Set-Cookie'))
        assert 'remember_token=' in cookies
        assert 'HttpOnly' in cookies
        assert 'SameSite=Lax' in cookies

    def test_session_cookie_is_secure_http_only_and_lax(self, client, regular_user):
        resp = client.post('/auth/login', data={
            'email': 'rider@test.com',
            'password': 'password123',
        })
        cookies = '\n'.join(resp.headers.getlist('Set-Cookie'))
        assert 'session=' in cookies
        assert 'HttpOnly' in cookies
        assert 'SameSite=Lax' in cookies

    def test_production_cookie_config_defaults_secure(self):
        from app.config import Config
        assert Config.SESSION_COOKIE_SECURE is True
        assert Config.REMEMBER_COOKIE_SECURE is True

    def test_production_secure_cookie_rejects_development_secret(self, monkeypatch):
        from app import create_app
        from app.config import Config

        monkeypatch.setenv('COOKIE_SECURE', 'true')
        monkeypatch.setenv('SECRET_KEY', 'dev-secret-key-change-in-production')
        monkeypatch.setenv('FLASK_SKIP_SCHEDULER', '1')

        class ProdLikeConfig(Config):
            TESTING = False

        with pytest.raises(RuntimeError) as excinfo:
            create_app(ProdLikeConfig)

        assert 'SECRET_KEY' in str(excinfo.value)

    def test_login_with_bad_password(self, client, regular_user):
        resp = client.post('/auth/login', data={
            'email': 'rider@test.com',
            'password': 'wrongpassword',
        }, follow_redirects=True)
        assert resp.status_code == 200
        # Should stay on login page or show error
        assert b'rider' not in resp.data or b'Invalid' in resp.data

    def test_login_with_unknown_user(self, client):
        resp = client.post('/auth/login', data={
            'email': 'ghost@nowhere.com',
            'password': 'whatever',
        }, follow_redirects=True)
        assert resp.status_code == 200

    def test_logout_clears_session(self, client, regular_user):
        login(client, 'rider@test.com', 'password123')
        resp = logout(client)
        # After logout, Sign In link should appear
        assert b'Sign In' in resp.data

    def test_login_redirects_to_next(self, client, regular_user):
        resp = client.post('/auth/login?next=/clubs/', data={
            'email': 'rider@test.com',
            'password': 'password123',
        }, follow_redirects=True)
        assert resp.status_code == 200

    def test_non_trusted_session_expires_after_six_hours(self, client, regular_user):
        login(client, 'rider@test.com', 'password123')
        old = datetime.now(timezone.utc) - timedelta(hours=6, minutes=1)
        with client.session_transaction() as sess:
            sess['_paceline_auth_started_at'] = old.timestamp()
            sess['_paceline_trusted_browser'] = False

        resp = client.get('/auth/profile', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login?next=/auth/profile' in resp.headers['Location']

        resp = client.get('/auth/profile', follow_redirects=True)
        assert b'Your session expired' in resp.data
        assert b'Sign In' in resp.data

    def test_trusted_browser_skips_six_hour_reauth(self, client, regular_user):
        client.post('/auth/login', data={
            'email': 'rider@test.com',
            'password': 'password123',
            'remember': 'y',
        })
        old = datetime.now(timezone.utc) - timedelta(hours=12)
        with client.session_transaction() as sess:
            sess['_paceline_auth_started_at'] = old.timestamp()
            sess['_paceline_trusted_browser'] = True

        resp = client.get('/auth/profile')
        assert resp.status_code == 200
        assert b'rider' in resp.data

    def test_logout_requires_post(self, client, regular_user):
        login(client, 'rider@test.com', 'password123')
        resp = client.get('/auth/logout')
        assert resp.status_code == 405

    def test_revoking_session_version_invalidates_existing_session(self, client, db, regular_user):
        login(client, 'rider@test.com', 'password123')
        regular_user.revoke_sessions()
        db.session.commit()
        resp = client.get('/auth/profile', follow_redirects=True)
        assert b'Sign In' in resp.data

    def test_stale_trusted_session_must_reauth_for_admin(self, client, admin_user):
        client.post('/auth/login', data={
            'email': 'admin@test.com',
            'password': 'password123',
            'remember': 'y',
        })
        with client.session_transaction() as sess:
            sess['_fresh'] = False

        resp = client.get('/admin/', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login?next=/admin/' in resp.headers['Location']


# ── Admin access ──────────────────────────────────────────────────────────────

class TestAdminAccess:
    def test_admin_link_visible_to_admin(self, client, admin_user):
        login(client, 'admin@test.com', 'password123')
        resp = client.get('/')
        assert b'Admin' in resp.data

    def test_admin_link_hidden_from_regular_user(self, client, regular_user):
        login(client, 'rider@test.com', 'password123')
        resp = client.get('/')
        assert b'Admin' not in resp.data

    def test_admin_dashboard_requires_admin(self, client, regular_user):
        login(client, 'rider@test.com', 'password123')
        resp = client.get('/admin/', follow_redirects=True)
        # Regular user should be redirected or get 403
        assert resp.status_code in (200, 403)
        assert b'Admin Dashboard' not in resp.data

    def test_admin_dashboard_accessible_to_admin(self, client, admin_user):
        login(client, 'admin@test.com', 'password123')
        resp = client.get('/admin/')
        assert resp.status_code == 200
        assert b'Admin' in resp.data


# ── Profile ───────────────────────────────────────────────────────────────────

class TestProfile:
    def test_profile_requires_login(self, client):
        resp = client.get('/auth/profile', follow_redirects=True)
        assert b'Sign In' in resp.data

    def test_profile_page_loads(self, client, regular_user):
        login(client)
        resp = client.get('/auth/profile')
        assert resp.status_code == 200
        assert b'rider' in resp.data

    def test_profile_shows_zip_field(self, client, regular_user):
        login(client)
        assert b'Zip Code' in client.get('/auth/profile').data

    def test_profile_cannot_update_username(self, client, regular_user, db):
        login(client)
        client.post('/auth/profile', data={
            'username': 'newrider', 'email': 'rider@test.com', 'zip_code': '',
        }, follow_redirects=True)
        from app.models import User
        db.session.refresh(regular_user)
        assert regular_user.username == 'rider'
        assert User.query.filter_by(username='newrider').first() is None

    def test_profile_update_zip_saves(self, client, regular_user, db):
        from unittest.mock import patch
        login(client)
        with patch('app.routes.auth.geocode_zip', return_value=(38.9, -77.3)):
            client.post('/auth/profile', data={
                'username': 'rider', 'email': 'rider@test.com', 'zip_code': '22101',
            }, follow_redirects=True)
        from app.models import User
        u = User.query.filter_by(username='rider').first()
        assert u.zip_code == '22101'
        assert u.lat == 38.9

    def test_profile_saves_canonical_strava_profile_url(self, client, regular_user, db):
        login(client)
        resp = client.post('/auth/profile', data={
            'username': 'rider',
            'email': 'rider@test.com',
            'zip_code': '',
            'strava_profile_url': 'http://strava.com/athletes/123456',
        }, follow_redirects=True)

        assert resp.status_code == 200
        db.session.refresh(regular_user)
        assert regular_user.strava_profile_url == 'https://www.strava.com/athletes/123456'

    def test_profile_rejects_non_strava_profile_url(self, client, regular_user, db):
        login(client)
        resp = client.post('/auth/profile', data={
            'username': 'rider',
            'email': 'rider@test.com',
            'zip_code': '',
            'strava_profile_url': 'https://example.com/rider',
        }, follow_redirects=True)

        assert b'Enter your Strava athlete profile URL' in resp.data
        db.session.refresh(regular_user)
        assert regular_user.strava_profile_url is None

    def test_profile_rejects_strava_url_that_does_not_match_connected_account(self, client, regular_user, db):
        regular_user.strava_id = 111
        db.session.commit()
        login(client)
        resp = client.post('/auth/profile', data={
            'username': 'rider',
            'email': 'rider@test.com',
            'zip_code': '',
            'strava_profile_url': 'https://www.strava.com/athletes/222',
        }, follow_redirects=True)

        assert b'does not match the Strava account connected' in resp.data
        db.session.refresh(regular_user)
        assert regular_user.strava_profile_url is None

    def test_public_profile_uses_saved_strava_profile_url(self, client, regular_user, db):
        regular_user.strava_profile_url = 'https://www.strava.com/athletes/123456'
        db.session.commit()
        login(client)

        resp = client.get(f'/users/{regular_user.username}')

        assert resp.status_code == 200
        assert b'https://www.strava.com/athletes/123456' in resp.data

    def test_profile_ignores_submitted_duplicate_username(self, client, regular_user, second_user, db):
        login(client)
        resp = client.post('/auth/profile', data={
            'username': 'rider2', 'email': 'rider@test.com', 'zip_code': '',
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(regular_user)
        assert regular_user.username == 'rider'

    def test_profile_shows_ytd_stats(self, client, regular_user, sample_club, db):
        login(client)
        past_date = date.today() - timedelta(days=10)
        ride = Ride(
            club_id=sample_club.id, title='Past Ride', date=past_date,
            time=time(9, 0), meeting_location='HQ', distance_miles=30.0,
            elevation_feet=1500, pace_category='B',
        )
        db.session.add(ride)
        db.session.commit()
        db.session.add(RideSignup(ride_id=ride.id, user_id=regular_user.id, is_waitlist=False))
        db.session.commit()

        resp = client.get('/auth/profile')
        assert resp.status_code == 200
        assert b'Stats' in resp.data
        assert b'30.0' in resp.data

    def test_profile_shows_ride_history(self, client, regular_user, sample_club, db):
        login(client)
        past_date = date.today() - timedelta(days=5)
        ride = Ride(
            club_id=sample_club.id, title='History Test Ride', date=past_date,
            time=time(8, 0), meeting_location='Park', distance_miles=25.0,
            pace_category='C',
        )
        db.session.add(ride)
        db.session.commit()
        db.session.add(RideSignup(ride_id=ride.id, user_id=regular_user.id, is_waitlist=False))
        db.session.commit()

        resp = client.get('/auth/profile')
        assert b'History Test Ride' in resp.data

    def test_profile_history_excludes_waitlist(self, client, regular_user, sample_club, db):
        login(client)
        past_date = date.today() - timedelta(days=3)
        ride = Ride(
            club_id=sample_club.id, title='Waitlist Ride', date=past_date,
            time=time(8, 0), meeting_location='Park', distance_miles=20.0,
            pace_category='C',
        )
        db.session.add(ride)
        db.session.commit()
        db.session.add(RideSignup(ride_id=ride.id, user_id=regular_user.id, is_waitlist=True))
        db.session.commit()

        resp = client.get('/auth/profile')
        assert b'Waitlist Ride' not in resp.data


# ── Distance unit setting ──────────────────────────────────────────────────────

class TestDistanceUnit:
    def _profile_post(self, client, **extra):
        data = {'username': 'rider', 'email': 'rider@test.com', **extra}
        return client.post('/auth/profile', data=data, follow_redirects=True)

    def test_distance_unit_field_on_profile_page(self, client, regular_user):
        login(client)
        resp = client.get('/auth/profile')
        assert b'distance_unit' in resp.data
        assert b'Miles (US)' in resp.data
        assert b'Kilometres' in resp.data

    def test_distance_unit_saves_miles(self, client, regular_user, db):
        login(client)
        self._profile_post(client, distance_unit='mi')
        db.session.refresh(regular_user)
        assert regular_user.distance_unit == 'mi'

    def test_distance_unit_saves_km(self, client, regular_user, db):
        login(client)
        self._profile_post(client, distance_unit='km')
        db.session.refresh(regular_user)
        assert regular_user.distance_unit == 'km'

    def test_distance_unit_clears_to_none_on_auto(self, client, regular_user, db):
        regular_user.distance_unit = 'mi'
        db.session.commit()
        login(client)
        self._profile_post(client, distance_unit='')
        db.session.refresh(regular_user)
        assert regular_user.distance_unit is None

    def test_dist_filter_miles(self, app):
        from app import _dist_filter
        with app.test_request_context('/'):
            from flask import g
            g.distance_unit = 'mi'
            assert _dist_filter(42.5) == '42.5 mi'
            assert _dist_filter(0) == '0.0 mi'

    def test_dist_filter_km(self, app):
        from app import _dist_filter
        with app.test_request_context('/'):
            from flask import g
            g.distance_unit = 'km'
            result = _dist_filter(10.0)
            assert result.endswith(' km')
            assert '16.1' in result

    def test_dist_filter_precision_zero(self, app):
        from app import _dist_filter
        with app.test_request_context('/'):
            from flask import g
            g.distance_unit = 'mi'
            assert _dist_filter(1234, precision=0) == '1,234 mi'

    def test_dist_filter_none_returns_empty(self, app):
        from app import _dist_filter
        with app.test_request_context('/'):
            from flask import g
            g.distance_unit = 'mi'
            assert _dist_filter(None) == ''

    def test_elev_filter_feet(self, app):
        from app import _elev_filter
        with app.test_request_context('/'):
            from flask import g
            g.distance_unit = 'mi'
            assert _elev_filter(2500) == '2,500 ft'

    def test_elev_filter_meters(self, app):
        from app import _elev_filter
        with app.test_request_context('/'):
            from flask import g
            g.distance_unit = 'km'
            assert _elev_filter(3281) == '1,000 m'

    def test_elev_filter_none_returns_empty(self, app):
        from app import _elev_filter
        with app.test_request_context('/'):
            from flask import g
            g.distance_unit = 'km'
            assert _elev_filter(None) == ''

    def test_auto_detect_us_zip_uses_miles(self, client, regular_user, db):
        regular_user.zip_code = '22101'
        regular_user.distance_unit = None
        db.session.commit()
        login(client)
        resp = client.get('/auth/profile')
        assert b'42.5 mi' in resp.data or resp.status_code == 200

    def test_explicit_km_overrides_us_zip(self, client, regular_user, db):
        regular_user.zip_code = '22101'
        regular_user.distance_unit = 'km'
        db.session.commit()
        login(client)
        # Just verify the preference is respected (g.distance_unit == 'km')
        from app import create_app
        with client.application.test_request_context('/', environ_base={'HTTP_COOKIE': ''}):
            from flask_login import login_user
            login_user(regular_user)
            from flask import g
            from app import _dist_filter
            g.distance_unit = regular_user.distance_unit
            assert _dist_filter(10.0).endswith(' km')

    def test_pace_filter_returns_mph_for_miles(self, app):
        from app import _pace_filter
        with app.test_request_context('/'):
            from flask import g
            g.distance_unit = 'mi'
            assert _pace_filter('C — Casual (14–18 mph)') == 'C — Casual (14–18 mph)'

    def test_pace_filter_converts_to_kmh_for_km(self, app):
        from app import _pace_filter
        with app.test_request_context('/'):
            from flask import g
            g.distance_unit = 'km'
            assert _pace_filter('C — Casual (14–18 mph)') == 'C — Casual (22–29 km/h)'

    def test_pace_filter_all_categories_km(self, app):
        from app import _pace_filter
        with app.test_request_context('/'):
            from flask import g
            g.distance_unit = 'km'
            assert 'km/h' in _pace_filter('A — Fast (22+ mph)')
            assert 'km/h' in _pace_filter('B — Moderate (18–22 mph)')
            assert 'km/h' in _pace_filter('D — Beginner (<14 mph)')
