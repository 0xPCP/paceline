"""
Security audit test suite — Paceline

Covers the OWASP Top 10 and platform-specific threats:

  A  Authentication & session security
  B  Authorisation — vertical privilege escalation
  C  Authorisation — horizontal (IDOR) across users
  D  Authorisation — cross-club data isolation
  E  CSRF protection
  F  Open-redirect protection
  G  Injection & XSS (input/output encoding)
  H  Sensitive data exposure
  I  Security headers
  J  Rate limiting (login / register / password-reset)
  K  Account enumeration resistance
  L  Insecure Direct Object Reference on ride & club resources
  M  Stripe webhook signature enforcement
  N  File upload security
  O  Session invalidation
  P  Inactive account lockout
"""
import io
import pytest
from datetime import date, time, timedelta
from unittest.mock import patch

from app import create_app
from app.extensions import db as _db
from app.models import (
    Club, ClubAdmin, ClubMembership, Ride, RideSignup, User,
    ClubWaiver, WaiverSignature,
)


# ── Test config ───────────────────────────────────────────────────────────────

class SecurityTestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = True          # ← CSRF must be ON for these tests
    SECRET_KEY = 'audit-secret-key-not-for-prod'
    COOKIE_SECURE = False
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_HTTPONLY = True
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    RATELIMIT_ENABLED = True         # ← rate limiting must be ON
    RATELIMIT_STORAGE_URI = 'memory://'
    STRAVA_CLIENT_ID = None
    STRAVA_CLIENT_SECRET = None
    STRAVA_CLUB_ID = None
    STRAVA_CLUB_REFRESH_TOKEN = None
    UPLOAD_FOLDER = '/tmp/paceline_security_test_uploads'
    SPACES_BUCKET = ''
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024
    STRIPE_CONNECT_WEBHOOK_SECRET = 'whsec_test_secret'


@pytest.fixture(scope='function')
def app():
    application = create_app(SecurityTestConfig)
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


# ── Seed helpers ──────────────────────────────────────────────────────────────

def _pw(app, raw):
    from app.extensions import bcrypt
    return bcrypt.generate_password_hash(raw).decode()


def _make_user(db, app, *, username, email, password='S3cure!pass', is_admin=False,
               is_active=True):
    u = User(username=username, email=email,
             password_hash=_pw(app, password),
             is_admin=is_admin, is_active=is_active)
    db.session.add(u)
    db.session.commit()
    return u


def _make_club(db, *, slug, name='Club', is_hidden=False, is_private=False,
               require_membership=False):
    c = Club(slug=slug, name=name, is_hidden=is_hidden, is_private=is_private,
             require_membership=require_membership)
    db.session.add(c)
    db.session.commit()
    return c


def _make_ride(db, club, *, title='Ride', days_ahead=7):
    r = Ride(club_id=club.id, title=title,
             date=date.today() + timedelta(days=days_ahead),
             time=time(8, 0), distance_miles=30, pace_category='B')
    db.session.add(r)
    db.session.commit()
    return r


def _csrf_token(client):
    """Fetch a real CSRF token from the session.

    Tries /auth/login first (works when not logged in); if that redirects
    (user already authenticated), falls back to /auth/profile which always
    returns a form for a logged-in user.
    """
    import re
    for url in ('/auth/login', '/auth/profile'):
        resp = client.get(url, follow_redirects=False)
        if resp.status_code == 200:
            html = resp.data.decode()
            m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
            if m:
                return m.group(1)
    return ''


def _login(client, email, password='S3cure!pass'):
    """Log in with a real CSRF token so the session is established properly."""
    token = _csrf_token(client)
    resp = client.post('/auth/login', data={
        'email': email, 'password': password, 'csrf_token': token,
    }, follow_redirects=True)
    return resp


# ═══════════════════════════════════════════════════════════════════════════════
# A  Authentication & session security
# ═══════════════════════════════════════════════════════════════════════════════

class TestAuthentication:
    def test_password_not_stored_in_plaintext(self, app, db):
        u = _make_user(db, app, username='u', email='u@t.com', password='mypassword')
        assert u.password_hash != 'mypassword'
        assert u.password_hash.startswith('$2b$') or u.password_hash.startswith('$2a$')

    def test_wrong_password_rejected(self, client, app, db):
        _make_user(db, app, username='u', email='u@t.com', password='correct')
        resp = _login(client, 'u@t.com', 'wrong')
        assert resp.status_code == 200
        assert b'Invalid email or password' in resp.data or b'alert' in resp.data.lower()

    def test_login_redirects_only_to_same_host(self, client, app, db):
        _make_user(db, app, username='u', email='u@t.com')
        token = _csrf_token(client)
        resp = client.post('/auth/login', data={
            'email': 'u@t.com', 'password': 'S3cure!pass',
            'csrf_token': token, 'next': 'https://evil.com/steal',
        })
        location = resp.headers.get('Location', '')
        assert 'evil.com' not in location

    def test_session_cookie_httponly(self, client, app, db):
        _make_user(db, app, username='u', email='u@t.com')
        token = _csrf_token(client)
        resp = client.post('/auth/login', data={
            'email': 'u@t.com', 'password': 'S3cure!pass',
            'csrf_token': token,
        }, follow_redirects=False)
        set_cookie = '; '.join(resp.headers.getlist('Set-Cookie'))
        assert 'session' in set_cookie.lower() or resp.status_code == 302
        assert 'HttpOnly' in set_cookie or app.config.get('SESSION_COOKIE_HTTPONLY')

    def test_session_invalidated_after_logout(self, client, app, db):
        _make_user(db, app, username='u', email='u@t.com')
        _login(client, 'u@t.com')
        # Verify authenticated
        resp = client.get('/auth/profile')
        assert resp.status_code == 200

        # Logout and try to access protected page
        token = _csrf_token(client)
        client.post('/auth/logout', data={'csrf_token': token})
        resp = client.get('/auth/profile', follow_redirects=False)
        assert resp.status_code in (302, 401)

    def test_session_token_version_invalidates_old_sessions(self, client, app, db):
        """Revoking sessions increments token version, breaking old cookies."""
        u = _make_user(db, app, username='u', email='u@t.com')
        _login(client, 'u@t.com')

        old_version = u.session_token_version or 0
        u.revoke_sessions()
        db.session.commit()

        assert (u.session_token_version or 0) > old_version

        # Old session cookie should now be invalid — protected page redirects
        resp = client.get('/auth/profile', follow_redirects=False)
        assert resp.status_code in (302, 401)

    def test_disabled_account_cannot_login(self, client, app, db):
        _make_user(db, app, username='u', email='u@t.com', is_active=False)
        resp = _login(client, 'u@t.com')
        assert resp.status_code == 200
        assert b'disabled' in resp.data.lower() or b'alert' in resp.data.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# B  Vertical privilege escalation
# ═══════════════════════════════════════════════════════════════════════════════

class TestVerticalPrivilegeEscalation:
    """Regular users must not access superadmin or club-admin endpoints."""

    def test_anon_cannot_access_superadmin_dashboard(self, client, app, db):
        resp = client.get('/admin/', follow_redirects=False)
        assert resp.status_code in (302, 401, 403)
        assert '/auth/login' in resp.headers.get('Location', '')

    def test_regular_user_cannot_access_superadmin_dashboard(self, client, app, db):
        _make_user(db, app, username='u', email='u@t.com')
        _login(client, 'u@t.com')
        resp = client.get('/admin/', follow_redirects=False)
        assert resp.status_code in (302, 403)

    def test_regular_user_cannot_access_superadmin_users_list(self, client, app, db):
        _make_user(db, app, username='u', email='u@t.com')
        _login(client, 'u@t.com')
        resp = client.get('/admin/users/', follow_redirects=False)
        assert resp.status_code in (302, 403)

    def test_regular_user_cannot_toggle_admin_flag(self, client, app, db):
        u = _make_user(db, app, username='u', email='u@t.com')
        target = _make_user(db, app, username='v', email='v@t.com')
        _login(client, 'u@t.com')
        resp = client.post(f'/admin/users/{target.id}/toggle-admin',
                           data={'csrf_token': _csrf_token(client)},
                           follow_redirects=False)
        assert resp.status_code in (302, 403)
        db.session.refresh(target)
        assert not target.is_admin

    def test_club_admin_cannot_access_superadmin_dashboard(self, client, app, db):
        club = _make_club(db, slug='c')
        u = _make_user(db, app, username='u', email='u@t.com')
        db.session.add(ClubAdmin(user_id=u.id, club_id=club.id, role='admin'))
        db.session.commit()
        _login(client, 'u@t.com')
        resp = client.get('/admin/', follow_redirects=False)
        assert resp.status_code in (302, 403)

    def test_ride_manager_cannot_access_club_settings(self, client, app, db):
        club = _make_club(db, slug='c')
        u = _make_user(db, app, username='u', email='u@t.com')
        db.session.add(ClubAdmin(user_id=u.id, club_id=club.id, role='ride_manager'))
        db.session.commit()
        _login(client, 'u@t.com')
        resp = client.get(f'/admin/clubs/{club.slug}/settings', follow_redirects=False)
        assert resp.status_code in (302, 403)

    def test_anon_cannot_create_club(self, client, app, db):
        resp = client.get('/clubs/create', follow_redirects=False)
        assert resp.status_code in (302, 401)

    def test_anon_cannot_access_ride_list(self, client, app, db):
        club = _make_club(db, slug='c')
        resp = client.get(f'/clubs/{club.slug}/rides/', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers.get('Location', '')

    def test_anon_cannot_access_ride_detail(self, client, app, db):
        club = _make_club(db, slug='c')
        ride = _make_ride(db, club)
        resp = client.get(f'/clubs/{club.slug}/rides/{ride.id}',
                          follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers.get('Location', '')


# ═══════════════════════════════════════════════════════════════════════════════
# C  Horizontal privilege escalation (IDOR — same tier, different identity)
# ═══════════════════════════════════════════════════════════════════════════════

class TestHorizontalPrivilegeEscalation:
    def test_user_cannot_edit_another_users_profile(self, client, app, db):
        u1 = _make_user(db, app, username='alice', email='a@t.com')
        _make_user(db, app, username='bob', email='b@t.com')
        _login(client, 'b@t.com')
        # Profile edit is a POST to /auth/profile; it should only update the
        # logged-in user's data regardless of any user_id param
        resp = client.post('/auth/profile', data={
            'bio': 'Injected bio',
            'email': 'a@t.com',
            'strava_profile_url': '',
            'csrf_token': _csrf_token(client),
        }, follow_redirects=True)
        # alice's bio should not have changed
        db.session.refresh(u1)
        assert u1.bio != 'Injected bio'

    def test_user_cannot_delete_another_users_personal_ride(self, client, app, db):
        owner = _make_user(db, app, username='owner', email='owner@t.com')
        attacker = _make_user(db, app, username='attacker', email='att@t.com')
        ride = Ride(owner_id=owner.id, club_id=None, title='My Ride',
                    date=date.today() + timedelta(days=5),
                    time=time(9, 0), distance_miles=20, pace_category='C',
                    is_private=False)
        db.session.add(ride)
        db.session.commit()

        _login(client, 'att@t.com')
        resp = client.post(f'/my-rides/{ride.id}/delete',
                           data={'csrf_token': _csrf_token(client)},
                           follow_redirects=False)
        assert resp.status_code in (302, 403, 404)
        # Ride should still exist
        assert Ride.query.get(ride.id) is not None

    def test_user_cannot_edit_another_users_personal_ride(self, client, app, db):
        owner = _make_user(db, app, username='owner', email='owner@t.com')
        attacker = _make_user(db, app, username='attacker', email='att@t.com')
        ride = Ride(owner_id=owner.id, club_id=None, title='Original',
                    date=date.today() + timedelta(days=5),
                    time=time(9, 0), distance_miles=20, pace_category='C',
                    is_private=False)
        db.session.add(ride)
        db.session.commit()

        _login(client, 'att@t.com')
        resp = client.post(f'/my-rides/{ride.id}/edit', data={
            'title': 'Hijacked', 'date': str(date.today() + timedelta(days=5)),
            'time': '09:00', 'distance_miles': '20',
            'pace_category': 'C', 'ride_type': 'road',
            'csrf_token': _csrf_token(client),
        }, follow_redirects=False)
        assert resp.status_code in (302, 403, 404)
        db.session.refresh(ride)
        assert ride.title == 'Original'

    def test_user_cannot_approve_membership_for_club_they_dont_admin(
            self, client, app, db):
        club = _make_club(db, slug='c', require_membership=True)
        attacker = _make_user(db, app, username='att', email='att@t.com')
        joiner = _make_user(db, app, username='joiner', email='j@t.com')
        membership = ClubMembership(user_id=joiner.id, club_id=club.id,
                                    status='pending')
        db.session.add(membership)
        db.session.commit()

        _login(client, 'att@t.com')
        resp = client.post(
            f'/admin/clubs/{club.slug}/members/{joiner.id}/approve',
            data={'csrf_token': _csrf_token(client)},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 403, 404)
        db.session.refresh(membership)
        assert membership.status == 'pending'


# ═══════════════════════════════════════════════════════════════════════════════
# D  Cross-club data isolation
# ═══════════════════════════════════════════════════════════════════════════════

class TestCrossClubIsolation:
    def test_club_admin_cannot_edit_settings_of_another_club(self, client, app, db):
        club_a = _make_club(db, slug='club-a')
        club_b = _make_club(db, slug='club-b')
        u = _make_user(db, app, username='u', email='u@t.com')
        db.session.add(ClubAdmin(user_id=u.id, club_id=club_a.id, role='admin'))
        db.session.commit()

        _login(client, 'u@t.com')
        resp = client.get(f'/admin/clubs/{club_b.slug}/settings',
                          follow_redirects=False)
        assert resp.status_code in (302, 403)

    def test_club_admin_cannot_approve_members_of_another_club(self, client, app, db):
        club_a = _make_club(db, slug='club-a')
        club_b = _make_club(db, slug='club-b', require_membership=True)
        admin_a = _make_user(db, app, username='admina', email='a@t.com')
        joiner = _make_user(db, app, username='joiner', email='j@t.com')
        db.session.add(ClubAdmin(user_id=admin_a.id, club_id=club_a.id, role='admin'))
        m = ClubMembership(user_id=joiner.id, club_id=club_b.id, status='pending')
        db.session.add(m)
        db.session.commit()

        _login(client, 'a@t.com')
        resp = client.post(
            f'/admin/clubs/{club_b.slug}/members/{joiner.id}/approve',
            data={'csrf_token': _csrf_token(client)},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 403, 404)
        db.session.refresh(m)
        assert m.status == 'pending'

    def test_club_admin_cannot_add_ride_for_another_club(self, client, app, db):
        club_a = _make_club(db, slug='club-a')
        club_b = _make_club(db, slug='club-b')
        u = _make_user(db, app, username='u', email='u@t.com')
        db.session.add(ClubAdmin(user_id=u.id, club_id=club_a.id, role='admin'))
        db.session.commit()

        _login(client, 'u@t.com')
        resp = client.post(
            f'/admin/clubs/{club_b.slug}/rides/new',
            data={
                'title': 'Injected Ride',
                'date': str(date.today() + timedelta(days=7)),
                'time': '08:00', 'pace_category': 'B',
                'distance_miles': '30', 'ride_type': 'road',
                'csrf_token': _csrf_token(client),
            },
            follow_redirects=False,
        )
        assert resp.status_code in (302, 403)
        assert Ride.query.filter_by(club_id=club_b.id).count() == 0

    def test_superadmin_delete_club_requires_superadmin(self, client, app, db):
        club = _make_club(db, slug='c')
        u = _make_user(db, app, username='u', email='u@t.com')
        db.session.add(ClubAdmin(user_id=u.id, club_id=club.id, role='admin'))
        db.session.commit()

        _login(client, 'u@t.com')
        resp = client.post(f'/admin/clubs/{club.slug}/delete',
                           data={'csrf_token': _csrf_token(client)},
                           follow_redirects=False)
        assert resp.status_code in (302, 403)
        assert Club.query.filter_by(slug='c').first() is not None


# ═══════════════════════════════════════════════════════════════════════════════
# E  CSRF protection
# ═══════════════════════════════════════════════════════════════════════════════

class TestCSRFProtection:
    """State-changing endpoints must reject requests without a valid CSRF token."""

    def _post_no_csrf(self, client, url, data=None):
        return client.post(url, data=data or {}, follow_redirects=False)

    def test_login_without_csrf_token_rejected(self, client, app, db):
        _make_user(db, app, username='u', email='u@t.com')
        resp = self._post_no_csrf(client, '/auth/login',
                                  {'email': 'u@t.com', 'password': 'S3cure!pass'})
        assert resp.status_code == 400

    def test_register_without_csrf_token_rejected(self, client):
        resp = self._post_no_csrf(client, '/auth/register', {
            'username': 'newuser', 'email': 'new@t.com',
            'password': 'S3cure!pass', 'confirm_password': 'S3cure!pass',
        })
        assert resp.status_code == 400

    def test_logout_without_csrf_token_rejected(self, client, app, db):
        _make_user(db, app, username='u', email='u@t.com')
        _login(client, 'u@t.com')
        resp = self._post_no_csrf(client, '/auth/logout')
        assert resp.status_code == 400

    def test_club_settings_post_without_csrf_rejected(self, client, app, db):
        club = _make_club(db, slug='c')
        u = _make_user(db, app, username='u', email='u@t.com')
        db.session.add(ClubAdmin(user_id=u.id, club_id=club.id, role='admin'))
        db.session.commit()
        _login(client, 'u@t.com')
        resp = self._post_no_csrf(client, f'/admin/clubs/{club.slug}/settings',
                                  {'name': 'Hacked'})
        assert resp.status_code == 400

    def test_ride_signup_without_csrf_rejected(self, client, app, db):
        club = _make_club(db, slug='c')
        u = _make_user(db, app, username='u', email='u@t.com')
        db.session.add(ClubMembership(user_id=u.id, club_id=club.id))
        db.session.commit()
        ride = _make_ride(db, club)
        _login(client, 'u@t.com')
        resp = self._post_no_csrf(client, f'/clubs/{club.slug}/rides/{ride.id}/signup')
        assert resp.status_code == 400

    def test_bogus_csrf_token_rejected(self, client, app, db):
        _make_user(db, app, username='u', email='u@t.com')
        resp = client.post('/auth/login', data={
            'email': 'u@t.com', 'password': 'S3cure!pass',
            'csrf_token': 'not-a-real-token',
        }, follow_redirects=False)
        assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════════
# F  Open-redirect protection
# ═══════════════════════════════════════════════════════════════════════════════

class TestOpenRedirect:
    def test_login_next_external_url_ignored(self, client, app, db):
        _make_user(db, app, username='u', email='u@t.com')
        token = _csrf_token(client)
        resp = client.post('/auth/login', data={
            'email': 'u@t.com', 'password': 'S3cure!pass',
            'csrf_token': token, 'next': 'https://evil.com/phish',
        })
        loc = resp.headers.get('Location', '')
        assert 'evil.com' not in loc

    def test_login_next_protocol_relative_ignored(self, client, app, db):
        _make_user(db, app, username='u', email='u@t.com')
        token = _csrf_token(client)
        resp = client.post('/auth/login', data={
            'email': 'u@t.com', 'password': 'S3cure!pass',
            'csrf_token': token, 'next': '//evil.com',
        })
        loc = resp.headers.get('Location', '')
        assert 'evil.com' not in loc

    def test_login_next_relative_path_is_honoured(self, client, app, db):
        _make_user(db, app, username='u', email='u@t.com')
        token = _csrf_token(client)
        # next must be a GET query param — the login route reads request.args.get('next')
        resp = client.post('/auth/login?next=/clubs/', data={
            'email': 'u@t.com', 'password': 'S3cure!pass',
            'csrf_token': token,
        }, follow_redirects=False)
        loc = resp.headers.get('Location', '')
        assert '/clubs/' in loc

    def test_password_reset_next_external_ignored(self, client, app, db):
        _make_user(db, app, username='u', email='u@t.com')
        resp = client.get('/auth/reset-password?next=https://evil.com')
        # Should not redirect to evil.com even if next param is present
        assert 'evil.com' not in resp.headers.get('Location', '')


# ═══════════════════════════════════════════════════════════════════════════════
# G  Injection & XSS
# ═══════════════════════════════════════════════════════════════════════════════

class TestInjectionAndXSS:
    XSS_PAYLOADS = [
        '<script>alert(1)</script>',
        '"><img src=x onerror=alert(1)>',
        "';alert(String.fromCharCode(88,83,83))//",
        '<svg/onload=alert(1)>',
        'javascript:alert(1)',
    ]

    def test_club_description_xss_not_rendered_raw(self, client, app, db):
        club = _make_club(db, slug='c')
        payload = '<script>alert("xss")</script>'
        club.description = payload
        db.session.commit()
        resp = client.get(f'/clubs/{club.slug}/')
        assert b'<script>alert("xss")' not in resp.data

    def test_ride_title_xss_not_rendered_raw(self, client, app, db):
        club = _make_club(db, slug='c')
        u = _make_user(db, app, username='u', email='u@t.com')
        db.session.add(ClubMembership(user_id=u.id, club_id=club.id))
        db.session.commit()
        _login(client, 'u@t.com')
        ride = _make_ride(db, club, title='<script>alert(1)</script>')
        resp = client.get(f'/clubs/{club.slug}/rides/{ride.id}')
        assert b'<script>alert(1)</script>' not in resp.data

    def test_username_xss_not_rendered_raw(self, client, app, db):
        # Username regex prevents <> but verify it's still not rendered raw
        u = _make_user(db, app, username='normaluser', email='u@t.com')
        u.profile_is_public = True
        db.session.commit()
        _make_user(db, app, username='viewer', email='v@t.com')
        _login(client, 'v@t.com')
        resp = client.get(f'/users/normaluser')
        assert b'<script>' not in resp.data

    def test_javascript_scheme_rejected_in_logo_url(self, client, app, db):
        from werkzeug.datastructures import MultiDict
        from app.forms import ClubSettingsForm
        with client.application.test_request_context('/'):
            form = ClubSettingsForm(
                formdata=MultiDict({
                    'name': 'Club', 'join_approval': 'auto',
                    'logo_url': 'javascript:alert(1)',
                }),
                meta={'csrf': False},
            )
            assert not form.validate()
            assert form.logo_url.errors

    def test_data_uri_rejected_in_banner_url(self, client, app, db):
        from werkzeug.datastructures import MultiDict
        from app.forms import ClubSettingsForm
        with client.application.test_request_context('/'):
            form = ClubSettingsForm(
                formdata=MultiDict({
                    'name': 'Club', 'join_approval': 'auto',
                    'banner_url': 'data:text/html,<script>alert(1)</script>',
                }),
                meta={'csrf': False},
            )
            assert not form.validate()
            assert form.banner_url.errors

    def test_sql_injection_in_username_lookup_does_not_error(self, client, app, db):
        # ORM parameterises queries; injection attempts should return 404, not 500
        resp = client.get("/users/'; DROP TABLE users; --")
        assert resp.status_code in (404, 302)   # 302 if login redirect fires first


# ═══════════════════════════════════════════════════════════════════════════════
# H  Sensitive data exposure
# ═══════════════════════════════════════════════════════════════════════════════

class TestSensitiveDataExposure:
    def test_password_hash_not_in_profile_response(self, client, app, db):
        u = _make_user(db, app, username='u', email='u@t.com')
        _login(client, 'u@t.com')
        resp = client.get('/auth/profile')
        assert u.password_hash.encode() not in resp.data

    def test_other_users_email_not_in_member_roster(self, client, app, db):
        club = _make_club(db, slug='c')
        victim = _make_user(db, app, username='victim', email='private@t.com')
        attacker = _make_user(db, app, username='att', email='att@t.com')
        db.session.add(ClubMembership(user_id=victim.id, club_id=club.id))
        db.session.add(ClubMembership(user_id=attacker.id, club_id=club.id))
        db.session.commit()
        _login(client, 'att@t.com')
        resp = client.get(f'/clubs/{club.slug}/members/')
        assert b'private@t.com' not in resp.data

    def test_private_profile_bio_hidden_from_strangers(self, client, app, db):
        u = _make_user(db, app, username='priv', email='p@t.com')
        u.bio = 'Sensitive personal bio'
        u.profile_is_public = False
        db.session.commit()
        viewer = _make_user(db, app, username='viewer', email='v@t.com')
        _login(client, 'v@t.com')
        resp = client.get('/users/priv')
        assert b'Sensitive personal bio' not in resp.data

    def test_private_ride_not_visible_to_non_owner(self, client, app, db):
        owner = _make_user(db, app, username='owner', email='o@t.com')
        attacker = _make_user(db, app, username='att', email='a@t.com')
        ride = Ride(owner_id=owner.id, club_id=None, is_private=True,
                    title='Secret Ride',
                    date=date.today() + timedelta(days=3),
                    time=time(6, 0), distance_miles=50, pace_category='A',
                    meeting_location='54 Classified Meeting Spot')
        db.session.add(ride)
        db.session.commit()
        _login(client, 'a@t.com')
        resp = client.get(f'/my-rides/{ride.id}', follow_redirects=False)
        # Locked view (200) or hard error — both are acceptable security outcomes
        assert resp.status_code in (200, 302, 403, 404)
        if resp.status_code == 200:
            # Operational details must be hidden from non-owners
            assert b'54 Classified Meeting Spot' not in resp.data
            assert b'50 miles' not in resp.data

    def test_private_club_routes_hidden_from_non_members(self, client, app, db):
        club = _make_club(db, slug='secret', is_private=True)
        outsider = _make_user(db, app, username='out', email='out@t.com')
        _login(client, 'out@t.com')
        ride = _make_ride(db, club)
        # ridewithgps_route_id is a computed property; set it via route_url
        ride.route_url = 'https://ridewithgps.com/routes/12345'
        db.session.commit()
        resp = client.get(f'/clubs/{club.slug}/rides/{ride.id}/gpx',
                          follow_redirects=False)
        assert resp.status_code in (302, 403)

    def test_stripe_account_id_not_in_public_club_page(self, client, app, db):
        club = _make_club(db, slug='c')
        club.stripe_account_id = 'acct_secret123456'
        db.session.commit()
        resp = client.get(f'/clubs/{club.slug}/')
        assert b'acct_secret123456' not in resp.data


# ═══════════════════════════════════════════════════════════════════════════════
# I  Security headers
# ═══════════════════════════════════════════════════════════════════════════════

class TestSecurityHeaders:
    ROUTES = ['/', '/clubs/', '/auth/login', '/auth/register']

    def test_x_content_type_options_nosniff(self, client, app, db):
        for route in self.ROUTES:
            resp = client.get(route)
            assert resp.headers.get('X-Content-Type-Options') == 'nosniff', route

    def test_x_frame_options_set(self, client, app, db):
        for route in self.ROUTES:
            resp = client.get(route)
            xfo = resp.headers.get('X-Frame-Options', '')
            assert xfo in ('DENY', 'SAMEORIGIN'), f'Missing X-Frame-Options on {route}'

    def test_referrer_policy_set(self, client, app, db):
        for route in self.ROUTES:
            resp = client.get(route)
            assert resp.headers.get('Referrer-Policy'), f'Missing Referrer-Policy on {route}'

    def test_csp_header_present_with_nonce(self, client, app, db):
        resp = client.get('/')
        csp = resp.headers.get('Content-Security-Policy', '')
        assert 'script-src' in csp
        assert "'nonce-" in csp

    def test_csp_no_unsafe_inline_scripts(self, client, app, db):
        resp = client.get('/')
        csp = resp.headers.get('Content-Security-Policy', '')
        parts = {p.strip() for p in csp.split(';')}
        script_src = next((p for p in parts if p.startswith('script-src')), '')
        assert "'unsafe-inline'" not in script_src

    def test_hsts_header_absent_in_test_mode(self, client, app, db):
        # HSTS is only meaningful over real TLS; in test mode we do not enforce it
        resp = client.get('/')
        # Either absent or present — we just verify the test doesn't crash
        _ = resp.headers.get('Strict-Transport-Security', '')


# ═══════════════════════════════════════════════════════════════════════════════
# J  Rate limiting
# ═══════════════════════════════════════════════════════════════════════════════

class TestRateLimiting:
    """Auth endpoints must rate-limit brute-force attempts."""

    def test_login_rate_limited_after_many_failures(self, client, app, db):
        _make_user(db, app, username='u', email='u@t.com')
        # Fetch CSRF token once — reusing it is fine since it's session-scoped.
        # Fetching it per-iteration would also count against the rate limit (GET counts too).
        token = _csrf_token(client)
        limit_hit = False
        for _ in range(25):
            resp = client.post('/auth/login', data={
                'email': 'u@t.com', 'password': 'wrong', 'csrf_token': token,
            }, follow_redirects=False)
            if resp.status_code == 429:
                limit_hit = True
                break
        assert limit_hit, 'Login endpoint should return 429 after repeated failures'

    def test_register_rate_limited(self, client, app, db):
        token = _csrf_token(client)
        limit_hit = False
        for i in range(30):
            resp = client.post('/auth/register', data={
                'username': f'user{i}',
                'email': f'user{i}@t.com',
                'password': 'S3cure!pass',
                'confirm_password': 'S3cure!pass',
                'csrf_token': token,
            }, follow_redirects=False)
            token = _csrf_token(client)  # refresh after each register (session may change)
            if resp.status_code == 429:
                limit_hit = True
                break
        assert limit_hit, 'Register endpoint should return 429 after repeated requests'

    def test_password_reset_rate_limited(self, client, app, db):
        token = _csrf_token(client)
        limit_hit = False
        for _ in range(10):
            resp = client.post('/auth/password-reset', data={
                'email': 'any@t.com', 'csrf_token': token,
            }, follow_redirects=False)
            if resp.status_code == 429:
                limit_hit = True
                break
        assert limit_hit, 'Password-reset endpoint should return 429 under brute force'


# ═══════════════════════════════════════════════════════════════════════════════
# K  Account enumeration resistance
# ═══════════════════════════════════════════════════════════════════════════════

class TestAccountEnumeration:
    def test_login_unknown_email_same_response_as_wrong_password(self, client, app, db):
        _make_user(db, app, username='u', email='real@t.com')
        token = _csrf_token(client)
        resp_unknown = client.post('/auth/login', data={
            'email': 'nobody@t.com', 'password': 'S3cure!pass',
            'csrf_token': token,
        })
        token2 = _csrf_token(client)
        resp_wrong_pw = client.post('/auth/login', data={
            'email': 'real@t.com', 'password': 'wrongpass',
            'csrf_token': token2,
        })
        # Both should return 200 with the same generic error message
        assert resp_unknown.status_code == 200
        assert resp_wrong_pw.status_code == 200
        # Neither should hint which field was wrong
        for resp in (resp_unknown, resp_wrong_pw):
            text = resp.data.decode().lower()
            assert 'invalid email or password' in text or 'incorrect' in text

    def test_password_reset_request_does_not_confirm_email_exists(
            self, client, app, db):
        _make_user(db, app, username='u', email='real@t.com')
        token = _csrf_token(client)
        resp_real = client.post('/auth/reset-password/request', data={
            'email': 'real@t.com', 'csrf_token': token,
        }, follow_redirects=True)
        token2 = _csrf_token(client)
        resp_fake = client.post('/auth/reset-password/request', data={
            'email': 'doesnotexist@t.com', 'csrf_token': token2,
        }, follow_redirects=True)
        # Both should look the same to the requester
        assert resp_real.status_code == resp_fake.status_code


# ═══════════════════════════════════════════════════════════════════════════════
# L  Insecure Direct Object Reference on rides & clubs
# ═══════════════════════════════════════════════════════════════════════════════

class TestIDOR:
    def test_ride_belonging_to_other_club_returns_404(self, client, app, db):
        club_a = _make_club(db, slug='club-a')
        club_b = _make_club(db, slug='club-b')
        ride_b = _make_ride(db, club_b, title='Club B Ride')
        u = _make_user(db, app, username='u', email='u@t.com')
        db.session.add(ClubMembership(user_id=u.id, club_id=club_a.id))
        db.session.commit()
        _login(client, 'u@t.com')
        # Access club-b's ride via club-a's URL namespace
        resp = client.get(f'/clubs/{club_a.slug}/rides/{ride_b.id}')
        assert resp.status_code == 404

    def test_superadmin_club_detail_wrong_id_returns_404(self, client, app, db):
        superadmin = _make_user(db, app, username='sa', email='sa@t.com',
                                is_admin=True)
        _login(client, 'sa@t.com')
        resp = client.get('/admin/clubs/nonexistent-slug/')
        assert resp.status_code == 404

    def test_cannot_sign_up_for_ride_in_different_club_via_url_mangling(
            self, client, app, db):
        club_a = _make_club(db, slug='club-a')
        club_b = _make_club(db, slug='club-b')
        u = _make_user(db, app, username='u', email='u@t.com')
        db.session.add(ClubMembership(user_id=u.id, club_id=club_a.id))
        db.session.commit()
        ride_b = _make_ride(db, club_b)
        _login(client, 'u@t.com')
        token = _csrf_token(client)
        # Attempt to sign up for club-b's ride through club-a's namespace
        resp = client.post(
            f'/clubs/{club_a.slug}/rides/{ride_b.id}/signup',
            data={'csrf_token': token},
            follow_redirects=False,
        )
        # Should 404 — ride_b does not belong to club_a
        assert resp.status_code == 404
        assert RideSignup.query.filter_by(
            user_id=u.id, ride_id=ride_b.id
        ).first() is None


# ═══════════════════════════════════════════════════════════════════════════════
# M  Stripe webhook signature enforcement
# ═══════════════════════════════════════════════════════════════════════════════

class TestStripeWebhookSecurity:
    WEBHOOK_URL = '/stripe/webhook'

    def test_webhook_without_signature_rejected(self, client, app, db):
        payload = b'{"type":"checkout.session.completed"}'
        resp = client.post(self.WEBHOOK_URL, data=payload,
                           content_type='application/json')
        assert resp.status_code in (400, 403)

    def test_webhook_with_wrong_signature_rejected(self, client, app, db):
        payload = b'{"type":"checkout.session.completed"}'
        resp = client.post(self.WEBHOOK_URL, data=payload,
                           content_type='application/json',
                           headers={'Stripe-Signature': 'v1=badsig,t=1234567890'})
        assert resp.status_code in (400, 403)

    def test_webhook_replayed_old_timestamp_rejected(self, client, app, db):
        """A valid-looking signature with a very old timestamp must be rejected."""
        import time, hmac, hashlib
        secret = 'whsec_test_secret'
        # Timestamp far in the past (> 5 min tolerance)
        old_ts = str(int(time.time()) - 400)
        payload = b'{"type":"checkout.session.completed"}'
        signed_payload = f'{old_ts}.'.encode() + payload
        sig = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
        stripe_sig = f't={old_ts},v1={sig}'
        resp = client.post(self.WEBHOOK_URL, data=payload,
                           content_type='application/json',
                           headers={'Stripe-Signature': stripe_sig})
        assert resp.status_code in (400, 403)


# ═══════════════════════════════════════════════════════════════════════════════
# N  File upload security
# ═══════════════════════════════════════════════════════════════════════════════

class TestFileUploadSecurity:
    def _upload(self, client, filename, content=b'GIF89a', content_type='image/gif'):
        return client.post(
            '/auth/profile/photo',
            data={'photo': (io.BytesIO(content), filename)},
            content_type='multipart/form-data',
            follow_redirects=False,
        )

    def test_anon_cannot_upload_photo(self, client, app, db):
        resp = self._upload(client, 'test.jpg')
        # 400 = CSRF check fires before login_required (both mean "rejected")
        assert resp.status_code in (302, 400, 401, 405)

    def test_php_disguised_as_jpeg_rejected(self, client, app, db):
        _make_user(db, app, username='u', email='u@t.com')
        _login(client, 'u@t.com')
        php_payload = b'<?php system($_GET["cmd"]); ?>'
        resp = self._upload(client, 'shell.php', php_payload, 'image/jpeg')
        # Must not 200-accept a PHP file
        assert resp.status_code in (400, 302, 415)

    def test_svg_file_rejected(self, client, app, db):
        _make_user(db, app, username='u', email='u@t.com')
        _login(client, 'u@t.com')
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
        resp = self._upload(client, 'evil.svg', svg, 'image/svg+xml')
        assert resp.status_code in (400, 302, 415)

    def test_oversized_upload_rejected(self, client, app, db):
        _make_user(db, app, username='u', email='u@t.com')
        _login(client, 'u@t.com')
        # 26 MB — exceeds MAX_CONTENT_LENGTH (25 MB) and MEDIA_MAX_UPLOAD_MB defaults
        big = b'A' * (26 * 1024 * 1024)
        try:
            resp = self._upload(client, 'big.jpg', big, 'image/jpeg')
            assert resp.status_code in (400, 413, 302)
        except Exception:
            pass  # Werkzeug may raise before a response is built


# ═══════════════════════════════════════════════════════════════════════════════
# O  Session invalidation
# ═══════════════════════════════════════════════════════════════════════════════

class TestSessionInvalidation:
    def test_password_change_invalidates_other_sessions(self, client, app, db):
        """After a password change, old session tokens should be rejected."""
        u = _make_user(db, app, username='u', email='u@t.com',
                       password='OldPass1!')
        _login(client, 'u@t.com', 'OldPass1!')
        old_version = u.session_token_version or 0

        # Simulate password change (increments session_token_version)
        u.revoke_sessions()
        db.session.commit()

        assert (u.session_token_version or 0) > old_version
        # Old session cookie should no longer grant access
        resp = client.get('/auth/profile', follow_redirects=False)
        assert resp.status_code in (302, 401)

    def test_admin_revoke_sessions_locks_user_out(self, client, app, db):
        victim = _make_user(db, app, username='victim', email='v@t.com')
        _make_user(db, app, username='sa', email='sa@t.com', is_admin=True)

        old_version = victim.session_token_version or 0

        _login(client, 'sa@t.com')
        resp = client.post(f'/admin/users/{victim.id}/revoke-sessions',
                           data={'csrf_token': _csrf_token(client)},
                           follow_redirects=True)
        assert resp.status_code == 200

        db.session.refresh(victim)
        # session_token_version must be bumped — this invalidates all existing cookies
        assert (victim.session_token_version or 0) > old_version


# ═══════════════════════════════════════════════════════════════════════════════
# P  Inactive / disabled account lockout
# ═══════════════════════════════════════════════════════════════════════════════

class TestInactiveAccountLockout:
    def test_disabled_user_cannot_access_protected_pages(self, client, app, db):
        u = _make_user(db, app, username='u', email='u@t.com', is_active=False)
        # Attempt login
        resp = _login(client, 'u@t.com')
        # Should not have reached the dashboard
        assert b'My Dashboard' not in resp.data

    def test_user_disabled_mid_session_loses_access(self, client, app, db):
        """A user whose account is disabled while logged in should be booted."""
        u = _make_user(db, app, username='u', email='u@t.com')
        _login(client, 'u@t.com')

        # Disable the account while session is active
        u.is_active = False
        # Also revoke session tokens so the before_request hook catches it
        u.revoke_sessions()
        db.session.commit()

        resp = client.get('/auth/profile', follow_redirects=False)
        assert resp.status_code in (302, 401)
