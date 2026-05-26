"""Tests for per-club Strava activity feed."""
import pytest
from unittest.mock import patch, MagicMock
from app.extensions import db
from app.routes.strava import get_club_activities, _activity_cache, _token_cache


FAKE_ACTIVITY = {
    'name': 'Tuesday Morning Rip',
    'type': 'Ride',
    'distance': 64374.0,      # ~40 miles in meters
    'total_elevation_gain': 640.0,  # ~2100 ft in meters
    'moving_time': 5400,      # 1h 30m
    'athlete': {'firstname': 'Dave', 'lastname': 'K.'},
}


def _clear_caches():
    _activity_cache.clear()
    _token_cache.clear()


# ── get_club_activities unit tests ────────────────────────────────────────────

def test_returns_empty_for_none_club_id(app):
    with app.app_context():
        assert get_club_activities(None) == []


def test_returns_empty_when_no_token(app):
    with app.app_context():
        _clear_caches()
        # No STRAVA_CLIENT_ID configured → _get_club_token returns None
        assert get_club_activities(12345) == []


def test_fetches_and_transforms_activities(app):
    with app.app_context():
        _clear_caches()
        fake_token = {'access_token': 'tok123', 'expires_at': 9999999999}

        with patch('app.routes.strava.requests.post') as mock_post, \
             patch('app.routes.strava.requests.get') as mock_get:
            mock_post.return_value = MagicMock(status_code=200, json=lambda: fake_token)
            mock_get.return_value = MagicMock(status_code=200, json=lambda: [FAKE_ACTIVITY])

            app.config['STRAVA_CLIENT_ID'] = 'cid'
            app.config['STRAVA_CLIENT_SECRET'] = 'csec'
            app.config['STRAVA_CLUB_REFRESH_TOKEN'] = 'rtoken'

            acts = get_club_activities(12345)

        assert len(acts) == 1
        a = acts[0]
        assert a['distance_miles'] == pytest.approx(40.0, abs=0.5)
        assert a['elevation_feet'] > 2000
        assert a['moving_time_fmt'] == '1h 30m'
        assert a['athlete']['firstname'] == 'Dave'

        # Clean up config
        app.config['STRAVA_CLIENT_ID'] = None
        app.config['STRAVA_CLIENT_SECRET'] = None
        app.config['STRAVA_CLUB_REFRESH_TOKEN'] = None
        _clear_caches()


def test_cache_prevents_second_request(app):
    with app.app_context():
        _clear_caches()
        fake_token = {'access_token': 'tok123', 'expires_at': 9999999999}

        app.config['STRAVA_CLIENT_ID'] = 'cid'
        app.config['STRAVA_CLIENT_SECRET'] = 'csec'
        app.config['STRAVA_CLUB_REFRESH_TOKEN'] = 'rtoken'

        with patch('app.routes.strava.requests.post') as mock_post, \
             patch('app.routes.strava.requests.get') as mock_get:
            mock_post.return_value = MagicMock(status_code=200, json=lambda: fake_token)
            mock_get.return_value = MagicMock(status_code=200, json=lambda: [FAKE_ACTIVITY])

            get_club_activities(12345)
            get_club_activities(12345)  # second call should use cache

            assert mock_get.call_count == 1  # only fetched once

        app.config['STRAVA_CLIENT_ID'] = None
        app.config['STRAVA_CLIENT_SECRET'] = None
        app.config['STRAVA_CLUB_REFRESH_TOKEN'] = None
        _clear_caches()


def test_different_club_ids_cached_separately(app):
    with app.app_context():
        _clear_caches()
        fake_token = {'access_token': 'tok123', 'expires_at': 9999999999}

        app.config['STRAVA_CLIENT_ID'] = 'cid'
        app.config['STRAVA_CLIENT_SECRET'] = 'csec'
        app.config['STRAVA_CLUB_REFRESH_TOKEN'] = 'rtoken'

        with patch('app.routes.strava.requests.post') as mock_post, \
             patch('app.routes.strava.requests.get') as mock_get:
            mock_post.return_value = MagicMock(status_code=200, json=lambda: fake_token)
            mock_get.return_value = MagicMock(status_code=200, json=lambda: [FAKE_ACTIVITY])

            get_club_activities(11111)
            get_club_activities(22222)

            assert mock_get.call_count == 2  # separate fetches

        app.config['STRAVA_CLIENT_ID'] = None
        app.config['STRAVA_CLIENT_SECRET'] = None
        app.config['STRAVA_CLUB_REFRESH_TOKEN'] = None
        _clear_caches()


def test_moving_time_fmt_under_one_hour(app):
    with app.app_context():
        _clear_caches()
        fake_token = {'access_token': 'tok', 'expires_at': 9999999999}
        short_act = dict(FAKE_ACTIVITY, moving_time=2700)  # 45m

        app.config['STRAVA_CLIENT_ID'] = 'cid'
        app.config['STRAVA_CLIENT_SECRET'] = 'csec'
        app.config['STRAVA_CLUB_REFRESH_TOKEN'] = 'rtoken'

        with patch('app.routes.strava.requests.post') as mock_post, \
             patch('app.routes.strava.requests.get') as mock_get:
            mock_post.return_value = MagicMock(status_code=200, json=lambda: fake_token)
            mock_get.return_value = MagicMock(status_code=200, json=lambda: [short_act])

            acts = get_club_activities(99999)

        assert acts[0]['moving_time_fmt'] == '45m'

        app.config['STRAVA_CLIENT_ID'] = None
        app.config['STRAVA_CLIENT_SECRET'] = None
        app.config['STRAVA_CLUB_REFRESH_TOKEN'] = None
        _clear_caches()


def test_returns_empty_on_strava_api_error(app):
    with app.app_context():
        _clear_caches()
        fake_token = {'access_token': 'tok', 'expires_at': 9999999999}

        app.config['STRAVA_CLIENT_ID'] = 'cid'
        app.config['STRAVA_CLIENT_SECRET'] = 'csec'
        app.config['STRAVA_CLUB_REFRESH_TOKEN'] = 'rtoken'

        with patch('app.routes.strava.requests.post') as mock_post, \
             patch('app.routes.strava.requests.get') as mock_get:
            mock_post.return_value = MagicMock(status_code=200, json=lambda: fake_token)
            mock_get.return_value = MagicMock(status_code=403)

            result = get_club_activities(12345)

        assert result == []

        app.config['STRAVA_CLIENT_ID'] = None
        app.config['STRAVA_CLIENT_SECRET'] = None
        app.config['STRAVA_CLUB_REFRESH_TOKEN'] = None
        _clear_caches()


# ── Template / club home page tests ──────────────────────────────────────────

def test_strava_feed_shown_when_activities_present(client, app, sample_club, mock_weather):
    """Club home shows activity cards when Strava returns data."""
    sample_club.strava_club_id = 12345
    db.session.commit()

    with patch('app.routes.clubs.get_club_activities', return_value=[FAKE_ACTIVITY]):
        resp = client.get(f'/clubs/{sample_club.slug}/')

    assert resp.status_code == 200
    assert b'Recent Club Activity' in resp.data
    assert b'Tuesday Morning Rip' in resp.data


def test_strava_feed_hidden_when_no_activities(client, app, sample_club, mock_weather):
    """Club home hides the activity section when list is empty."""
    sample_club.strava_club_id = None
    db.session.commit()

    with patch('app.routes.clubs.get_club_activities', return_value=[]):
        resp = client.get(f'/clubs/{sample_club.slug}/')

    assert resp.status_code == 200
    assert b'Recent Club Rides' not in resp.data


def test_strava_view_on_strava_link_shown(client, app, sample_club, mock_weather):
    """'View on Strava' link includes the club's Strava ID."""
    sample_club.strava_club_id = 55555
    db.session.commit()

    with patch('app.routes.clubs.get_club_activities', return_value=[FAKE_ACTIVITY]):
        resp = client.get(f'/clubs/{sample_club.slug}/')

    assert b'55555' in resp.data


# ── Admin settings form tests ─────────────────────────────────────────────────

def test_settings_saves_strava_club_id(client, app, sample_club, club_admin_user):
    """Admin can save a numeric strava_club_id via settings form."""
    from tests.conftest import login
    login(client, email='clubadmin@test.com')

    resp = client.post(
        f'/admin/clubs/{sample_club.slug}/settings',
        data={
            'name': sample_club.name,
            'strava_club_id': '98765',
            'cancel_rain_prob': '80',
            'cancel_wind_mph': '35',
            'cancel_temp_min_f': '28',
            'cancel_temp_max_f': '100',
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    db.session.refresh(sample_club)
    assert sample_club.strava_club_id == 98765


def test_settings_clears_strava_club_id_when_blank(client, app, sample_club, club_admin_user):
    """Submitting blank strava_club_id clears it."""
    sample_club.strava_club_id = 12345
    db.session.commit()

    from tests.conftest import login
    login(client, email='clubadmin@test.com')

    resp = client.post(
        f'/admin/clubs/{sample_club.slug}/settings',
        data={
            'name': sample_club.name,
            'strava_club_id': '',
            'cancel_rain_prob': '80',
            'cancel_wind_mph': '35',
            'cancel_temp_min_f': '28',
            'cancel_temp_max_f': '100',
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    db.session.refresh(sample_club)
    assert sample_club.strava_club_id is None


def test_settings_ignores_non_numeric_strava_id(client, app, sample_club, club_admin_user):
    """Non-numeric strava_club_id is not saved (treated as None)."""
    from tests.conftest import login
    login(client, email='clubadmin@test.com')

    resp = client.post(
        f'/admin/clubs/{sample_club.slug}/settings',
        data={
            'name': sample_club.name,
            'strava_club_id': 'not-a-number',
            'cancel_rain_prob': '80',
            'cancel_wind_mph': '35',
            'cancel_temp_min_f': '28',
            'cancel_temp_max_f': '100',
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    db.session.refresh(sample_club)
    assert sample_club.strava_club_id is None


# ── OAuth state nonce (CSRF protection) ───────────────────────────────────────

def _do_login(client, email='rider@test.com', password='password123'):
    client.post('/auth/login', data={'email': email, 'password': password},
                follow_redirects=True)


def test_strava_connect_sets_state_in_session(client, app, regular_user):
    """connect() stores a state nonce in the session and passes it to Strava."""
    app.config['STRAVA_CLIENT_ID'] = 'test-client-id'
    _do_login(client)
    resp = client.get('/strava/connect')
    assert resp.status_code == 302
    location = resp.headers['Location']
    assert 'state=' in location
    with client.session_transaction() as sess:
        assert 'strava_oauth_state' in sess


def test_strava_callback_rejects_missing_state(client, app, regular_user):
    """callback() redirects to profile with error when state param is absent."""
    app.config['STRAVA_CLIENT_ID'] = 'test-client-id'
    app.config['STRAVA_CLIENT_SECRET'] = 'secret'
    _do_login(client)
    with client.session_transaction() as sess:
        sess['strava_oauth_state'] = 'expected-nonce'
    resp = client.get('/strava/callback?code=abc123')
    assert resp.status_code == 302
    assert '/auth/profile' in resp.headers['Location']
    with client.session_transaction() as sess:
        assert 'strava_oauth_state' not in sess  # consumed even on failure


def test_strava_callback_rejects_wrong_state(client, app, regular_user):
    """callback() rejects a state that doesn't match the session nonce."""
    app.config['STRAVA_CLIENT_ID'] = 'test-client-id'
    app.config['STRAVA_CLIENT_SECRET'] = 'secret'
    _do_login(client)
    with client.session_transaction() as sess:
        sess['strava_oauth_state'] = 'correct-nonce'
    resp = client.get('/strava/callback?code=abc123&state=wrong-nonce')
    assert resp.status_code == 302
    assert '/auth/profile' in resp.headers['Location']
