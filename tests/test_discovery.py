"""Tests for cross-club ride discovery, club stats, leader roster, sponsors, and role expansion."""
import pytest
from datetime import date, time, timedelta
from app.models import Club, Ride, ClubLeader, ClubSponsor, ClubAdmin, ClubMembership
from tests.conftest import login


# ── Club stats ────────────────────────────────────────────────────────────────

class TestClubStats:
    def test_stats_shown_on_home(self, client, sample_club, sample_rides, mock_weather):
        r = client.get(f'/clubs/{sample_club.slug}/')
        assert r.status_code == 200
        # Stats are now in the stats band (csi-label elements), no longer a "Club Stats" card
        assert b'Members' in r.data
        assert b'Rides Hosted' in r.data

    def test_stats_total_rides_count(self, client, db, sample_club, mock_weather):
        today = date.today()
        for i in range(3):
            db.session.add(Ride(
                club_id=sample_club.id, title=f'Ride {i}',
                date=today + timedelta(days=i+1), time=time(9, 0),
                meeting_location='Park', distance_miles=20.0, pace_category='B',
            ))
        db.session.commit()
        r = client.get(f'/clubs/{sample_club.slug}/')
        assert b'3' in r.data  # total_rides = 3


# ── Ride discovery ────────────────────────────────────────────────────────────

class TestDiscovery:
    def test_discover_page_loads(self, client, mock_weather):
        r = client.get('/discover/')
        assert r.status_code == 200
        assert b'Discover Rides' in r.data

    def test_discover_shows_upcoming_rides(self, client, db, sample_club, mock_weather):
        ride = Ride(
            club_id=sample_club.id, title='Discover Me',
            date=date.today() + timedelta(days=2), time=time(8, 0),
            meeting_location='HQ', distance_miles=30.0, pace_category='B',
        )
        db.session.add(ride)
        db.session.commit()
        r = client.get('/discover/?range=week')
        assert r.status_code == 200
        assert b'Discover Me' in r.data

    def test_discover_pace_filter(self, client, db, sample_club, mock_weather):
        for pace in ('A', 'C'):
            db.session.add(Ride(
                club_id=sample_club.id, title=f'Pace {pace} Ride',
                date=date.today() + timedelta(days=2), time=time(8, 0),
                meeting_location='HQ', distance_miles=30.0, pace_category=pace,
            ))
        db.session.commit()
        r = client.get('/discover/?range=week&pace=A')
        assert b'Pace A Ride' in r.data
        assert b'Pace C Ride' not in r.data

    def test_discover_type_filter(self, client, db, sample_club, mock_weather):
        db.session.add(Ride(
            club_id=sample_club.id, title='Gravel Adventure',
            date=date.today() + timedelta(days=2), time=time(8, 0),
            meeting_location='HQ', distance_miles=40.0, pace_category='B',
            ride_type='gravel',
        ))
        db.session.add(Ride(
            club_id=sample_club.id, title='Road Sprint',
            date=date.today() + timedelta(days=2), time=time(8, 0),
            meeting_location='HQ', distance_miles=40.0, pace_category='A',
            ride_type='road',
        ))
        db.session.commit()
        r = client.get('/discover/?range=week&type=gravel')
        assert b'Gravel Adventure' in r.data
        assert b'Road Sprint' not in r.data

    def test_discover_excludes_past_rides(self, client, db, sample_club, mock_weather):
        db.session.add(Ride(
            club_id=sample_club.id, title='Old Ride',
            date=date.today() - timedelta(days=1), time=time(8, 0),
            meeting_location='HQ', distance_miles=20.0, pace_category='C',
        ))
        db.session.commit()
        r = client.get('/discover/?range=week')
        assert b'Old Ride' not in r.data

    def test_discover_excludes_cancelled(self, client, db, sample_club, mock_weather):
        db.session.add(Ride(
            club_id=sample_club.id, title='Cancelled Ride',
            date=date.today() + timedelta(days=2), time=time(8, 0),
            meeting_location='HQ', distance_miles=20.0, pace_category='C',
            is_cancelled=True,
        ))
        db.session.commit()
        r = client.get('/discover/?range=week')
        assert b'Cancelled Ride' not in r.data

    def test_discover_nav_link_present(self, client, mock_weather):
        r = client.get('/')
        assert b'Discover Rides' in r.data

    def test_discover_club_only_filter_hides_user_rides(self, client, db, sample_club, regular_user, mock_weather):
        """club_only=1 should exclude personal user rides."""
        from app.models import User as UserModel
        club_ride = Ride(
            club_id=sample_club.id, title='Club Group Ride',
            date=date.today() + timedelta(days=2), time=time(8, 0),
            meeting_location='HQ', distance_miles=30.0, pace_category='B',
        )
        personal_ride = Ride(
            owner_id=regular_user.id, title='My Personal Ride',
            date=date.today() + timedelta(days=2), time=time(9, 0),
            meeting_location='Start', distance_miles=25.0, pace_category='C',
            is_private=False,
        )
        db.session.add_all([club_ride, personal_ride])
        db.session.commit()

        r = client.get('/discover/?range=week&club_only=1')
        assert b'Club Group Ride' in r.data
        assert b'My Personal Ride' not in r.data

    def test_discover_without_club_only_shows_user_rides(self, client, db, sample_club, regular_user, mock_weather):
        """Without club_only filter, personal public rides should appear."""
        personal_ride = Ride(
            owner_id=regular_user.id, title='Public Personal Ride',
            date=date.today() + timedelta(days=2), time=time(9, 0),
            meeting_location='Start', distance_miles=25.0, pace_category='C',
            is_private=False,
        )
        db.session.add(personal_ride)
        db.session.commit()

        r = client.get('/discover/?range=week')
        assert b'Public Personal Ride' in r.data

    def test_discover_club_logo_url_shown(self, client, db, sample_club, mock_weather):
        """Club logo URL should appear in ride card when club has a logo."""
        sample_club.logo_url = 'https://example.com/logo.png'
        db.session.commit()

        db.session.add(Ride(
            club_id=sample_club.id, title='Logo Test Ride',
            date=date.today() + timedelta(days=2), time=time(8, 0),
            meeting_location='HQ', distance_miles=20.0, pace_category='B',
        ))
        db.session.commit()

        r = client.get('/discover/?range=week')
        assert b'Logo Test Ride' in r.data
        assert b'example.com/logo.png' in r.data

    def test_discover_club_no_logo_shows_name(self, client, db, sample_club, mock_weather):
        """When club has no logo, its name should still be shown as text."""
        sample_club.logo_url = None
        sample_club.logo_key = None
        db.session.commit()

        db.session.add(Ride(
            club_id=sample_club.id, title='No Logo Ride',
            date=date.today() + timedelta(days=2), time=time(8, 0),
            meeting_location='HQ', distance_miles=20.0, pace_category='B',
        ))
        db.session.commit()

        r = client.get('/discover/?range=week')
        assert b'No Logo Ride' in r.data
        assert sample_club.name.encode() in r.data

    def test_discover_club_only_button_shown(self, client, mock_weather):
        """Club Rides Only filter button should be rendered on the page."""
        r = client.get('/discover/')
        assert b'Club Rides Only' in r.data

    def test_discover_favicon_in_base(self, client, mock_weather):
        """Favicon .ico link should be present in discover page (extends base.html)."""
        r = client.get('/discover/')
        assert b'favicon.ico' in r.data
        assert b'apple-touch-icon' in r.data


# ── Ride leader roster ────────────────────────────────────────────────────────

class TestLeaderRoster:
    def test_add_leader(self, client, db, sample_club, club_admin_user):
        login(client, email=club_admin_user.email)
        r = client.post(f'/admin/clubs/{sample_club.slug}/leaders/new', data={
            'name': 'Dave K.',
            'bio': 'Fast wheels since 2008.',
            'photo_url': '',
            'display_order': 0,
        }, follow_redirects=True)
        assert r.status_code == 200
        assert b'Leader added' in r.data
        assert ClubLeader.query.filter_by(club_id=sample_club.id, name='Dave K.').first() is not None

    def test_edit_leader(self, client, db, sample_club, club_admin_user):
        login(client, email=club_admin_user.email)
        leader = ClubLeader(club_id=sample_club.id, name='Old Name', display_order=0)
        db.session.add(leader)
        db.session.commit()
        r = client.post(f'/admin/clubs/{sample_club.slug}/leaders/{leader.id}/edit', data={
            'name': 'New Name', 'bio': '', 'photo_url': '', 'display_order': 1,
        }, follow_redirects=True)
        assert b'Leader updated' in r.data
        db.session.refresh(leader)
        assert leader.name == 'New Name'

    def test_delete_leader(self, client, db, sample_club, club_admin_user):
        login(client, email=club_admin_user.email)
        leader = ClubLeader(club_id=sample_club.id, name='Gone Guy', display_order=0)
        db.session.add(leader)
        db.session.commit()
        lid = leader.id
        r = client.post(f'/admin/clubs/{sample_club.slug}/leaders/{lid}/delete',
                        follow_redirects=True)
        assert b'Leader removed' in r.data
        assert ClubLeader.query.get(lid) is None

    def test_public_leaders_page(self, client, db, sample_club, club_admin_user):
        db.session.add(ClubLeader(club_id=sample_club.id, name='Public Leader',
                                   bio='A great rider.', display_order=0))
        db.session.commit()
        r = client.get(f'/clubs/{sample_club.slug}/leaders/')
        assert r.status_code == 200
        assert b'Public Leader' in r.data
        assert b'A great rider.' in r.data

    def test_leaders_preview_on_home(self, client, db, sample_club, mock_weather):
        db.session.add(ClubLeader(club_id=sample_club.id, name='Home Preview Leader',
                                   display_order=0))
        db.session.commit()
        r = client.get(f'/clubs/{sample_club.slug}/')
        assert b'Home Preview Leader' in r.data

    def test_leader_admin_requires_club_admin(self, client, sample_club, regular_user):
        login(client, email=regular_user.email)
        r = client.get(f'/admin/clubs/{sample_club.slug}/leaders', follow_redirects=True)
        assert r.status_code == 403


# ── Sponsors ──────────────────────────────────────────────────────────────────

class TestSponsors:
    def test_add_sponsor(self, client, db, sample_club, club_admin_user):
        login(client, email=club_admin_user.email)
        r = client.post(f'/admin/clubs/{sample_club.slug}/sponsors/new', data={
            'name': "Conte's Bike Shop",
            'logo_url': '',
            'website': '',
            'display_order': 0,
        }, follow_redirects=True)
        assert b'Sponsor added' in r.data
        assert ClubSponsor.query.filter_by(club_id=sample_club.id).first() is not None

    def test_sponsors_shown_on_home(self, client, db, sample_club, mock_weather):
        db.session.add(ClubSponsor(club_id=sample_club.id, name='Big Sponsor Co.',
                                    display_order=0))
        db.session.commit()
        r = client.get(f'/clubs/{sample_club.slug}/')
        assert b'Big Sponsor Co.' in r.data
        assert b'Partners' in r.data


# ── Roles expansion ───────────────────────────────────────────────────────────

def _make_user_with_role(db, sample_club, role):
    from app.extensions import bcrypt
    from app.models import User
    u = User(
        username=f'user_{role}', email=f'{role}@test.com',
        password_hash=bcrypt.generate_password_hash('password123').decode(),
    )
    db.session.add(u)
    db.session.commit()
    db.session.add(ClubAdmin(user_id=u.id, club_id=sample_club.id, role=role))
    db.session.commit()
    return u


class TestRoleExpansion:
    def test_content_editor_can_access_posts(self, client, db, sample_club):
        editor = _make_user_with_role(db, sample_club, 'content_editor')
        login(client, email=editor.email)
        r = client.get(f'/admin/clubs/{sample_club.slug}/posts')
        assert r.status_code == 200

    def test_content_editor_cannot_access_settings(self, client, db, sample_club):
        editor = _make_user_with_role(db, sample_club, 'content_editor')
        login(client, email=editor.email)
        r = client.get(f'/admin/clubs/{sample_club.slug}/settings')
        assert r.status_code == 403

    def test_treasurer_can_export_members(self, client, db, sample_club):
        treasurer = _make_user_with_role(db, sample_club, 'treasurer')
        login(client, email=treasurer.email)
        r = client.get(f'/admin/clubs/{sample_club.slug}/members/export')
        assert r.status_code == 200
        assert b'Username' in r.data

    def test_treasurer_cannot_access_settings(self, client, db, sample_club):
        treasurer = _make_user_with_role(db, sample_club, 'treasurer')
        login(client, email=treasurer.email)
        r = client.get(f'/admin/clubs/{sample_club.slug}/settings')
        assert r.status_code == 403

    def test_ride_manager_cannot_access_posts(self, client, db, sample_club):
        rm = _make_user_with_role(db, sample_club, 'ride_manager')
        login(client, email=rm.email)
        r = client.get(f'/admin/clubs/{sample_club.slug}/posts')
        assert r.status_code == 403

    def test_role_badge_shown_in_team_page(self, client, db, sample_club, club_admin_user):
        login(client, email=club_admin_user.email)
        editor = _make_user_with_role(db, sample_club, 'content_editor')
        r = client.get(f'/admin/clubs/{sample_club.slug}/team')
        assert b'Content Editor' in r.data

    def test_new_roles_accepted_in_team_add(self, client, db, sample_club, club_admin_user, regular_user):
        login(client, email=club_admin_user.email)
        r = client.post(f'/admin/clubs/{sample_club.slug}/team/add', data={
            'identifier': regular_user.email,
            'role': 'content_editor',
        }, follow_redirects=True)
        assert r.status_code == 200
        row = ClubAdmin.query.filter_by(user_id=regular_user.id, club_id=sample_club.id).first()
        assert row is not None
        assert row.role == 'content_editor'
