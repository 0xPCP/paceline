"""Tests for ride comment thread, invite-by-email, superadmin dashboard, and mobile CSS."""
import secrets
from datetime import datetime, timezone, timedelta
import pytest
from app.models import RideComment, ClubInvite, ClubMembership


# ── Login helper ───────────────────────────────────────────────────────────────

def _login(client, user, password='password123'):
    client.post('/auth/login', data={'email': user.email, 'password': password},
                follow_redirects=True)


# ── Ride Comments ──────────────────────────────────────────────────────────────

class TestRideComments:
    def test_comment_section_on_ride_page(self, client, sample_club, sample_rides, club_admin_user):
        ride = sample_rides[0]
        _login(client, club_admin_user)
        resp = client.get(f'/clubs/{sample_club.slug}/rides/{ride.id}')
        assert resp.status_code == 200
        assert b'Discussion' in resp.data

    def test_no_comment_form_when_unauthenticated(self, client, sample_club, sample_rides):
        ride = sample_rides[0]
        resp = client.get(f'/clubs/{sample_club.slug}/rides/{ride.id}', follow_redirects=False)
        # Unauthenticated users are now redirected to login — they cannot see the ride at all
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers.get('Location', '')

    def test_post_comment_requires_login(self, client, sample_club, sample_rides):
        ride = sample_rides[0]
        resp = client.post(
            f'/clubs/{sample_club.slug}/rides/{ride.id}/comments',
            data={'body': 'Hello'},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 403)

    def test_post_comment_authenticated(self, client, sample_club, sample_rides, club_admin_user, app):
        ride = sample_rides[0]
        _login(client, club_admin_user)
        resp = client.post(
            f'/clubs/{sample_club.slug}/rides/{ride.id}/comments',
            data={'body': 'Great route!'},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        with app.app_context():
            comment = RideComment.query.filter_by(ride_id=ride.id).first()
            assert comment is not None
            assert comment.body == 'Great route!'
            assert comment.user_id == club_admin_user.id

    def test_comment_appears_on_ride_page(self, client, sample_club, sample_rides, club_admin_user, app):
        ride = sample_rides[0]
        with app.app_context():
            from app.extensions import db
            db.session.add(RideComment(ride_id=ride.id, user_id=club_admin_user.id, body='See you there!'))
            db.session.commit()
        _login(client, club_admin_user)
        resp = client.get(f'/clubs/{sample_club.slug}/rides/{ride.id}')
        assert b'See you there!' in resp.data

    def test_author_can_delete_own_comment(self, client, sample_club, sample_rides, club_admin_user, app):
        ride = sample_rides[0]
        with app.app_context():
            from app.extensions import db
            c = RideComment(ride_id=ride.id, user_id=club_admin_user.id, body='Delete me')
            db.session.add(c)
            db.session.commit()
            cid = c.id

        _login(client, club_admin_user)
        resp = client.post(
            f'/clubs/{sample_club.slug}/rides/{ride.id}/comments/{cid}/delete',
            follow_redirects=True,
        )
        assert resp.status_code == 200
        with app.app_context():
            assert RideComment.query.get(cid) is None

    def test_other_user_cannot_delete_comment(self, client, sample_club, sample_rides,
                                               club_admin_user, regular_user, app):
        ride = sample_rides[0]
        with app.app_context():
            from app.extensions import db
            c = RideComment(ride_id=ride.id, user_id=club_admin_user.id, body='Mine')
            db.session.add(c)
            db.session.commit()
            cid = c.id

        _login(client, regular_user)
        resp = client.post(
            f'/clubs/{sample_club.slug}/rides/{ride.id}/comments/{cid}/delete',
            follow_redirects=True,
        )
        assert resp.status_code == 403
        with app.app_context():
            assert RideComment.query.get(cid) is not None

    def test_club_admin_can_delete_any_comment(self, client, sample_club, sample_rides,
                                                club_admin_user, regular_user, app):
        ride = sample_rides[0]
        with app.app_context():
            from app.extensions import db
            c = RideComment(ride_id=ride.id, user_id=regular_user.id, body='From member')
            db.session.add(c)
            db.session.commit()
            cid = c.id

        _login(client, club_admin_user)
        resp = client.post(
            f'/clubs/{sample_club.slug}/rides/{ride.id}/comments/{cid}/delete',
            follow_redirects=True,
        )
        assert resp.status_code == 200
        with app.app_context():
            assert RideComment.query.get(cid) is None

    def test_multiple_comments_ordered_oldest_first(self, client, sample_club, sample_rides,
                                                     club_admin_user, regular_user, app):
        ride = sample_rides[0]
        with app.app_context():
            from app.extensions import db
            c1 = RideComment(ride_id=ride.id, user_id=club_admin_user.id, body='First comment',
                             created_at=datetime(2025, 1, 1, 10, tzinfo=timezone.utc))
            c2 = RideComment(ride_id=ride.id, user_id=regular_user.id, body='Second comment',
                             created_at=datetime(2025, 1, 1, 11, tzinfo=timezone.utc))
            db.session.add_all([c1, c2])
            db.session.commit()

        _login(client, club_admin_user)
        resp = client.get(f'/clubs/{sample_club.slug}/rides/{ride.id}')
        body = resp.data.decode()
        assert body.index('First comment') < body.index('Second comment')


# ── Club Invites ───────────────────────────────────────────────────────────────

class TestClubInvites:
    def test_invite_page_requires_admin(self, client, sample_club):
        resp = client.get(f'/admin/clubs/{sample_club.slug}/invites')
        assert resp.status_code in (302, 403)

    def test_invite_page_accessible_to_admin(self, client, sample_club, club_admin_user):
        _login(client, club_admin_user)
        resp = client.get(f'/admin/clubs/{sample_club.slug}/invites')
        assert resp.status_code == 200
        assert b'Send New Invite' in resp.data

    def test_invite_page_lists_sent_invites(self, client, sample_club, club_admin_user, app):
        with app.app_context():
            from app.extensions import db
            invite = ClubInvite(
                club_id=sample_club.id,
                email='listed@test.com',
                token=secrets.token_urlsafe(32),
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
                created_by=club_admin_user.id,
            )
            db.session.add(invite)
            db.session.commit()

        _login(client, club_admin_user)
        resp = client.get(f'/admin/clubs/{sample_club.slug}/invites')
        assert b'listed@test.com' in resp.data

    def test_claim_invalid_token_404(self, client):
        resp = client.get('/clubs/invites/notarealtoken9999xxx')
        assert resp.status_code == 404

    def test_unauthenticated_invite_claim_redirects_to_login(self, client, sample_club,
                                                              club_admin_user, app):
        with app.app_context():
            from app.extensions import db
            token = secrets.token_urlsafe(32)
            invite = ClubInvite(
                club_id=sample_club.id,
                email='anon@example.com',
                token=token,
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
                created_by=club_admin_user.id,
            )
            db.session.add(invite)
            db.session.commit()

        resp = client.get(f'/clubs/invites/{token}')
        assert resp.status_code == 302
        assert '/login' in resp.headers['Location']

    def test_claim_valid_invite_creates_active_membership(self, client, sample_club,
                                                           club_admin_user, regular_user, app):
        with app.app_context():
            from app.extensions import db
            token = secrets.token_urlsafe(32)
            invite = ClubInvite(
                club_id=sample_club.id,
                email=regular_user.email,
                token=token,
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
                created_by=club_admin_user.id,
            )
            db.session.add(invite)
            db.session.commit()

        _login(client, regular_user)
        resp = client.get(f'/clubs/invites/{token}', follow_redirects=True)
        assert resp.status_code == 200

        with app.app_context():
            m = ClubMembership.query.filter_by(
                user_id=regular_user.id, club_id=sample_club.id
            ).first()
            assert m is not None
            assert m.status == 'active'
            inv = ClubInvite.query.filter_by(token=token).first()
            assert inv.used_at is not None
            assert inv.used_by_user_id == regular_user.id

    def test_expired_invite_rejected(self, client, sample_club, club_admin_user, regular_user, app):
        with app.app_context():
            from app.extensions import db
            token = secrets.token_urlsafe(32)
            invite = ClubInvite(
                club_id=sample_club.id,
                email=regular_user.email,
                token=token,
                expires_at=datetime.now(timezone.utc) - timedelta(days=1),
                created_by=club_admin_user.id,
            )
            db.session.add(invite)
            db.session.commit()

        _login(client, regular_user)
        resp = client.get(f'/clubs/invites/{token}', follow_redirects=True)
        assert resp.status_code == 200
        assert b'expired' in resp.data.lower()

        with app.app_context():
            m = ClubMembership.query.filter_by(
                user_id=regular_user.id, club_id=sample_club.id
            ).first()
            assert m is None

    def test_used_invite_rejected(self, client, sample_club, club_admin_user, regular_user, app):
        with app.app_context():
            from app.extensions import db
            token = secrets.token_urlsafe(32)
            invite = ClubInvite(
                club_id=sample_club.id,
                email=regular_user.email,
                token=token,
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
                created_by=club_admin_user.id,
                used_at=datetime.now(timezone.utc),
                used_by_user_id=regular_user.id,
            )
            db.session.add(invite)
            db.session.commit()

        _login(client, regular_user)
        resp = client.get(f'/clubs/invites/{token}', follow_redirects=True)
        assert b'already been used' in resp.data.lower()

    def test_pending_member_upgraded_to_active_via_invite(self, client, sample_club,
                                                            club_admin_user, regular_user, app):
        """Inviting a pending member promotes them to active."""
        with app.app_context():
            from app.extensions import db
            db.session.add(ClubMembership(
                user_id=regular_user.id, club_id=sample_club.id, status='pending'
            ))
            token = secrets.token_urlsafe(32)
            invite = ClubInvite(
                club_id=sample_club.id,
                email=regular_user.email,
                token=token,
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
                created_by=club_admin_user.id,
            )
            db.session.add(invite)
            db.session.commit()

        _login(client, regular_user)
        client.get(f'/clubs/invites/{token}', follow_redirects=True)

        with app.app_context():
            m = ClubMembership.query.filter_by(
                user_id=regular_user.id, club_id=sample_club.id
            ).first()
            assert m.status == 'active'


# ── Superadmin Dashboard ───────────────────────────────────────────────────────

class TestSuperadminDashboard:
    def test_dashboard_shows_extended_stats(self, client, sample_club, admin_user):
        _login(client, admin_user, 'password123')
        resp = client.get('/admin/')
        assert resp.status_code == 200
        assert b'Active Clubs' in resp.data
        assert b'Total Distance Hosted' in resp.data

    def test_dashboard_shows_club_table_with_upcoming_col(self, client, sample_club, admin_user):
        _login(client, admin_user, 'password123')
        resp = client.get('/admin/')
        assert resp.status_code == 200
        assert b'Upcoming' in resp.data
        assert b'Status' in resp.data

    def test_dashboard_shows_created_date(self, client, sample_club, admin_user):
        _login(client, admin_user, 'password123')
        resp = client.get('/admin/')
        assert resp.status_code == 200
        assert b'Created' in resp.data

    def test_dashboard_shows_private_badge_for_private_club(self, client, admin_user, app):
        with app.app_context():
            from app.extensions import db
            club = ClubInvite.__table__.metadata  # just to confirm app context works
            from app.models import Club
            private = Club(slug='private-test', name='Private Club',
                           is_private=True, is_active=True)
            db.session.add(private)
            db.session.commit()

        _login(client, admin_user, 'password123')
        resp = client.get('/admin/')
        assert b'Private' in resp.data

    def test_new_users_30d_shown(self, client, admin_user, regular_user):
        _login(client, admin_user, 'password123')
        resp = client.get('/admin/')
        assert b'last 30 days' in resp.data


# ── Mobile CSS ─────────────────────────────────────────────────────────────────

class TestMobileCSS:
    def test_ride_card_css_classes_defined(self, client):
        resp = client.get('/static/css/style.css')
        assert resp.status_code == 200
        css = resp.data
        for cls in [b'.ride-card', b'.ride-date-block', b'.rdb-month', b'.rdb-day',
                    b'.ride-title', b'.ride-meta']:
            assert cls in css, f'{cls} not found in style.css'

    def test_comment_thread_css_defined(self, client):
        resp = client.get('/static/css/style.css')
        css = resp.data
        for cls in [b'.comment-thread', b'.comment-item', b'.comment-avatar',
                    b'.comment-body', b'.comment-text']:
            assert cls in css, f'{cls} not found in style.css'

    def test_mobile_breakpoint_exists(self, client):
        resp = client.get('/static/css/style.css')
        assert b'max-width: 575px' in resp.data
        assert b'.ride-card' in resp.data
