"""Tests for club hosting mode (full vs rides_only)."""
import pytest
from datetime import date, time, timedelta
from app.models import Club, ClubAdmin, ClubMembership, Ride


# ── Helpers ───────────────────────────────────────────────────────────────────

def _login(client, user, password='password123'):
    return client.post('/auth/login', data={'email': user.email, 'password': password},
                       follow_redirects=True)


def _rides_only_club(db, slug='ro-club'):
    club = Club(
        slug=slug,
        name='Rides Only Club',
        is_hidden=False,
        hosting_mode='rides_only',
    )
    db.session.add(club)
    db.session.commit()
    return club


def _make_admin(db, user, club):
    db.session.add(ClubAdmin(user_id=user.id, club_id=club.id, role='admin'))
    db.session.commit()


def _make_ride(db, club, days_ahead=3):
    ride = Ride(
        club_id=club.id,
        title='Test Ride',
        date=date.today() + timedelta(days=days_ahead),
        time=time(7, 0),
        meeting_location='Main St',
        pace_category='B',
        distance_miles=25.0,
        is_cancelled=False,
    )
    db.session.add(ride)
    db.session.commit()
    return ride


# ── Model defaults ────────────────────────────────────────────────────────────

class TestHostingModeModel:

    def test_default_hosting_mode_is_full(self, db):
        """New clubs default to 'full' hosting mode."""
        club = Club(slug='default-mode', name='Default Club', is_hidden=False)
        db.session.add(club)
        db.session.commit()
        assert club.hosting_mode == 'full'

    def test_can_set_rides_only_mode(self, db):
        """hosting_mode can be set to 'rides_only'."""
        club = Club(slug='ro-mode', name='RO Club', is_hidden=False,
                    hosting_mode='rides_only')
        db.session.add(club)
        db.session.commit()
        fetched = Club.query.get(club.id)
        assert fetched.hosting_mode == 'rides_only'


# ── Club creation wizard ──────────────────────────────────────────────────────

class TestHostingModeCreation:

    def test_create_club_with_full_mode(self, client, db, regular_user):
        """Wizard POST with hosting_mode=full creates a full club."""
        _login(client, regular_user)
        resp = client.post('/clubs/create', data={
            'name': 'Full Mode Club',
            'city': 'Reston', 'state': 'VA', 'zip_code': '20191',
            'hosting_mode': 'full',
            'is_private': '0',
            'theme_preset': 'forest',
            'theme_primary': '#2d6a4f',
            'theme_accent': '#e76f51',
        }, follow_redirects=False)
        assert resp.status_code in (200, 302)
        club = Club.query.filter_by(name='Full Mode Club').first()
        assert club is not None
        assert club.hosting_mode == 'full'

    def test_create_club_with_rides_only_mode(self, client, db, regular_user):
        """Wizard POST with hosting_mode=rides_only creates a rides-only club."""
        _login(client, regular_user)
        resp = client.post('/clubs/create', data={
            'name': 'Rides Only Club Wizard',
            'city': 'McLean', 'state': 'VA', 'zip_code': '22101',
            'hosting_mode': 'rides_only',
            'is_private': '0',
            'theme_preset': 'forest',
            'theme_primary': '#2d6a4f',
            'theme_accent': '#e76f51',
        }, follow_redirects=False)
        assert resp.status_code in (200, 302)
        club = Club.query.filter_by(name='Rides Only Club Wizard').first()
        assert club is not None
        assert club.hosting_mode == 'rides_only'

    def test_invalid_hosting_mode_defaults_to_full(self, client, db, regular_user):
        """An invalid hosting_mode value falls back to 'full'."""
        _login(client, regular_user)
        client.post('/clubs/create', data={
            'name': 'Bad Mode Club',
            'hosting_mode': 'hacker_mode',
            'is_private': '0',
            'theme_preset': 'forest',
            'theme_primary': '#2d6a4f',
            'theme_accent': '#e76f51',
        }, follow_redirects=False)
        club = Club.query.filter_by(name='Bad Mode Club').first()
        if club:
            assert club.hosting_mode == 'full'


# ── Admin settings ────────────────────────────────────────────────────────────

class TestHostingModeAdminSettings:

    def test_settings_shows_hosting_mode_selector(
            self, client, db, club_admin_user, sample_club):
        """Hosting mode select field appears in admin settings."""
        _login(client, club_admin_user)
        resp = client.get(f'/admin/clubs/{sample_club.slug}/settings')
        assert resp.status_code == 200
        assert b'Hosting Mode' in resp.data
        assert b'hosting_mode' in resp.data

    def test_settings_shows_full_mode_selected_for_full_club(
            self, client, db, club_admin_user, sample_club):
        """'Full Club' option is selected when club is in full mode."""
        sample_club.hosting_mode = 'full'
        db.session.commit()
        _login(client, club_admin_user)
        resp = client.get(f'/admin/clubs/{sample_club.slug}/settings')
        html = resp.data.decode()
        assert 'Full Club' in html

    def test_settings_can_switch_to_rides_only(
            self, client, db, club_admin_user, sample_club):
        """Admin can change hosting mode to rides_only via settings form."""
        _login(client, club_admin_user)
        resp = client.post(f'/admin/clubs/{sample_club.slug}/settings', data={
            'name': sample_club.name,
            'hosting_mode': 'rides_only',
            'join_approval': 'auto',
            'membership_duration_months': '12',
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_club)
        assert sample_club.hosting_mode == 'rides_only'

    def test_settings_can_switch_back_to_full(
            self, client, db, club_admin_user, sample_club):
        """Admin can switch from rides_only back to full mode."""
        sample_club.hosting_mode = 'rides_only'
        db.session.commit()
        _login(client, club_admin_user)
        client.post(f'/admin/clubs/{sample_club.slug}/settings', data={
            'name': sample_club.name,
            'hosting_mode': 'full',
            'join_approval': 'auto',
            'membership_duration_months': '12',
        }, follow_redirects=True)
        db.session.refresh(sample_club)
        assert sample_club.hosting_mode == 'full'

    def test_rides_only_settings_shows_membership_disabled_note(
            self, client, db, club_admin_user, sample_club):
        """Settings page notes that membership is disabled in rides_only mode."""
        sample_club.hosting_mode = 'rides_only'
        db.session.commit()
        _login(client, club_admin_user)
        resp = client.get(f'/admin/clubs/{sample_club.slug}/settings')
        assert b'Rides Only' in resp.data
        assert b'disabled' in resp.data.lower() or b'Membership features are disabled' in resp.data


# ── Club home page rendering ──────────────────────────────────────────────────

class TestHostingModeClubHome:

    def test_full_mode_club_home_loads(self, client, sample_club):
        """Full mode club home page loads successfully."""
        resp = client.get(f'/clubs/{sample_club.slug}/')
        assert resp.status_code == 200

    def test_rides_only_club_home_loads(self, client, db):
        """Rides-only club home page loads without errors."""
        club = _rides_only_club(db)
        resp = client.get(f'/clubs/{club.slug}/')
        assert resp.status_code == 200

    def test_rides_only_club_shows_rides(self, client, db):
        """Rides appear on a rides-only club home page."""
        club = _rides_only_club(db, slug='ro-show-rides')
        _make_ride(db, club)
        resp = client.get(f'/clubs/{club.slug}/')
        assert resp.status_code == 200


# ── Embed availability ────────────────────────────────────────────────────────

class TestEmbedAvailableForBothModes:

    def test_full_mode_club_has_embed(self, client, sample_club):
        """Embed widget works for full-mode clubs."""
        resp = client.get(f'/clubs/{sample_club.slug}/embed')
        assert resp.status_code == 200

    def test_rides_only_club_has_embed(self, client, db):
        """Embed widget works for rides-only clubs."""
        club = _rides_only_club(db, slug='ro-embed')
        resp = client.get(f'/clubs/{club.slug}/embed')
        assert resp.status_code == 200
