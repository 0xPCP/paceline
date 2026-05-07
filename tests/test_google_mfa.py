from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

from app.extensions import bcrypt, db
from app.mfa import _totp_at
from app.models import User
from tests.conftest import login


def _enable_google(app):
    app.config['GOOGLE_OAUTH_CLIENT_ID'] = 'google-client-id'
    app.config['GOOGLE_OAUTH_CLIENT_SECRET'] = 'google-client-secret'


def _json_response(payload):
    response = MagicMock()
    response.json.return_value = payload
    return response


def test_google_login_redirects_to_google_with_state(client, app):
    _enable_google(app)

    resp = client.get('/auth/google?next=/clubs/')

    assert resp.status_code == 302
    parsed = urlparse(resp.headers['Location'])
    query = parse_qs(parsed.query)
    assert parsed.netloc == 'accounts.google.com'
    assert query['client_id'] == ['google-client-id']
    assert query['scope'] == ['openid email profile']
    assert query['redirect_uri'][0].endswith('/auth/google/callback')
    with client.session_transaction() as sess:
        assert sess['_google_oauth_state'] == query['state'][0]
        assert sess['_google_oauth_next'] == '/clubs/'


def test_google_login_uses_forwarded_https_redirect_uri(client, app):
    _enable_google(app)

    resp = client.get('/auth/google', headers={
        'Host': 'cyclingclub.pcp.dev',
        'X-Forwarded-Proto': 'https',
        'X-Forwarded-Host': 'cyclingclub.pcp.dev',
    })

    parsed = urlparse(resp.headers['Location'])
    query = parse_qs(parsed.query)
    assert query['redirect_uri'] == ['https://cyclingclub.pcp.dev/auth/google/callback']


def test_google_callback_creates_user_for_verified_email(client, app):
    _enable_google(app)
    with client.session_transaction() as sess:
        sess['_google_oauth_state'] = 'state-token'

    with patch('app.routes.auth.requests.post', return_value=_json_response({'access_token': 'token'})), \
         patch('app.routes.auth.requests.get', return_value=_json_response({
             'sub': 'google-sub-1',
             'email': 'newgoogle@example.com',
             'email_verified': True,
         })):
        resp = client.get('/auth/google/callback?state=state-token&code=auth-code')

    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/auth/username')
    user = User.query.filter_by(email='newgoogle@example.com').one()
    assert user.google_sub == 'google-sub-1'
    assert user.username.startswith('google-')
    assert user.username_finalized is False
    with client.session_transaction() as sess:
        assert sess['_user_id'] == user.get_id()
        assert sess['_paceline_trusted_browser'] is False


def test_google_callback_links_existing_verified_email(client, app, regular_user):
    _enable_google(app)
    with client.session_transaction() as sess:
        sess['_google_oauth_state'] = 'state-token'

    with patch('app.routes.auth.requests.post', return_value=_json_response({'access_token': 'token'})), \
         patch('app.routes.auth.requests.get', return_value=_json_response({
             'sub': 'google-sub-existing',
             'email': regular_user.email,
             'email_verified': True,
         })):
        resp = client.get('/auth/google/callback?state=state-token&code=auth-code')

    assert resp.status_code == 302
    db.session.refresh(regular_user)
    assert regular_user.google_sub == 'google-sub-existing'
    assert regular_user.username_finalized is True


def test_google_user_must_set_unique_username_before_using_app(client, app):
    _enable_google(app)
    db.session.add(User(
        username='taken',
        email='taken@example.com',
        password_hash=bcrypt.generate_password_hash('password123').decode(),
    ))
    db.session.commit()
    with client.session_transaction() as sess:
        sess['_google_oauth_state'] = 'state-token'

    with patch('app.routes.auth.requests.post', return_value=_json_response({'access_token': 'token'})), \
         patch('app.routes.auth.requests.get', return_value=_json_response({
             'sub': 'google-sub-needs-name',
             'email': 'needsname@example.com',
             'email_verified': True,
         })):
        client.get('/auth/google/callback?state=state-token&code=auth-code')

    assert client.get('/clubs/').headers['Location'].endswith('/auth/username')
    duplicate = client.post('/auth/username', data={'username': 'taken'})
    assert b'already taken' in duplicate.data

    resp = client.post('/auth/username', data={'username': 'newgoogleuser'}, follow_redirects=False)
    assert resp.status_code == 302
    user = User.query.filter_by(email='needsname@example.com').one()
    assert user.username == 'newgoogleuser'
    assert user.username_finalized is True


def test_google_callback_rejects_unverified_email(client, app):
    _enable_google(app)
    with client.session_transaction() as sess:
        sess['_google_oauth_state'] = 'state-token'

    with patch('app.routes.auth.requests.post', return_value=_json_response({'access_token': 'token'})), \
         patch('app.routes.auth.requests.get', return_value=_json_response({
             'sub': 'google-sub-unverified',
             'email': 'unverified@example.com',
             'email_verified': False,
         })):
        resp = client.get('/auth/google/callback?state=state-token&code=auth-code')

    assert resp.status_code == 302
    assert User.query.filter_by(email='unverified@example.com').first() is None


def test_password_login_requires_mfa_when_enabled(client, regular_user):
    regular_user.mfa_enabled = True
    regular_user.mfa_secret = 'JBSWY3DPEHPK3PXP'
    db.session.commit()

    resp = login(client, regular_user.email, 'password123')

    assert resp.status_code == 200
    with client.session_transaction() as sess:
        assert sess['_pending_mfa_user_id'] == regular_user.id
        assert '_user_id' not in sess


def test_mfa_code_completes_password_login(client, regular_user):
    regular_user.mfa_enabled = True
    regular_user.mfa_secret = 'JBSWY3DPEHPK3PXP'
    db.session.commit()
    login(client, regular_user.email, 'password123')

    code = _totp_at(regular_user.mfa_secret, 0)
    with patch('app.routes.auth.verify_totp', return_value=True):
        resp = client.post('/auth/mfa', data={'code': code}, follow_redirects=False)

    assert resp.status_code == 302
    with client.session_transaction() as sess:
        assert sess['_user_id'] == regular_user.get_id()
        assert '_pending_mfa_user_id' not in sess


def test_mfa_backup_code_is_single_use(client, regular_user):
    backup_code = '12345678'
    regular_user.mfa_enabled = True
    regular_user.mfa_secret = 'JBSWY3DPEHPK3PXP'
    regular_user.mfa_backup_codes = [bcrypt.generate_password_hash(backup_code).decode()]
    db.session.commit()
    login(client, regular_user.email, 'password123')

    resp = client.post('/auth/mfa', data={'code': backup_code}, follow_redirects=False)

    assert resp.status_code == 302
    db.session.refresh(regular_user)
    assert regular_user.mfa_backup_codes == []
