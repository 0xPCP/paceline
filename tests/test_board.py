"""Tests for the club board feature."""
import pytest
from app.models import ClubBoardPost, ClubBoardSubscription
from app.extensions import db as _db


def _login(client, email, password='password123'):
    return client.post('/auth/login', data={'email': email, 'password': password},
                       follow_redirects=True)


def _make_member(db, user, club):
    from app.models import ClubMembership
    db.session.add(ClubMembership(user_id=user.id, club_id=club.id, status='active'))
    db.session.commit()


def _make_post(db, user, club, body='Test post'):
    post = ClubBoardPost(club_id=club.id, author_id=user.id, body=body)
    db.session.add(post)
    db.session.commit()
    return post


# ── Access control ────────────────────────────────────────────────────────────

def test_board_requires_login(client, sample_club):
    r = client.get(f'/clubs/{sample_club.slug}/board/')
    assert r.status_code == 302
    assert b'/auth/login' in r.data or r.headers.get('Location', '').endswith('/auth/login') \
        or '/auth/login' in r.headers.get('Location', '')


def test_board_requires_membership(client, db, regular_user, sample_club):
    _login(client, regular_user.email)
    r = client.get(f'/clubs/{sample_club.slug}/board/')
    assert r.status_code == 403


def test_board_accessible_to_member(client, db, regular_user, sample_club):
    _make_member(db, regular_user, sample_club)
    _login(client, regular_user.email)
    r = client.get(f'/clubs/{sample_club.slug}/board/')
    assert r.status_code == 200
    assert b'Share something' in r.data


def test_board_accessible_to_club_admin(client, db, club_admin_user, sample_club):
    _make_member(db, club_admin_user, sample_club)
    _login(client, club_admin_user.email)
    r = client.get(f'/clubs/{sample_club.slug}/board/')
    assert r.status_code == 200


# ── Create post ───────────────────────────────────────────────────────────────

def test_create_post(client, db, regular_user, sample_club):
    _make_member(db, regular_user, sample_club)
    _login(client, regular_user.email)
    r = client.post(f'/clubs/{sample_club.slug}/board/',
                    data={'body': 'Hello club!'},
                    follow_redirects=True)
    assert r.status_code == 200
    post = ClubBoardPost.query.filter_by(club_id=sample_club.id).first()
    assert post is not None
    assert post.body == 'Hello club!'
    assert post.author_id == regular_user.id


def test_create_post_empty_body(client, db, regular_user, sample_club):
    _make_member(db, regular_user, sample_club)
    _login(client, regular_user.email)
    r = client.post(f'/clubs/{sample_club.slug}/board/',
                    data={'body': '   '},
                    follow_redirects=True)
    assert r.status_code == 200
    assert ClubBoardPost.query.filter_by(club_id=sample_club.id).count() == 0


def test_create_post_non_member_forbidden(client, db, regular_user, sample_club):
    _login(client, regular_user.email)
    r = client.post(f'/clubs/{sample_club.slug}/board/',
                    data={'body': 'Hello!'},
                    follow_redirects=True)
    assert r.status_code == 403
    assert ClubBoardPost.query.count() == 0


# ── Delete post ───────────────────────────────────────────────────────────────

def test_delete_own_post(client, db, regular_user, sample_club):
    _make_member(db, regular_user, sample_club)
    post = _make_post(db, regular_user, sample_club)
    post_id = post.id
    _login(client, regular_user.email)
    r = client.post(f'/clubs/{sample_club.slug}/board/{post_id}/delete',
                    follow_redirects=True)
    assert r.status_code == 200
    assert db.session.get(ClubBoardPost, post_id) is None


def test_delete_other_post_forbidden(client, db, regular_user, second_user, sample_club):
    _make_member(db, regular_user, sample_club)
    _make_member(db, second_user, sample_club)
    post = _make_post(db, second_user, sample_club)
    post_id = post.id
    _login(client, regular_user.email)
    r = client.post(f'/clubs/{sample_club.slug}/board/{post_id}/delete',
                    follow_redirects=True)
    assert r.status_code == 403
    assert db.session.get(ClubBoardPost, post_id) is not None


def test_admin_can_delete_any_post(client, db, club_admin_user, regular_user, sample_club):
    _make_member(db, club_admin_user, sample_club)
    _make_member(db, regular_user, sample_club)
    post = _make_post(db, regular_user, sample_club)
    post_id = post.id
    _login(client, club_admin_user.email)
    r = client.post(f'/clubs/{sample_club.slug}/board/{post_id}/delete',
                    follow_redirects=True)
    assert r.status_code == 200
    assert db.session.get(ClubBoardPost, post_id) is None


# ── Pin post ──────────────────────────────────────────────────────────────────

def test_pin_post_admin_only(client, db, club_admin_user, sample_club):
    _make_member(db, club_admin_user, sample_club)
    post = _make_post(db, club_admin_user, sample_club)
    _login(client, club_admin_user.email)
    client.post(f'/clubs/{sample_club.slug}/board/{post.id}/pin', follow_redirects=True)
    db.session.refresh(post)
    assert post.is_pinned is True
    # Toggle off
    client.post(f'/clubs/{sample_club.slug}/board/{post.id}/pin', follow_redirects=True)
    db.session.refresh(post)
    assert post.is_pinned is False


def test_pin_post_non_admin_forbidden(client, db, regular_user, sample_club):
    _make_member(db, regular_user, sample_club)
    post = _make_post(db, regular_user, sample_club)
    _login(client, regular_user.email)
    r = client.post(f'/clubs/{sample_club.slug}/board/{post.id}/pin', follow_redirects=True)
    assert r.status_code == 403
    db.session.refresh(post)
    assert post.is_pinned is False


# ── Subscribe / unsubscribe ───────────────────────────────────────────────────

def test_subscribe_toggle(client, db, regular_user, sample_club):
    _make_member(db, regular_user, sample_club)
    _login(client, regular_user.email)

    # Subscribe
    client.post(f'/clubs/{sample_club.slug}/board/subscribe', follow_redirects=True)
    sub = ClubBoardSubscription.query.filter_by(
        club_id=sample_club.id, user_id=regular_user.id).first()
    assert sub is not None

    # Unsubscribe
    client.post(f'/clubs/{sample_club.slug}/board/subscribe', follow_redirects=True)
    sub = ClubBoardSubscription.query.filter_by(
        club_id=sample_club.id, user_id=regular_user.id).first()
    assert sub is None


def test_subscribe_non_member_forbidden(client, db, regular_user, sample_club):
    _login(client, regular_user.email)
    r = client.post(f'/clubs/{sample_club.slug}/board/subscribe', follow_redirects=True)
    assert r.status_code == 403


# ── Pagination ────────────────────────────────────────────────────────────────

def test_board_shows_15_posts_by_default(client, db, regular_user, sample_club):
    _make_member(db, regular_user, sample_club)
    for i in range(20):
        db.session.add(ClubBoardPost(
            club_id=sample_club.id, author_id=regular_user.id, body=f'Post {i}'))
    db.session.commit()
    _login(client, regular_user.email)
    r = client.get(f'/clubs/{sample_club.slug}/board/')
    assert r.status_code == 200
    assert b'Load older posts' in r.data


def test_board_before_param_accepted(client, db, regular_user, sample_club):
    _make_member(db, regular_user, sample_club)
    post = _make_post(db, regular_user, sample_club)
    _login(client, regular_user.email)
    r = client.get(f'/clubs/{sample_club.slug}/board/?before={post.id + 999}')
    assert r.status_code == 200


# ── Home page board tab ───────────────────────────────────────────────────────

def test_home_board_tab_visible_to_member(client, db, regular_user, sample_club, mock_weather):
    _make_member(db, regular_user, sample_club)
    _login(client, regular_user.email)
    r = client.get(f'/clubs/{sample_club.slug}/')
    assert r.status_code == 200
    assert b'tab-board' in r.data


def test_home_board_tab_hidden_from_non_member(client, db, regular_user, sample_club, mock_weather):
    _login(client, regular_user.email)
    r = client.get(f'/clubs/{sample_club.slug}/')
    assert r.status_code == 200
    assert b'tab-board' not in r.data


def test_home_shows_board_posts_for_member(client, db, regular_user, sample_club, mock_weather):
    _make_member(db, regular_user, sample_club)
    _make_post(db, regular_user, sample_club, body='A test announcement')
    _login(client, regular_user.email)
    r = client.get(f'/clubs/{sample_club.slug}/')
    assert r.status_code == 200
    assert b'A test announcement' in r.data
