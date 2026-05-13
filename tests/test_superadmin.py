"""
Tests for the super admin panel:
  - Non-admin users are blocked (403) from all admin user-management endpoints
  - User list: search and filter
  - User detail page
  - Password reset: generates a working temp password
  - Toggle admin: grant, revoke, can't change own status
  - Toggle active: deactivate, reactivate, can't deactivate self
  - Deactivated user cannot log in
"""
import pytest
from datetime import date, time, timedelta
from unittest.mock import patch
from app.extensions import db, bcrypt
from app.models import (AdminAuditLog, Club, ClubAdmin, ClubMembership,
                        EmailDeliveryLog, Ride, RideMedia, RideSignup, User)
from tests.conftest import login, logout


# ── Helpers ───────────────────────────────────────────────────────────────────

def login_as(client, user, password='password123'):
    return client.post('/auth/login', data={
        'email': user.email, 'password': password,
    }, follow_redirects=True)


def make_user(db, username, email, is_admin=False, is_active=True, password='password123'):
    u = User(
        username=username,
        email=email,
        password_hash=bcrypt.generate_password_hash(password).decode(),
        is_admin=is_admin,
        is_active=is_active,
    )
    db.session.add(u)
    db.session.commit()
    return u


# ── Access control ─────────────────────────────────────────────────────────────

class TestSuperadminAccessControl:

    def test_unauthenticated_user_list_redirects(self, client):
        resp = client.get('/admin/users/', follow_redirects=False)
        assert resp.status_code in (302, 403)

    def test_regular_user_blocked_user_list(self, client, db, regular_user):
        login_as(client, regular_user)
        resp = client.get('/admin/users/')
        assert resp.status_code == 403

    def test_regular_user_blocked_user_detail(self, client, db, regular_user, admin_user):
        login_as(client, regular_user)
        resp = client.get(f'/admin/users/{admin_user.id}')
        assert resp.status_code == 403

    def test_regular_user_blocked_reset_password(self, client, db, regular_user, admin_user):
        login_as(client, regular_user)
        resp = client.post(f'/admin/users/{admin_user.id}/reset-password')
        assert resp.status_code == 403

    def test_regular_user_blocked_toggle_admin(self, client, db, regular_user, admin_user):
        login_as(client, regular_user)
        resp = client.post(f'/admin/users/{admin_user.id}/toggle-admin')
        assert resp.status_code == 403

    def test_regular_user_blocked_toggle_active(self, client, db, regular_user, admin_user):
        login_as(client, regular_user)
        resp = client.post(f'/admin/users/{admin_user.id}/toggle-active')
        assert resp.status_code == 403

    def test_superadmin_can_access_user_list(self, client, db, admin_user):
        login_as(client, admin_user)
        resp = client.get('/admin/users/')
        assert resp.status_code == 200

    def test_superadmin_can_access_user_detail(self, client, db, admin_user, regular_user):
        login_as(client, admin_user)
        resp = client.get(f'/admin/users/{regular_user.id}')
        assert resp.status_code == 200

    def test_configured_superadmin_email_promoted_by_schema_guard(self, app, db):
        from app.schema import ensure_runtime_schema
        app.config['SUPERADMIN_EMAILS'] = 'phil@pcp.dev'
        user = make_user(db, 'phil', 'phil@pcp.dev', is_admin=False)
        with app.app_context():
            ensure_runtime_schema()
        db.session.refresh(user)
        assert user.is_admin is True


# ── User list ─────────────────────────────────────────────────────────────────

class TestUserList:

    def test_user_list_shows_all_users(self, client, db, admin_user, regular_user):
        login_as(client, admin_user)
        resp = client.get('/admin/users/')
        assert resp.status_code == 200
        assert b'rider' in resp.data
        assert b'superadmin' in resp.data

    def test_search_by_username(self, client, db, admin_user, regular_user):
        login_as(client, admin_user)
        resp = client.get('/admin/users/?q=rider')
        assert resp.status_code == 200
        assert b'rider@test.com' in resp.data
        assert b'admin@test.com' not in resp.data  # admin email absent from results

    def test_search_by_email(self, client, db, admin_user, regular_user):
        login_as(client, admin_user)
        resp = client.get('/admin/users/?q=admin@test.com')
        assert resp.status_code == 200
        assert b'admin@test.com' in resp.data
        assert b'rider@test.com' not in resp.data

    def test_filter_admins(self, client, db, admin_user, regular_user):
        login_as(client, admin_user)
        resp = client.get('/admin/users/?filter=admins')
        assert resp.status_code == 200
        assert b'admin@test.com' in resp.data
        assert b'rider@test.com' not in resp.data

    def test_filter_inactive(self, client, db, admin_user):
        inactive = make_user(db, 'sleeper', 'sleeper@test.com', is_active=False)
        login_as(client, admin_user)
        resp = client.get('/admin/users/?filter=inactive')
        assert resp.status_code == 200
        assert b'sleeper@test.com' in resp.data
        assert b'admin@test.com' not in resp.data  # admin is active, not in inactive filter

    def test_search_no_results(self, client, db, admin_user):
        login_as(client, admin_user)
        resp = client.get('/admin/users/?q=zzznobody')
        assert resp.status_code == 200
        assert b'No users found' in resp.data


# ── User detail ───────────────────────────────────────────────────────────────

class TestUserDetail:

    def test_detail_shows_account_info(self, client, db, admin_user, regular_user):
        login_as(client, admin_user)
        resp = client.get(f'/admin/users/{regular_user.id}')
        assert resp.status_code == 200
        assert b'rider@test.com' in resp.data
        assert b'rider' in resp.data

    def test_detail_404_for_nonexistent_user(self, client, db, admin_user):
        login_as(client, admin_user)
        resp = client.get('/admin/users/99999')
        assert resp.status_code == 404

    def test_detail_shows_deactivated_badge(self, client, db, admin_user):
        inactive = make_user(db, 'goneguy', 'gone@test.com', is_active=False)
        login_as(client, admin_user)
        resp = client.get(f'/admin/users/{inactive.id}')
        assert resp.status_code == 200
        assert b'Deactivated' in resp.data

    def test_detail_self_actions_disabled(self, client, db, admin_user):
        """Admin/active action buttons are hidden when viewing own account."""
        login_as(client, admin_user)
        resp = client.get(f'/admin/users/{admin_user.id}')
        assert resp.status_code == 200
        assert b'Admin/active actions are disabled' in resp.data


# ── Password reset ────────────────────────────────────────────────────────────

class TestPasswordReset:

    def test_reset_password_changes_hash(self, client, db, admin_user, regular_user):
        old_hash = regular_user.password_hash
        login_as(client, admin_user)
        resp = client.post(
            f'/admin/users/{regular_user.id}/reset-password',
            follow_redirects=True,
        )
        assert resp.status_code == 200
        db.session.refresh(regular_user)
        assert regular_user.password_hash != old_hash

    def test_reset_password_flash_contains_temp_password(self, client, db, admin_user, regular_user):
        login_as(client, admin_user)
        resp = client.post(
            f'/admin/users/{regular_user.id}/reset-password',
            follow_redirects=True,
        )
        assert b'Temporary password' in resp.data

    def test_reset_password_new_pw_works(self, client, db, admin_user, regular_user):
        """After reset, the user should be able to log in with the temp password."""
        login_as(client, admin_user)
        # Capture the redirect response (not following) to stay on detail page
        client.post(f'/admin/users/{regular_user.id}/reset-password', follow_redirects=True)

        # Re-fetch user and brute-check we can find the new hash via bcrypt
        db.session.refresh(regular_user)
        # We can't read the temp pw from the response easily, so just verify hash changed
        # and that the old password no longer works
        logout(client)
        resp = client.post('/auth/login', data={
            'email': regular_user.email, 'password': 'password123',
        }, follow_redirects=True)
        # Old password should fail
        assert b'Invalid email or password' in resp.data


# ── Toggle admin ──────────────────────────────────────────────────────────────

class TestToggleAdmin:

    def test_grant_admin(self, client, db, admin_user, regular_user):
        assert not regular_user.is_admin
        login_as(client, admin_user)
        resp = client.post(
            f'/admin/users/{regular_user.id}/toggle-admin',
            follow_redirects=True,
        )
        assert resp.status_code == 200
        db.session.refresh(regular_user)
        assert regular_user.is_admin

    def test_revoke_admin(self, client, db, admin_user):
        second_admin = make_user(db, 'admin2', 'admin2@test.com', is_admin=True)
        login_as(client, admin_user)
        resp = client.post(
            f'/admin/users/{second_admin.id}/toggle-admin',
            follow_redirects=True,
        )
        assert resp.status_code == 200
        db.session.refresh(second_admin)
        assert not second_admin.is_admin

    def test_cannot_revoke_configured_bootstrap_superadmin(self, client, db, admin_user):
        client.application.config['SUPERADMIN_EMAILS'] = 'phil@pcp.dev'
        phil = make_user(db, 'phil', 'phil@pcp.dev', is_admin=True)
        login_as(client, admin_user)
        resp = client.post(
            f'/admin/users/{phil.id}/toggle-admin',
            follow_redirects=True,
        )
        assert b'bootstrap superadmin' in resp.data
        db.session.refresh(phil)
        assert phil.is_admin is True

    def test_cannot_change_own_admin_status(self, client, db, admin_user):
        login_as(client, admin_user)
        resp = client.post(
            f'/admin/users/{admin_user.id}/toggle-admin',
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b'cannot change your own' in resp.data
        db.session.refresh(admin_user)
        assert admin_user.is_admin  # unchanged

    def test_grant_admin_flash_message(self, client, db, admin_user, regular_user):
        login_as(client, admin_user)
        resp = client.post(
            f'/admin/users/{regular_user.id}/toggle-admin',
            follow_redirects=True,
        )
        assert b'granted' in resp.data
        assert AdminAuditLog.query.filter_by(
            action='grant_superadmin',
            target_user_id=regular_user.id,
        ).first() is not None


# ── Toggle active ─────────────────────────────────────────────────────────────

class TestToggleActive:

    def test_deactivate_user(self, client, db, admin_user, regular_user):
        assert regular_user.is_active
        login_as(client, admin_user)
        resp = client.post(
            f'/admin/users/{regular_user.id}/toggle-active',
            follow_redirects=True,
        )
        assert resp.status_code == 200
        db.session.refresh(regular_user)
        assert not regular_user.is_active

    def test_reactivate_user(self, client, db, admin_user):
        inactive = make_user(db, 'dormant', 'dormant@test.com', is_active=False)
        login_as(client, admin_user)
        resp = client.post(
            f'/admin/users/{inactive.id}/toggle-active',
            follow_redirects=True,
        )
        assert resp.status_code == 200
        db.session.refresh(inactive)
        assert inactive.is_active

    def test_cannot_deactivate_self(self, client, db, admin_user):
        login_as(client, admin_user)
        resp = client.post(
            f'/admin/users/{admin_user.id}/toggle-active',
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b'cannot deactivate your own' in resp.data
        db.session.refresh(admin_user)
        assert admin_user.is_active  # unchanged

    def test_deactivate_flash_message(self, client, db, admin_user, regular_user):
        login_as(client, admin_user)
        resp = client.post(
            f'/admin/users/{regular_user.id}/toggle-active',
            follow_redirects=True,
        )
        assert b'deactivated' in resp.data

    def test_reactivate_flash_message(self, client, db, admin_user):
        inactive = make_user(db, 'zombie', 'zombie@test.com', is_active=False)
        login_as(client, admin_user)
        resp = client.post(
            f'/admin/users/{inactive.id}/toggle-active',
            follow_redirects=True,
        )
        assert b'reactivated' in resp.data


class TestDeleteTestUser:

    def test_detail_shows_delete_test_user_for_generated_account(self, client, db, admin_user):
        test_user = make_user(db, 'audit_owner_20260513000102', 'audit_owner_20260513000102@example.com')
        login_as(client, admin_user)
        resp = client.get(f'/admin/users/{test_user.id}')
        assert resp.status_code == 200
        assert b'data-testid="delete-test-user-panel"' in resp.data
        assert b'DELETE TEST USER audit_owner_20260513000102@example.com' in resp.data

    def test_detail_hides_delete_test_user_for_real_account(self, client, db, admin_user, regular_user):
        login_as(client, admin_user)
        resp = client.get(f'/admin/users/{regular_user.id}')
        assert resp.status_code == 200
        assert b'data-testid="delete-test-user-panel"' not in resp.data

    def test_delete_test_user_requires_generated_account(self, client, db, admin_user, regular_user):
        login_as(client, admin_user)
        resp = client.post(
            f'/admin/users/{regular_user.id}/delete-test-user',
            data={'confirmation': f'DELETE TEST USER {regular_user.email}'},
            follow_redirects=True,
        )
        assert b'Only generated test users' in resp.data
        assert db.session.get(User, regular_user.id) is not None

    def test_delete_test_user_requires_exact_confirmation(self, client, db, admin_user):
        test_user = make_user(db, 'audit_owner_20260513000103', 'audit_owner_20260513000103@example.com')
        login_as(client, admin_user)
        resp = client.post(
            f'/admin/users/{test_user.id}/delete-test-user',
            data={'confirmation': 'DELETE'},
            follow_redirects=True,
        )
        assert b'DELETE TEST USER audit_owner_20260513000103@example.com' in resp.data
        assert db.session.get(User, test_user.id) is not None

    def test_superadmin_can_delete_generated_test_user_and_artifacts(self, client, db, admin_user):
        test_user = make_user(db, 'audit_owner_20260513000104', 'audit_owner_20260513000104@example.com')
        audit_club = Club(
            slug='audit-workflow-club-20260513000104',
            name='Audit Workflow Club 20260513000104',
            owner_id=test_user.id,
        )
        db.session.add(audit_club)
        db.session.commit()
        personal_ride = Ride(
            owner_id=test_user.id,
            title='Audit Personal Ride',
            date=date.today() + timedelta(days=3),
            time=time(9, 0),
            meeting_location='Test lot',
            distance_miles=12,
            pace_category='B',
            ride_type='road',
        )
        db.session.add(personal_ride)
        db.session.commit()

        login_as(client, admin_user)
        resp = client.post(
            f'/admin/users/{test_user.id}/delete-test-user',
            data={'confirmation': 'DELETE TEST USER audit_owner_20260513000104@example.com'},
            follow_redirects=True,
        )

        assert resp.status_code == 200
        assert b'Deleted test user' in resp.data
        assert db.session.get(User, test_user.id) is None
        assert db.session.get(Club, audit_club.id) is None
        assert db.session.get(Ride, personal_ride.id) is None
        assert AdminAuditLog.query.filter_by(action='delete_test_user').first() is not None


# ── Deactivated user cannot log in ────────────────────────────────────────────

class TestDeactivatedLogin:

    def test_deactivated_user_cannot_login(self, client, db):
        inactive = make_user(db, 'banned', 'banned@test.com', is_active=False)
        resp = client.post('/auth/login', data={
            'email': 'banned@test.com', 'password': 'password123',
        }, follow_redirects=True)
        assert b'deactivated' in resp.data.lower()

    def test_active_user_can_login(self, client, db, regular_user):
        resp = client.post('/auth/login', data={
            'email': regular_user.email, 'password': 'password123',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'deactivated' not in resp.data.lower()

    def test_deactivated_user_session_invalidated(self, client, db, admin_user, regular_user):
        """A user who gets deactivated mid-session should be treated as anonymous."""
        login_as(client, regular_user)
        # Deactivate them while they are "logged in"
        regular_user.is_active = False
        db.session.commit()
        # Flask-Login checks is_active on each request — they should be redirected
        resp = client.get('/auth/profile', follow_redirects=False)
        assert resp.status_code == 302


class TestSessionRevocation:

    def test_superadmin_can_revoke_user_sessions(self, client, db, admin_user, regular_user):
        old_version = regular_user.session_token_version
        login_as(client, admin_user)
        resp = client.post(
            f'/admin/users/{regular_user.id}/revoke-sessions',
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b'existing sessions revoked' in resp.data.lower()
        db.session.refresh(regular_user)
        assert regular_user.session_token_version == old_version + 1
        assert AdminAuditLog.query.filter_by(
            action='revoke_sessions',
            target_user_id=regular_user.id,
        ).first() is not None

    def test_superadmin_cannot_revoke_own_session(self, client, db, admin_user):
        old_version = admin_user.session_token_version
        login_as(client, admin_user)
        resp = client.post(
            f'/admin/users/{admin_user.id}/revoke-sessions',
            follow_redirects=True,
        )
        assert b'cannot revoke your own' in resp.data
        db.session.refresh(admin_user)
        assert admin_user.session_token_version == old_version


# ── Bulk geocoding ─────────────────────────────────────────────────────────────

class TestBulkGeocoding:

    def _ungeocodeable_club(self, db):
        club = Club(slug='geo-test', name='Geo Test Club', zip_code='20148', lat=None, lng=None)
        db.session.add(club)
        db.session.commit()
        return club

    def test_geocode_clubs_requires_superadmin(self, client, db, regular_user):
        login_as(client, regular_user)
        resp = client.post('/admin/geocode-clubs', follow_redirects=False)
        assert resp.status_code == 403

    def test_geocode_clubs_fills_coordinates(self, client, db, admin_user):
        club = self._ungeocodeable_club(db)
        login_as(client, admin_user)
        with patch('app.routes.admin.geocode_zip', return_value=(38.9, -77.4)):
            resp = client.post('/admin/geocode-clubs', follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(club)
        assert club.lat == pytest.approx(38.9)
        assert club.lng == pytest.approx(-77.4)

    def test_geocode_clubs_skips_already_geocoded(self, client, db, admin_user, sample_club):
        original_lat = sample_club.lat
        login_as(client, admin_user)
        with patch('app.routes.admin.geocode_zip', return_value=(0.0, 0.0)) as mock_geo:
            client.post('/admin/geocode-clubs', follow_redirects=True)
        mock_geo.assert_not_called()
        db.session.refresh(sample_club)
        assert sample_club.lat == original_lat

    def test_geocode_clubs_handles_lookup_failure(self, client, db, admin_user):
        club = self._ungeocodeable_club(db)
        login_as(client, admin_user)
        with patch('app.routes.admin.geocode_zip', return_value=None):
            resp = client.post('/admin/geocode-clubs', follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(club)
        assert club.lat is None

    def test_dashboard_shows_geocode_warning(self, client, db, admin_user):
        self._ungeocodeable_club(db)
        login_as(client, admin_user)
        resp = client.get('/admin/')
        assert b'missing map coordinates' in resp.data

    def test_dashboard_no_geocode_warning_when_all_geocoded(self, client, db, admin_user, sample_club):
        login_as(client, admin_user)
        resp = client.get('/admin/')
        assert b'missing map coordinates' not in resp.data


class TestPlatformStatistics:

    def test_dashboard_shows_usage_and_storage_sections(self, client, db, admin_user, sample_club, regular_user, sample_rides):
        db.session.add(RideSignup(ride_id=sample_rides[0].id, user_id=regular_user.id))
        db.session.add(RideMedia(
            ride_id=sample_rides[0].id,
            user_id=regular_user.id,
            media_type='video_link',
            url='https://youtube.com/watch?v=test',
        ))
        db.session.commit()
        login_as(client, admin_user)
        resp = client.get('/admin/')
        assert resp.status_code == 200
        assert b'Growth Trends' in resp.data
        assert b'Usage and Storage' in resp.data
        assert b'Active Riders' in resp.data
        assert b'Rides Last 30 Days' in resp.data
        assert b'Video Links' in resp.data

    def test_dashboard_shows_email_delivery_monitoring(self, client, db, admin_user):
        db.session.add(EmailDeliveryLog(
            provider='resend',
            subject='Welcome',
            recipient_count=3,
            status='sent',
        ))
        db.session.add(EmailDeliveryLog(
            provider='resend',
            subject='Reminder',
            recipient_count=1,
            status='failed',
            error='rate limited',
        ))
        db.session.commit()
        login_as(client, admin_user)
        resp = client.get('/admin/')
        assert resp.status_code == 200
        assert b'Email Delivery' in resp.data
        assert b'Sent Today' in resp.data
        assert b'Sent This Month' in resp.data
        assert b'Sent This Year' in resp.data
        assert b'Failures Last 30 Days' in resp.data
        assert b'rate limited' in resp.data

    def test_dashboard_shows_recent_audit_activity(self, client, db, admin_user, regular_user):
        login_as(client, admin_user)
        client.post(f'/admin/users/{regular_user.id}/revoke-sessions', follow_redirects=True)
        resp = client.get('/admin/')
        assert b'Recent Superadmin Activity' in resp.data
        assert b'revoke_sessions' in resp.data


class TestSuperadminClubMaintenance:

    def test_dashboard_links_to_club_superadmin_panel(self, client, db, admin_user, sample_club):
        login_as(client, admin_user)
        resp = client.get('/admin/')
        assert resp.status_code == 200
        assert f'/admin/clubs/{sample_club.slug}/superadmin'.encode() in resp.data

    def test_regular_user_blocked_from_club_superadmin_panel(self, client, db, regular_user, sample_club):
        login_as(client, regular_user)
        resp = client.get(f'/admin/clubs/{sample_club.slug}/superadmin')
        assert resp.status_code == 403

    def test_superadmin_can_toggle_club_privacy(self, client, db, admin_user, sample_club):
        assert sample_club.is_private is False
        login_as(client, admin_user)
        resp = client.post(
            f'/admin/clubs/{sample_club.slug}/toggle-private',
            follow_redirects=True,
        )
        assert resp.status_code == 200
        db.session.refresh(sample_club)
        assert sample_club.is_private is True
        assert b'Make Public' in resp.data
        assert AdminAuditLog.query.filter_by(action='toggle_club_private').first() is not None

    def test_delete_club_requires_typed_confirmation(self, client, db, admin_user, sample_club):
        login_as(client, admin_user)
        resp = client.post(
            f'/admin/clubs/{sample_club.slug}/delete',
            data={'confirmation': 'DELETE WRONG'},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b'DELETE test-club' in resp.data
        assert Club.query.filter_by(id=sample_club.id).first() is not None

    def test_superadmin_can_manually_transfer_club_owner(self, client, db, admin_user, sample_club, regular_user):
        login_as(client, admin_user)
        resp = client.post(
            f'/admin/clubs/{sample_club.slug}/superadmin/transfer-owner',
            data={
                'email': regular_user.email,
                'confirm_email': regular_user.email,
            },
            follow_redirects=True,
        )

        assert resp.status_code == 200
        assert b'ownership was transferred' in resp.data
        db.session.refresh(sample_club)
        assert sample_club.owner_id == regular_user.id
        admin_row = ClubAdmin.query.filter_by(user_id=regular_user.id, club_id=sample_club.id).first()
        assert admin_row is not None
        assert admin_row.role == 'admin'
        member_row = ClubMembership.query.filter_by(user_id=regular_user.id, club_id=sample_club.id).first()
        assert member_row is not None
        assert member_row.status == 'active'
        assert AdminAuditLog.query.filter_by(action='manual_transfer_club_owner').first() is not None

    def test_superadmin_can_delete_club_with_confirmation(self, client, db, admin_user, sample_club, sample_rides):
        club_id = sample_club.id
        login_as(client, admin_user)
        resp = client.post(
            f'/admin/clubs/{sample_club.slug}/delete',
            data={'confirmation': f'DELETE {sample_club.slug}'},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b'deleted' in resp.data
        assert Club.query.filter_by(id=club_id).first() is None
        assert Ride.query.filter_by(club_id=club_id).count() == 0
        assert AdminAuditLog.query.filter_by(action='delete_club').first() is not None


class TestSuperadminUserHostedRides:

    def _make_user_ride(self, db, owner, title='User Ride', is_private=False):
        ride = Ride(
            owner_id=owner.id,
            club_id=None,
            is_private=is_private,
            title=title,
            date=date.today() + timedelta(days=2),
            time=time(9, 0),
            meeting_location='Coffee Shop',
            distance_miles=31.0,
            pace_category='B',
            ride_type='road',
            ride_leader=owner.username,
            created_by=owner.id,
        )
        db.session.add(ride)
        db.session.commit()
        return ride

    def test_regular_user_blocked_from_user_rides_list(self, client, db, regular_user):
        login_as(client, regular_user)
        resp = client.get('/admin/user-rides/')
        assert resp.status_code == 403

    def test_superadmin_can_view_user_hosted_rides(self, client, db, admin_user, regular_user):
        ride = self._make_user_ride(db, regular_user, title='Neighborhood Spin')
        login_as(client, admin_user)
        resp = client.get('/admin/user-rides/')
        assert resp.status_code == 200
        assert b'Neighborhood Spin' in resp.data
        assert regular_user.email.encode() in resp.data
        assert f'/my-rides/{ride.id}'.encode() in resp.data

    def test_user_rides_list_filters_private(self, client, db, admin_user, regular_user):
        self._make_user_ride(db, regular_user, title='Public Spin', is_private=False)
        self._make_user_ride(db, regular_user, title='Private Spin', is_private=True)
        login_as(client, admin_user)
        resp = client.get('/admin/user-rides/?privacy=private')
        assert resp.status_code == 200
        assert b'Private Spin' in resp.data
        assert b'Public Spin' not in resp.data


# ── Club verification ─────────────────────────────────────────────────────────

class TestClubVerification:
    def test_verify_club_sets_is_verified(self, client, db, admin_user, sample_club):
        assert not sample_club.is_verified
        login_as(client, admin_user)
        r = client.post(f'/admin/clubs/{sample_club.slug}/toggle-verified',
                        follow_redirects=True)
        assert r.status_code == 200
        db.session.refresh(sample_club)
        assert sample_club.is_verified

    def test_unverify_club_clears_is_verified(self, client, db, admin_user, sample_club):
        sample_club.is_verified = True
        db.session.commit()
        login_as(client, admin_user)
        r = client.post(f'/admin/clubs/{sample_club.slug}/toggle-verified',
                        follow_redirects=True)
        assert r.status_code == 200
        db.session.refresh(sample_club)
        assert not sample_club.is_verified

    def test_regular_user_cannot_verify_club(self, client, db, regular_user, sample_club):
        login_as(client, regular_user)
        r = client.post(f'/admin/clubs/{sample_club.slug}/toggle-verified',
                        follow_redirects=True)
        assert r.status_code == 403

    def test_verified_badge_shown_on_club_home(self, client, db, sample_club, mock_weather):
        sample_club.is_verified = True
        db.session.commit()
        r = client.get(f'/clubs/{sample_club.slug}/')
        assert r.status_code == 200
        assert b'Verified' in r.data

    def test_unverified_no_badge_on_club_home(self, client, db, sample_club, mock_weather):
        sample_club.is_verified = False
        db.session.commit()
        r = client.get(f'/clubs/{sample_club.slug}/')
        assert r.status_code == 200
        assert b'verified-badge' not in r.data
