"""
Tests for profile privacy and club members page.
"""
import pytest
from datetime import date, time, timedelta
from app.models import User, Club, ClubMembership, ClubAdmin, Ride, RideSignup
from app.extensions import db
from tests.conftest import login


# ── Profile privacy ───────────────────────────────────────────────────────────

class TestProfilePrivacy:
    def test_private_profile_hides_details_from_stranger(self, client, regular_user, second_user):
        # default is private
        login(client)
        resp = client.get(f'/users/{second_user.username}')
        assert resp.status_code == 200
        assert b'This profile is private' in resp.data
        assert b'Ride history is private' in resp.data

    def test_public_profile_visible_to_all(self, client, db, regular_user, second_user):
        second_user.profile_is_public = True
        db.session.commit()
        login(client)
        resp = client.get(f'/users/{second_user.username}')
        assert b'This profile is private' not in resp.data
        assert b'Member since' in resp.data

    def test_private_profile_visible_to_accepted_friend(self, client, db, regular_user, second_user):
        from app.models import UserFriend
        db.session.add(UserFriend(requester_id=regular_user.id, addressee_id=second_user.id, status='accepted'))
        db.session.commit()
        login(client)
        resp = client.get(f'/users/{second_user.username}')
        assert b'This profile is private' not in resp.data
        assert b'Member since' in resp.data

    def test_own_profile_always_visible(self, client, regular_user):
        login(client)
        resp = client.get(f'/users/{regular_user.username}')
        assert b'This profile is private' not in resp.data
        assert b'Member since' in resp.data

    def test_private_profile_shows_add_friend_prompt(self, client, regular_user, second_user):
        login(client)
        resp = client.get(f'/users/{second_user.username}')
        assert b'Add Friend to view profile' in resp.data

    def test_pending_request_shows_pending_message(self, client, db, regular_user, second_user):
        from app.models import UserFriend
        db.session.add(UserFriend(requester_id=regular_user.id, addressee_id=second_user.id, status='pending'))
        db.session.commit()
        login(client)
        resp = client.get(f'/users/{second_user.username}')
        assert b'pending' in resp.data.lower()


# ── Club members page ─────────────────────────────────────────────────────────

class TestClubMembersPage:
    def _add_member(self, db, user, club, status='active'):
        db.session.add(ClubMembership(user_id=user.id, club_id=club.id, status=status))
        db.session.commit()

    def test_members_page_returns_200(self, client, sample_club, regular_user, db):
        self._add_member(db, regular_user, sample_club)
        resp = client.get(f'/clubs/{sample_club.slug}/members/')
        assert resp.status_code == 200

    def test_members_page_shows_active_members(self, client, db, sample_club, regular_user, second_user):
        self._add_member(db, regular_user, sample_club)
        self._add_member(db, second_user, sample_club)
        resp = client.get(f'/clubs/{sample_club.slug}/members/')
        assert b'rider' in resp.data
        assert b'rider2' in resp.data

    def test_owner_shown_in_owner_section(self, client, db, sample_club, regular_user):
        sample_club.owner_id = regular_user.id
        self._add_member(db, regular_user, sample_club)
        db.session.commit()
        resp = client.get(f'/clubs/{sample_club.slug}/members/')
        assert b'Club Owner' in resp.data

    def test_admin_shown_in_admins_section(self, client, db, sample_club, regular_user, second_user):
        self._add_member(db, regular_user, sample_club)
        self._add_member(db, second_user, sample_club)
        db.session.add(ClubAdmin(user_id=regular_user.id, club_id=sample_club.id, role='admin'))
        db.session.commit()
        resp = client.get(f'/clubs/{sample_club.slug}/members/')
        assert b'Admins' in resp.data

    def test_private_club_members_requires_membership(self, client, db, sample_club, regular_user):
        sample_club.is_private = True
        db.session.commit()
        resp = client.get(f'/clubs/{sample_club.slug}/members/')
        assert resp.status_code == 403

    def test_private_club_members_visible_to_member(self, client, db, sample_club, regular_user):
        sample_club.is_private = True
        self._add_member(db, regular_user, sample_club)
        db.session.commit()
        login(client)
        resp = client.get(f'/clubs/{sample_club.slug}/members/')
        assert resp.status_code == 200

    def test_member_count_is_linked(self, client, db, sample_club, regular_user):
        self._add_member(db, regular_user, sample_club)
        resp = client.get(f'/clubs/{sample_club.slug}/')
        assert b'members/' in resp.data

    def test_public_profile_members_have_links(self, client, db, sample_club, regular_user):
        regular_user.profile_is_public = True
        self._add_member(db, regular_user, sample_club)
        db.session.commit()
        resp = client.get(f'/clubs/{sample_club.slug}/members/')
        assert f'/users/{regular_user.username}'.encode() in resp.data

    def test_private_profile_members_have_no_link(self, client, db, sample_club, regular_user):
        regular_user.profile_is_public = False
        self._add_member(db, regular_user, sample_club)
        db.session.commit()
        resp = client.get(f'/clubs/{sample_club.slug}/members/')
        assert f'/users/{regular_user.username}'.encode() not in resp.data
