from urllib.parse import urlparse
from unittest.mock import patch

from app.extensions import bcrypt, db
from app.models import User
from tests.conftest import login


def test_login_page_links_to_password_reset(client):
    resp = client.get('/auth/login')

    assert resp.status_code == 200
    assert b'/auth/password-reset' in resp.data


def test_password_reset_request_sends_email_without_enumeration(client, regular_user, monkeypatch):
    sent = []
    monkeypatch.setattr('app.routes.auth._send_password_reset', lambda user: sent.append(user.email))

    resp = client.post('/auth/password-reset', data={'email': regular_user.email}, follow_redirects=True)
    missing = client.post('/auth/password-reset', data={'email': 'missing@example.com'}, follow_redirects=True)

    assert resp.status_code == 200
    assert missing.status_code == 200
    assert sent == [regular_user.email]
    assert b'If that email is on a Paceline account' in resp.data
    assert b'If that email is on a Paceline account' in missing.data


def test_profile_password_reset_request_sends_to_logged_in_google_user(client, regular_user, monkeypatch):
    regular_user.google_sub = 'google-sub'
    db.session.commit()
    sent = []
    monkeypatch.setattr('app.routes.auth._send_password_reset', lambda user: sent.append(user.email))

    login(client, regular_user.email, 'password123')
    resp = client.post('/auth/password-reset/request-profile', follow_redirects=True)

    assert resp.status_code == 200
    assert sent == [regular_user.email]


def test_password_reset_token_sets_new_password_and_revokes_sessions(client, regular_user):
    from app.routes.auth import _password_reset_token
    token = _password_reset_token(regular_user)

    resp = client.post(f'/auth/password-reset/{token}', data={
        'password': 'NewPassword123!',
        'confirm_password': 'NewPassword123!',
    }, follow_redirects=True)

    assert resp.status_code == 200
    db.session.refresh(regular_user)
    assert bcrypt.check_password_hash(regular_user.password_hash, 'NewPassword123!')
    assert regular_user.session_token_version == 1
    assert login(client, regular_user.email, 'NewPassword123!').status_code == 200


def test_password_reset_token_cannot_be_reused(client, regular_user):
    from app.routes.auth import _password_reset_token
    token = _password_reset_token(regular_user)

    client.post(f'/auth/password-reset/{token}', data={
        'password': 'NewPassword123!',
        'confirm_password': 'NewPassword123!',
    })
    resp = client.get(f'/auth/password-reset/{token}', follow_redirects=True)

    assert resp.status_code == 200
    assert b'invalid or has already been used' in resp.data


def test_password_reset_email_is_branded_and_contains_link(app, regular_user):
    app.config['SERVER_NAME'] = 'paceline.club'
    from app.email import send_password_reset_email

    with app.app_context():
        with app.test_request_context(base_url='https://paceline.club'):
            with patch('app.email.mail') as mock_mail:
                send_password_reset_email(regular_user, 'https://paceline.club/auth/password-reset/token')

    msg = mock_mail.send.call_args.args[0]
    assert 'paceline.club' in msg.html
    assert 'https://paceline.club/auth/password-reset/token' in msg.html
    assert 'Set or reset your Paceline password' in msg.subject


def test_password_reset_email_route_generates_https_link(client, regular_user, monkeypatch):
    captured = []

    def fake_send(user):
        from app.routes.auth import _password_reset_token
        from flask import url_for
        captured.append(url_for('auth.password_reset', token=_password_reset_token(user), _external=True))

    monkeypatch.setattr('app.routes.auth._send_password_reset', fake_send)
    client.post('/auth/password-reset', data={'email': regular_user.email}, headers={
        'Host': 'cyclingclub.pcp.dev',
        'X-Forwarded-Proto': 'https',
        'X-Forwarded-Host': 'cyclingclub.pcp.dev',
    })

    parsed = urlparse(captured[0])
    assert parsed.scheme == 'https'
    assert parsed.netloc == 'cyclingclub.pcp.dev'
