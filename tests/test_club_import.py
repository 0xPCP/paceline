"""
Tests for the bulk member import feature.

Covers:
  - New-user path: account creation, membership, welcome email triggered
  - Existing-user path: invite email triggered, no account created
  - Already-member path: skipped silently
  - Invalid email: listed in results, not processed
  - Batch limit enforcement (>200 emails rejected)
  - setup_account: password set, user logged in, invite marked used
  - setup_account: expired / already-used token rejected
  - invite_claim redirect: is_new_user=True goes to setup_account
  - Non-admin cannot access import route
"""
import secrets
from datetime import datetime, timedelta, timezone

import pytest

from app.extensions import db as _db, bcrypt
from app.models import User, Club, ClubMembership, ClubAdmin, ClubInvite


# ── Helpers ───────────────────────────────────────────────────────────────────

def _login(client, email, password):
    return client.post('/auth/login', data={'email': email, 'password': password},
                       follow_redirects=True)


def _make_club_admin(db, club, user):
    db.session.add(ClubAdmin(user_id=user.id, club_id=club.id, role='admin'))
    db.session.commit()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def club(db):
    c = Club(slug='testclub', name='Test Club', is_active=True, is_hidden=False)
    db.session.add(c)
    db.session.commit()
    return c


@pytest.fixture
def club_admin(db, club):
    pw = bcrypt.generate_password_hash('password').decode()
    u = User(username='clubadmin', email='clubadmin@test.com', password_hash=pw)
    db.session.add(u)
    db.session.flush()
    _make_club_admin(db, club, u)
    db.session.commit()
    return u


@pytest.fixture
def existing_user(db):
    """A user who already has a Paceline account but is not in any club."""
    pw = bcrypt.generate_password_hash('password').decode()
    u = User(username='existinguser', email='existing@example.com', password_hash=pw)
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def member_user(db, club):
    """A user who is already an active member of the club."""
    pw = bcrypt.generate_password_hash('password').decode()
    u = User(username='alreadymember', email='member@example.com', password_hash=pw)
    db.session.add(u)
    db.session.flush()
    db.session.add(ClubMembership(user_id=u.id, club_id=club.id, status='active'))
    db.session.commit()
    return u


def _import_post(client, club, emails_text, message='', membership_expires_on=''):
    return client.post(
        f'/admin/clubs/{club.slug}/import',
        data={'emails': emails_text, 'message': message, 'membership_expires_on': membership_expires_on},
        follow_redirects=True,
    )


# ── Access control ────────────────────────────────────────────────────────────

class TestImportAccess:
    def test_anonymous_denied(self, client, club):
        resp = client.get(f'/admin/clubs/{club.slug}/import')
        assert resp.status_code in (302, 403)

    def test_non_admin_denied(self, client, db, club):
        pw = bcrypt.generate_password_hash('pw').decode()
        u = User(username='nobody', email='nobody@test.com', password_hash=pw)
        db.session.add(u)
        db.session.commit()
        _login(client, 'nobody@test.com', 'pw')
        resp = client.get(f'/admin/clubs/{club.slug}/import')
        assert resp.status_code == 403

    def test_club_admin_can_access(self, client, club, club_admin):
        _login(client, club_admin.email, 'password')
        resp = client.get(f'/admin/clubs/{club.slug}/import')
        assert resp.status_code == 200
        assert b'Import Members' in resp.data


# ── New-user import path ──────────────────────────────────────────────────────

class TestNewUserImport:
    def test_creates_user_account(self, client, club, club_admin, db):
        _login(client, club_admin.email, 'password')
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr('app.email.send_import_welcome_email', lambda inv: None)
            _import_post(client, club, 'newperson@example.com')

        user = User.query.filter_by(email='newperson@example.com').first()
        assert user is not None

    def test_new_user_added_as_active_member(self, client, club, club_admin, db):
        _login(client, club_admin.email, 'password')
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr('app.email.send_import_welcome_email', lambda inv: None)
            _import_post(client, club, 'newperson@example.com')

        user = User.query.filter_by(email='newperson@example.com').first()
        mem = ClubMembership.query.filter_by(user_id=user.id, club_id=club.id).first()
        assert mem is not None
        assert mem.status == 'active'

    def test_new_user_import_sets_batch_membership_expiration(self, client, club, club_admin, db):
        _login(client, club_admin.email, 'password')
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr('app.email.send_import_welcome_email', lambda inv: None)
            _import_post(client, club, 'paid@example.com', membership_expires_on='2026-12-31')

        user = User.query.filter_by(email='paid@example.com').first()
        mem = ClubMembership.query.filter_by(user_id=user.id, club_id=club.id).first()
        assert mem.dues_paid_until.isoformat() == '2026-12-31'

    def test_invite_token_created_with_is_new_user_true(self, client, club, club_admin, db):
        _login(client, club_admin.email, 'password')
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr('app.email.send_import_welcome_email', lambda inv: None)
            _import_post(client, club, 'newperson@example.com')

        invite = ClubInvite.query.filter_by(email='newperson@example.com').first()
        assert invite is not None
        assert invite.is_new_user is True

    def test_welcome_email_triggered(self, client, club, club_admin, db):
        _login(client, club_admin.email, 'password')
        sent = []
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr('app.routes.admin.send_import_welcome_email', lambda inv: sent.append(inv.email))
            _import_post(client, club, 'newperson@example.com')
        assert 'newperson@example.com' in sent

    def test_username_derived_from_email(self, client, club, club_admin, db):
        _login(client, club_admin.email, 'password')
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr('app.email.send_import_welcome_email', lambda inv: None)
            _import_post(client, club, 'jane.smith@example.com')
        user = User.query.filter_by(email='jane.smith@example.com').first()
        assert user.username == 'jane.smith'

    def test_duplicate_username_gets_suffix(self, client, club, club_admin, db):
        # Pre-create a user with the conflicting username
        pw = bcrypt.generate_password_hash('pw').decode()
        db.session.add(User(username='jane.smith', email='other@example.com', password_hash=pw))
        db.session.commit()

        _login(client, club_admin.email, 'password')
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr('app.email.send_import_welcome_email', lambda inv: None)
            _import_post(client, club, 'jane.smith@example.com')

        user = User.query.filter_by(email='jane.smith@example.com').first()
        assert user.username == 'jane.smith1'

    def test_results_page_shows_created_count(self, client, club, club_admin, db):
        _login(client, club_admin.email, 'password')
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr('app.email.send_import_welcome_email', lambda inv: None)
            resp = _import_post(client, club, 'newperson@example.com')
        assert b'newperson@example.com' in resp.data


# ── Existing-user import path ─────────────────────────────────────────────────

class TestExistingUserImport:
    def test_no_duplicate_account_created(self, client, club, club_admin, existing_user, db):
        _login(client, club_admin.email, 'password')
        before = User.query.filter_by(email=existing_user.email).count()
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr('app.email.send_import_invite_email', lambda inv: None)
            _import_post(client, club, existing_user.email)
        after = User.query.filter_by(email=existing_user.email).count()
        assert after == before

    def test_invite_token_created_with_is_new_user_false(self, client, club, club_admin, existing_user, db):
        _login(client, club_admin.email, 'password')
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr('app.email.send_import_invite_email', lambda inv: None)
            _import_post(client, club, existing_user.email)

        invite = ClubInvite.query.filter_by(email=existing_user.email, club_id=club.id).first()
        assert invite is not None
        assert invite.is_new_user is False

    def test_existing_user_not_auto_added_as_member(self, client, club, club_admin, existing_user, db):
        _login(client, club_admin.email, 'password')
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr('app.email.send_import_invite_email', lambda inv: None)
            _import_post(client, club, existing_user.email)

        mem = ClubMembership.query.filter_by(user_id=existing_user.id, club_id=club.id).first()
        assert mem is None

    def test_invite_email_triggered(self, client, club, club_admin, existing_user, db):
        _login(client, club_admin.email, 'password')
        sent = []
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr('app.routes.admin.send_import_invite_email', lambda inv: sent.append(inv.email))
            _import_post(client, club, existing_user.email)
        assert existing_user.email in sent

    def test_existing_user_claims_invite_joins_club(self, client, club, club_admin, existing_user, db):
        """After receiving the invite, the existing user clicks it and gets added."""
        _login(client, club_admin.email, 'password')
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr('app.email.send_import_invite_email', lambda inv: None)
            _import_post(client, club, existing_user.email)

        invite = ClubInvite.query.filter_by(email=existing_user.email, club_id=club.id).first()

        # Log in as the existing user and claim the invite
        client.post('/auth/logout')
        _login(client, existing_user.email, 'password')
        resp = client.get(f'/clubs/invites/{invite.token}', follow_redirects=True)
        assert resp.status_code == 200

        mem = ClubMembership.query.filter_by(user_id=existing_user.id, club_id=club.id).first()
        assert mem is not None
        assert mem.status == 'active'

    def test_existing_user_import_applies_row_expiration_after_claim(self, client, club, club_admin, existing_user, db):
        _login(client, club_admin.email, 'password')
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr('app.email.send_import_invite_email', lambda inv: None)
            _import_post(client, club, f'{existing_user.email}, 2027-01-15')

        invite = ClubInvite.query.filter_by(email=existing_user.email, club_id=club.id).first()
        assert invite.membership_expires_on.isoformat() == '2027-01-15'

        client.post('/auth/logout')
        _login(client, existing_user.email, 'password')
        client.get(f'/clubs/invites/{invite.token}', follow_redirects=True)

        mem = ClubMembership.query.filter_by(user_id=existing_user.id, club_id=club.id).first()
        assert mem.dues_paid_until.isoformat() == '2027-01-15'


# ── Already-member path ───────────────────────────────────────────────────────

class TestAlreadyMember:
    def test_already_member_skipped(self, client, club, club_admin, member_user, db):
        _login(client, club_admin.email, 'password')
        resp = _import_post(client, club, member_user.email)
        # No new invite created
        invite = ClubInvite.query.filter_by(email=member_user.email, club_id=club.id).first()
        assert invite is None
        assert b'Already Members' in resp.data or b'already_members' in resp.data or \
               member_user.email.encode() in resp.data


# ── Invalid / edge cases ──────────────────────────────────────────────────────

class TestEdgeCases:
    def test_invalid_email_skipped(self, client, club, club_admin, db):
        _login(client, club_admin.email, 'password')
        resp = _import_post(client, club, 'notanemail')
        assert User.query.filter_by(email='notanemail').first() is None

    def test_duplicate_emails_in_batch_deduplicated(self, client, club, club_admin, db):
        _login(client, club_admin.email, 'password')
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr('app.email.send_import_welcome_email', lambda inv: None)
            _import_post(client, club, 'dup@example.com\ndup@example.com\ndup@example.com')
        # Only one user and one invite created
        assert User.query.filter_by(email='dup@example.com').count() == 1
        assert ClubInvite.query.filter_by(email='dup@example.com').count() == 1

    def test_batch_limit_enforced(self, client, club, club_admin, db):
        _login(client, club_admin.email, 'password')
        big_batch = '\n'.join(f'user{i}@example.com' for i in range(201))
        resp = _import_post(client, club, big_batch)
        assert b'Maximum' in resp.data or b'maximum' in resp.data

    def test_mixed_batch(self, client, club, club_admin, existing_user, member_user, db):
        _login(client, club_admin.email, 'password')
        emails = f'brand.new@example.com\n{existing_user.email}\n{member_user.email}\nbadformat'
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr('app.email.send_import_welcome_email', lambda inv: None)
            mp.setattr('app.email.send_import_invite_email', lambda inv: None)
            resp = _import_post(client, club, emails)

        assert User.query.filter_by(email='brand.new@example.com').first() is not None
        assert ClubInvite.query.filter_by(email=existing_user.email, is_new_user=False).first() is not None
        assert ClubInvite.query.filter_by(email=member_user.email).first() is None


# ── setup_account route ───────────────────────────────────────────────────────

class TestSetupAccount:
    def _make_new_user_invite(self, db, club, admin_user):
        """Create a pre-imported user + invite token."""
        pw = bcrypt.generate_password_hash(secrets.token_hex(32)).decode()
        user = User(username='imported', email='imported@example.com', password_hash=pw)
        db.session.add(user)
        db.session.flush()
        db.session.add(ClubMembership(user_id=user.id, club_id=club.id, status='active'))
        invite = ClubInvite(
            club_id=club.id,
            email='imported@example.com',
            token=secrets.token_urlsafe(32),
            expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=7),
            created_by=admin_user.id,
            is_new_user=True,
        )
        db.session.add(invite)
        db.session.commit()
        return user, invite

    def test_setup_page_renders(self, client, club, club_admin, db):
        user, invite = self._make_new_user_invite(db, club, club_admin)
        resp = client.get(f'/auth/setup-account/{invite.token}')
        assert resp.status_code == 200
        assert b'Set Password' in resp.data

    def test_valid_password_logs_user_in(self, client, club, club_admin, db):
        user, invite = self._make_new_user_invite(db, club, club_admin)
        resp = client.post(f'/auth/setup-account/{invite.token}',
                           data={'password': 'newpassword1', 'confirm_password': 'newpassword1'},
                           follow_redirects=True)
        assert resp.status_code == 200
        # Should be on the club home page
        assert b'Test Club' in resp.data

    def test_invite_marked_used_after_setup(self, client, club, club_admin, db):
        user, invite = self._make_new_user_invite(db, club, club_admin)
        client.post(f'/auth/setup-account/{invite.token}',
                    data={'password': 'newpassword1', 'confirm_password': 'newpassword1'},
                    follow_redirects=True)
        db.session.refresh(invite)
        assert invite.used_at is not None
        assert invite.used_by_user_id == user.id

    def test_password_actually_set(self, client, club, club_admin, db):
        user, invite = self._make_new_user_invite(db, club, club_admin)
        client.post(f'/auth/setup-account/{invite.token}',
                    data={'password': 'newpassword1', 'confirm_password': 'newpassword1'},
                    follow_redirects=True)
        db.session.refresh(user)
        assert bcrypt.check_password_hash(user.password_hash, 'newpassword1')

    def test_mismatched_passwords_rejected(self, client, club, club_admin, db):
        user, invite = self._make_new_user_invite(db, club, club_admin)
        resp = client.post(f'/auth/setup-account/{invite.token}',
                           data={'password': 'password1', 'confirm_password': 'different'},
                           follow_redirects=True)
        assert resp.status_code == 200
        assert invite.used_at is None

    def test_already_used_token_rejected(self, client, club, club_admin, db):
        user, invite = self._make_new_user_invite(db, club, club_admin)
        invite.used_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.session.commit()
        resp = client.get(f'/auth/setup-account/{invite.token}', follow_redirects=True)
        assert b'already been used' in resp.data

    def test_expired_token_rejected(self, client, club, club_admin, db):
        user, invite = self._make_new_user_invite(db, club, club_admin)
        invite.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
        db.session.commit()
        resp = client.get(f'/auth/setup-account/{invite.token}', follow_redirects=True)
        assert b'expired' in resp.data

    def test_invite_claim_redirects_new_user_to_setup(self, client, club, club_admin, db):
        """invite_claim URL for a new-user token should redirect to setup_account."""
        user, invite = self._make_new_user_invite(db, club, club_admin)
        resp = client.get(f'/clubs/invites/{invite.token}')
        assert resp.status_code == 302
        assert '/setup-account/' in resp.headers['Location']

    def test_regular_invite_not_redirected_to_setup(self, client, club, club_admin, db):
        """A regular (is_new_user=False) invite should NOT redirect to setup_account."""
        invite = ClubInvite(
            club_id=club.id,
            email='reg@example.com',
            token=secrets.token_urlsafe(32),
            expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=7),
            created_by=club_admin.id,
            is_new_user=False,
        )
        db.session.add(invite)
        db.session.commit()
        resp = client.get(f'/clubs/invites/{invite.token}')
        # Should redirect to login (not setup_account)
        assert resp.status_code == 302
        assert '/setup-account/' not in resp.headers['Location']
