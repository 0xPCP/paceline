"""
Tests for club creation wizard, permission roles, private club access,
and team/member management routes.
"""
import pytest
from unittest.mock import patch
from tests.conftest import login, logout
from app.models import Club, ClubAdmin, ClubMembership, ClubOwnershipTransfer


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def ride_manager(db, sample_club, regular_user):
    """regular_user gets ride_manager role on sample_club."""
    db.session.add(ClubAdmin(user_id=regular_user.id, club_id=sample_club.id, role='ride_manager'))
    db.session.commit()
    return regular_user


@pytest.fixture
def full_admin(db, sample_club, club_admin_user):
    return club_admin_user  # already has role='admin'


# ── Club creation wizard ──────────────────────────────────────────────────────

def test_create_page_requires_login(client):
    r = client.get('/clubs/create', follow_redirects=True)
    assert b'Sign In' in r.data


def test_create_page_renders_for_logged_in(client, regular_user):
    login(client)
    r = client.get('/clubs/create')
    assert r.status_code == 200
    assert b'Create a Club' in r.data
    assert b'Club Name' in r.data
    assert b'Forest' in r.data  # theme preset visible


def test_create_wizard_shows_all_preset_themes(client, regular_user):
    login(client)
    r = client.get('/clubs/create')
    for label in [b'Forest', b'Ocean', b'Slate', b'Sunset', b'Crimson', b'Desert']:
        assert label in r.data


def test_create_club_success(client, db, regular_user):
    login(client)
    r = client.post('/clubs/create', data={
        'name': 'Test Wizard Club',
        'city': 'Reston', 'state': 'VA', 'zip_code': '20191',
        'is_private': '0',
        'theme_preset': 'forest',
        'theme_primary': '#2d6a4f',
        'theme_accent': '#e76f51',
        'description': 'A club created in tests.',
        'contact_email': '',
        'website': '',
        'logo_url': '',
        'banner_url': '',
    }, follow_redirects=True)
    assert b'Test Wizard Club' in r.data

    club = Club.query.filter_by(name='Test Wizard Club').first()
    assert club is not None
    assert club.slug == 'test-wizard-club'
    assert club.theme_preset == 'forest'
    assert club.theme_primary == '#2d6a4f'
    assert club.is_private is False


def test_create_private_club(client, db, regular_user):
    login(client)
    client.post('/clubs/create', data={
        'name': 'Secret Riders',
        'city': '', 'state': '', 'zip_code': '',
        'is_private': '1',
        'theme_preset': 'slate',
        'theme_primary': '#2c3e50',
        'theme_accent': '#27ae60',
        'description': '',
        'contact_email': '', 'website': '', 'logo_url': '', 'banner_url': '',
    }, follow_redirects=True)
    club = Club.query.filter_by(name='Secret Riders').first()
    assert club.is_private is True


def test_create_club_creator_becomes_admin_and_member(client, db, regular_user):
    login(client)
    client.post('/clubs/create', data={
        'name': 'Admin Check Club',
        'city': '', 'state': '', 'zip_code': '',
        'is_private': '0',
        'theme_preset': 'ocean',
        'theme_primary': '#1a5276',
        'theme_accent': '#f39c12',
        'description': '', 'contact_email': '', 'website': '',
        'logo_url': '', 'banner_url': '',
    }, follow_redirects=True)
    club = Club.query.filter_by(name='Admin Check Club').first()
    admin_row = ClubAdmin.query.filter_by(user_id=regular_user.id, club_id=club.id).first()
    member_row = ClubMembership.query.filter_by(user_id=regular_user.id, club_id=club.id).first()
    assert admin_row is not None
    assert admin_row.role == 'admin'
    assert member_row is not None


def test_create_club_name_required(client, regular_user):
    login(client)
    r = client.post('/clubs/create', data={
        'name': '',
        'city': '', 'state': '', 'zip_code': '',
        'is_private': '0',
        'theme_preset': 'forest',
        'theme_primary': '#2d6a4f',
        'theme_accent': '#e76f51',
        'description': '', 'contact_email': '', 'website': '',
        'logo_url': '', 'banner_url': '',
    }, follow_redirects=True)
    assert r.status_code == 200
    # Should stay on create page, not redirect to dashboard
    assert b'Create a Club' in r.data


def test_create_club_custom_theme(client, db, regular_user):
    login(client)
    client.post('/clubs/create', data={
        'name': 'Custom Theme Club',
        'city': '', 'state': '', 'zip_code': '',
        'is_private': '0',
        'theme_preset': 'custom',
        'theme_primary': '#ff0000',
        'theme_accent': '#0000ff',
        'description': '', 'contact_email': '', 'website': '',
        'logo_url': '', 'banner_url': '',
    }, follow_redirects=True)
    club = Club.query.filter_by(name='Custom Theme Club').first()
    assert club.theme_preset == 'custom'
    assert club.theme_primary == '#ff0000'
    assert club.theme_accent == '#0000ff'


def test_slug_auto_generated(client, db, regular_user):
    login(client)
    client.post('/clubs/create', data={
        'name': 'Slug Test Club!!! 123',
        'city': '', 'state': '', 'zip_code': '',
        'is_private': '0', 'theme_preset': 'forest',
        'theme_primary': '#2d6a4f', 'theme_accent': '#e76f51',
        'description': '', 'contact_email': '', 'website': '',
        'logo_url': '', 'banner_url': '',
    }, follow_redirects=True)
    club = Club.query.filter_by(name='Slug Test Club!!! 123').first()
    assert club.slug == 'slug-test-club-123'


# ── Permission model ──────────────────────────────────────────────────────────

def test_is_club_admin_returns_true_for_admin_role(db, sample_club, club_admin_user):
    assert club_admin_user.is_club_admin(sample_club) is True


def test_is_club_admin_returns_false_for_ride_manager(db, sample_club, ride_manager):
    assert ride_manager.is_club_admin(sample_club) is False


def test_is_ride_manager_true_for_ride_manager(db, sample_club, ride_manager):
    assert ride_manager.is_ride_manager(sample_club) is True


def test_is_ride_manager_false_for_full_admin(db, sample_club, club_admin_user):
    assert club_admin_user.is_ride_manager(sample_club) is False


def test_can_manage_rides_true_for_both_roles(db, sample_club, club_admin_user, ride_manager):
    assert club_admin_user.can_manage_rides(sample_club) is True
    assert ride_manager.can_manage_rides(sample_club) is True


def test_global_superadmin_is_always_club_admin(db, sample_club, admin_user):
    assert admin_user.is_club_admin(sample_club) is True
    assert admin_user.can_manage_rides(sample_club) is True


# ── Ride manager access ───────────────────────────────────────────────────────

def test_ride_manager_can_access_club_dashboard(client, db, sample_club, ride_manager, mock_weather):
    login(client, email='rider@test.com')
    r = client.get(f'/admin/clubs/{sample_club.slug}/')
    assert r.status_code == 200


def test_ride_manager_can_access_ride_new_page(client, db, sample_club, ride_manager):
    login(client, email='rider@test.com')
    r = client.get(f'/admin/clubs/{sample_club.slug}/rides/new')
    assert r.status_code == 200


def test_ride_manager_cannot_access_club_settings(client, db, sample_club, ride_manager):
    login(client, email='rider@test.com')
    r = client.get(f'/admin/clubs/{sample_club.slug}/settings')
    assert r.status_code == 403


def test_ride_manager_cannot_access_club_team(client, db, sample_club, ride_manager):
    login(client, email='rider@test.com')
    r = client.get(f'/admin/clubs/{sample_club.slug}/team')
    assert r.status_code == 403


def test_non_admin_cannot_access_dashboard(client, sample_club, regular_user):
    login(client)
    r = client.get(f'/admin/clubs/{sample_club.slug}/')
    assert r.status_code == 403


# ── Private club join flow ────────────────────────────────────────────────────

def test_private_club_shows_private_badge(client, db, sample_club):
    sample_club.is_private = True
    from app.extensions import db as _db
    _db.session.commit()
    r = client.get(f'/clubs/{sample_club.slug}/')
    assert b'Private' in r.data


def test_private_club_still_shows_join_button(client, db, sample_club, regular_user):
    # Private clubs are now joinable — they just hide route details from non-members
    sample_club.is_private = True
    from app.extensions import db as _db
    _db.session.commit()
    login(client)
    r = client.get(f'/clubs/{sample_club.slug}/')
    assert b'Join Club' in r.data


def test_public_club_shows_join_button_for_non_member(client, sample_club, regular_user):
    login(client)
    r = client.get(f'/clubs/{sample_club.slug}/')
    assert b'Join Club' in r.data


# ── Team management routes ────────────────────────────────────────────────────

def test_club_team_page_accessible_to_full_admin(client, sample_club, full_admin):
    login(client, email='clubadmin@test.com')
    r = client.get(f'/admin/clubs/{sample_club.slug}/team')
    assert r.status_code == 200
    assert b'Admin Team' in r.data


def test_club_team_add_user(client, db, sample_club, full_admin, regular_user):
    login(client, email='clubadmin@test.com')
    r = client.post(f'/admin/clubs/{sample_club.slug}/team/add', data={
        'identifier': regular_user.email,
        'role': 'ride_manager',
    }, follow_redirects=True)
    assert r.status_code == 200
    row = ClubAdmin.query.filter_by(user_id=regular_user.id, club_id=sample_club.id).first()
    assert row is not None
    assert row.role == 'ride_manager'


def test_club_team_add_nonexistent_user(client, sample_club, full_admin):
    login(client, email='clubadmin@test.com')
    r = client.post(f'/admin/clubs/{sample_club.slug}/team/add', data={
        'identifier': 'nobody@nowhere.com',
        'role': 'admin',
    }, follow_redirects=True)
    assert b'No user found' in r.data


def test_club_member_add(client, db, sample_club, full_admin, regular_user):
    login(client, email='clubadmin@test.com')
    r = client.post(f'/admin/clubs/{sample_club.slug}/members/add', data={
        'identifier': regular_user.username,
    }, follow_redirects=True)
    assert r.status_code == 200
    row = ClubMembership.query.filter_by(user_id=regular_user.id, club_id=sample_club.id).first()
    assert row is not None


def test_club_member_remove(client, db, sample_club, full_admin, regular_user):
    # First add the member
    db.session.add(ClubMembership(user_id=regular_user.id, club_id=sample_club.id))
    db.session.commit()
    login(client, email='clubadmin@test.com')
    r = client.post(f'/admin/clubs/{sample_club.slug}/members/{regular_user.id}/remove',
                    follow_redirects=True)
    assert r.status_code == 200
    row = ClubMembership.query.filter_by(user_id=regular_user.id, club_id=sample_club.id).first()
    assert row is None


def test_club_owner_can_request_ownership_transfer_by_email(client, db, sample_club, full_admin, second_user):
    login(client, email='clubadmin@test.com')
    with patch('app.routes.admin.send_club_ownership_transfer_email') as send_email:
        r = client.post(f'/admin/clubs/{sample_club.slug}/team/transfer-owner', data={
            'email': second_user.email,
            'confirm_email': second_user.email,
        }, follow_redirects=True)

    assert r.status_code == 200
    assert b'Ownership transfer sent' in r.data
    transfer = ClubOwnershipTransfer.query.filter_by(
        club_id=sample_club.id,
        to_user_id=second_user.id,
        status='pending',
    ).first()
    assert transfer is not None
    send_email.assert_called_once()


def test_club_owner_transfer_requires_matching_email_confirmation(client, db, sample_club, full_admin, second_user):
    login(client, email='clubadmin@test.com')
    r = client.post(f'/admin/clubs/{sample_club.slug}/team/transfer-owner', data={
        'email': second_user.email,
        'confirm_email': 'different@test.com',
    }, follow_redirects=True)

    assert r.status_code == 200
    assert b'Email confirmation must match' in r.data
    assert ClubOwnershipTransfer.query.count() == 0


def test_ownership_transfer_accept_requires_target_user(client, db, sample_club, full_admin, second_user, regular_user):
    transfer = ClubOwnershipTransfer(
        club_id=sample_club.id,
        from_user_id=full_admin.id,
        to_user_id=second_user.id,
    )
    db.session.add(transfer)
    db.session.commit()

    login(client, email=regular_user.email)
    r = client.post(f'/admin/ownership-transfer/{transfer.token}', follow_redirects=True)

    assert r.status_code == 200
    assert b'this ownership transfer was sent to' in r.data
    db.session.refresh(sample_club)
    assert sample_club.owner_id is None
    assert transfer.status == 'pending'


def test_ownership_transfer_accept_sets_owner_membership_and_admin(client, db, sample_club, full_admin, second_user):
    transfer = ClubOwnershipTransfer(
        club_id=sample_club.id,
        from_user_id=full_admin.id,
        to_user_id=second_user.id,
    )
    db.session.add(transfer)
    db.session.commit()

    login(client, email=second_user.email)
    r = client.post(f'/admin/ownership-transfer/{transfer.token}', follow_redirects=True)

    assert r.status_code == 200
    assert b'You are now the owner' in r.data
    db.session.refresh(sample_club)
    assert sample_club.owner_id == second_user.id
    admin_row = ClubAdmin.query.filter_by(user_id=second_user.id, club_id=sample_club.id).first()
    assert admin_row is not None
    assert admin_row.role == 'admin'
    member_row = ClubMembership.query.filter_by(user_id=second_user.id, club_id=sample_club.id).first()
    assert member_row is not None
    assert member_row.status == 'active'
    db.session.refresh(transfer)
    assert transfer.status == 'accepted'
