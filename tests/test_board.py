"""Tests for the club board feature."""
import io
import time
import pytest
from app.models import (ClubBoardPost, ClubBoardMedia,
                        ClubBoardReaction, ClubBoardReply, ClubBoardSubscription)
from app.extensions import db as _db


def _minimal_jpeg():
    """Minimal valid JPEG (1×1 red pixel) for upload tests."""
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (1, 1), color=(255, 0, 0)).save(buf, format='JPEG')
    return buf.getvalue()


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


def test_create_post_photo_only(client, db, regular_user, sample_club, app, tmp_path):
    """Posting a photo with no text body should succeed."""
    app.config['UPLOAD_FOLDER'] = str(tmp_path)
    _make_member(db, regular_user, sample_club)
    _login(client, regular_user.email)
    r = client.post(
        f'/clubs/{sample_club.slug}/board/',
        data={'body': '  ', 'photos': (io.BytesIO(_minimal_jpeg()), 'photo.jpg')},
        content_type='multipart/form-data',
        follow_redirects=True,
    )
    assert r.status_code == 200
    post = ClubBoardPost.query.filter_by(club_id=sample_club.id).first()
    assert post is not None
    assert post.body is None
    assert ClubBoardMedia.query.filter_by(post_id=post.id).count() == 1


def test_create_post_photo_and_text(client, db, regular_user, sample_club, app, tmp_path):
    """Photo + text together should create a post with both."""
    app.config['UPLOAD_FOLDER'] = str(tmp_path)
    _make_member(db, regular_user, sample_club)
    _login(client, regular_user.email)
    r = client.post(
        f'/clubs/{sample_club.slug}/board/',
        data={'body': 'Great ride!', 'photos': (io.BytesIO(_minimal_jpeg()), 'photo.jpg')},
        content_type='multipart/form-data',
        follow_redirects=True,
    )
    assert r.status_code == 200
    post = ClubBoardPost.query.filter_by(club_id=sample_club.id).first()
    assert post is not None
    assert post.body == 'Great ride!'
    assert ClubBoardMedia.query.filter_by(post_id=post.id).count() == 1


def test_create_post_empty_body_and_no_photo_rejected(client, db, regular_user, sample_club):
    """Empty body with no photos should still be rejected."""
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


# ── V2: Reactions ─────────────────────────────────────────────────────────────

def test_react_like(client, db, regular_user, sample_club):
    _make_member(db, regular_user, sample_club)
    post = _make_post(db, regular_user, sample_club)
    _login(client, regular_user.email)
    r = client.post(
        f'/clubs/{sample_club.slug}/board/{post.id}/react',
        json={'reaction': 'like'},
        content_type='application/json',
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data['like_count'] == 1
    assert data['user_reaction'] == 'like'


def test_react_toggle_removes_reaction(client, db, regular_user, sample_club):
    _make_member(db, regular_user, sample_club)
    post = _make_post(db, regular_user, sample_club)
    _login(client, regular_user.email)
    url = f'/clubs/{sample_club.slug}/board/{post.id}/react'
    client.post(url, json={'reaction': 'like'}, content_type='application/json')
    r = client.post(url, json={'reaction': 'like'}, content_type='application/json')
    data = r.get_json()
    assert data['like_count'] == 0
    assert data['user_reaction'] is None


def test_react_switch_changes_type(client, db, regular_user, sample_club):
    _make_member(db, regular_user, sample_club)
    post = _make_post(db, regular_user, sample_club)
    _login(client, regular_user.email)
    url = f'/clubs/{sample_club.slug}/board/{post.id}/react'
    client.post(url, json={'reaction': 'like'}, content_type='application/json')
    r = client.post(url, json={'reaction': 'dislike'}, content_type='application/json')
    data = r.get_json()
    assert data['like_count'] == 0
    assert data['dislike_count'] == 1
    assert data['user_reaction'] == 'dislike'


def test_react_invalid_reaction(client, db, regular_user, sample_club):
    _make_member(db, regular_user, sample_club)
    post = _make_post(db, regular_user, sample_club)
    _login(client, regular_user.email)
    r = client.post(
        f'/clubs/{sample_club.slug}/board/{post.id}/react',
        json={'reaction': 'heart'},
        content_type='application/json',
    )
    assert r.status_code == 400


def test_react_non_member_forbidden(client, db, regular_user, sample_club):
    _make_member(db, regular_user, sample_club)
    post = _make_post(db, regular_user, sample_club)
    # second_user not a member — log in as them
    from app.extensions import bcrypt
    from app.models import User
    outsider = User(username='outsider', email='out@test.com',
                    password_hash=bcrypt.generate_password_hash('password123').decode())
    db.session.add(outsider)
    db.session.commit()
    _login(client, 'out@test.com')
    r = client.post(
        f'/clubs/{sample_club.slug}/board/{post.id}/react',
        json={'reaction': 'like'},
        content_type='application/json',
    )
    assert r.status_code == 403


# ── V2: Replies ───────────────────────────────────────────────────────────────

def test_create_reply(client, db, regular_user, second_user, sample_club):
    _make_member(db, regular_user, sample_club)
    _make_member(db, second_user, sample_club)
    post = _make_post(db, regular_user, sample_club)
    _login(client, second_user.email)
    r = client.post(
        f'/clubs/{sample_club.slug}/board/{post.id}/reply',
        data={'body': 'Great post!'},
        follow_redirects=True,
    )
    assert r.status_code == 200
    reply = ClubBoardReply.query.filter_by(post_id=post.id).first()
    assert reply is not None
    assert reply.body == 'Great post!'
    assert reply.author_id == second_user.id


def test_reply_empty_body_rejected(client, db, regular_user, sample_club):
    _make_member(db, regular_user, sample_club)
    post = _make_post(db, regular_user, sample_club)
    _login(client, regular_user.email)
    client.post(
        f'/clubs/{sample_club.slug}/board/{post.id}/reply',
        data={'body': '   '},
        follow_redirects=True,
    )
    assert ClubBoardReply.query.filter_by(post_id=post.id).count() == 0


def test_reply_non_member_forbidden(client, db, regular_user, sample_club):
    _make_member(db, regular_user, sample_club)
    post = _make_post(db, regular_user, sample_club)
    from app.extensions import bcrypt
    from app.models import User
    outsider = User(username='out2', email='out2@test.com',
                    password_hash=bcrypt.generate_password_hash('password123').decode())
    db.session.add(outsider)
    db.session.commit()
    _login(client, 'out2@test.com')
    r = client.post(
        f'/clubs/{sample_club.slug}/board/{post.id}/reply',
        data={'body': 'Hello!'},
        follow_redirects=True,
    )
    assert r.status_code == 403


def test_delete_own_reply(client, db, regular_user, second_user, sample_club):
    _make_member(db, regular_user, sample_club)
    _make_member(db, second_user, sample_club)
    post = _make_post(db, regular_user, sample_club)
    reply = ClubBoardReply(post_id=post.id, author_id=second_user.id, body='Test reply')
    db.session.add(reply)
    db.session.commit()
    reply_id = reply.id
    _login(client, second_user.email)
    r = client.post(
        f'/clubs/{sample_club.slug}/board/{post.id}/reply/{reply_id}/delete',
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert db.session.get(ClubBoardReply, reply_id) is None


def test_delete_reply_forbidden_for_other_member(client, db, regular_user, second_user, sample_club):
    _make_member(db, regular_user, sample_club)
    _make_member(db, second_user, sample_club)
    post = _make_post(db, regular_user, sample_club)
    reply = ClubBoardReply(post_id=post.id, author_id=regular_user.id, body='Test reply')
    db.session.add(reply)
    db.session.commit()
    reply_id = reply.id
    _login(client, second_user.email)
    r = client.post(
        f'/clubs/{sample_club.slug}/board/{post.id}/reply/{reply_id}/delete',
        follow_redirects=True,
    )
    assert r.status_code == 403
    assert db.session.get(ClubBoardReply, reply_id) is not None


def test_admin_can_delete_any_reply(client, db, club_admin_user, regular_user, sample_club):
    _make_member(db, club_admin_user, sample_club)
    _make_member(db, regular_user, sample_club)
    post = _make_post(db, regular_user, sample_club)
    reply = ClubBoardReply(post_id=post.id, author_id=regular_user.id, body='Test reply')
    db.session.add(reply)
    db.session.commit()
    reply_id = reply.id
    _login(client, club_admin_user.email)
    r = client.post(
        f'/clubs/{sample_club.slug}/board/{post.id}/reply/{reply_id}/delete',
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert db.session.get(ClubBoardReply, reply_id) is None


def test_replies_visible_on_board_page(client, db, regular_user, sample_club):
    _make_member(db, regular_user, sample_club)
    post = _make_post(db, regular_user, sample_club)
    reply = ClubBoardReply(post_id=post.id, author_id=regular_user.id, body='A visible reply')
    db.session.add(reply)
    db.session.commit()
    _login(client, regular_user.email)
    r = client.get(f'/clubs/{sample_club.slug}/board/')
    assert b'A visible reply' in r.data


def test_post_cascade_deletes_replies_and_reactions(client, db, regular_user, sample_club):
    _make_member(db, regular_user, sample_club)
    post = _make_post(db, regular_user, sample_club)
    reply = ClubBoardReply(post_id=post.id, author_id=regular_user.id, body='Reply')
    reaction = ClubBoardReaction(post_id=post.id, user_id=regular_user.id, reaction='like')
    db.session.add_all([reply, reaction])
    db.session.commit()
    post_id = post.id
    _login(client, regular_user.email)
    client.post(f'/clubs/{sample_club.slug}/board/{post_id}/delete', follow_redirects=True)
    assert ClubBoardReply.query.filter_by(post_id=post_id).count() == 0
    assert ClubBoardReaction.query.filter_by(post_id=post_id).count() == 0


# ── V2: Username links and @mention rendering ────────────────────────────────

def test_board_renders_author_profile_link(client, db, regular_user, sample_club):
    _make_member(db, regular_user, sample_club)
    _make_post(db, regular_user, sample_club)
    _login(client, regular_user.email)
    r = client.get(f'/clubs/{sample_club.slug}/board/')
    assert f'/users/{regular_user.username}'.encode() in r.data


def test_mentionify_renders_link(client, db, regular_user, second_user, sample_club):
    _make_member(db, regular_user, sample_club)
    _make_post(db, regular_user, sample_club, body=f'Hey @{second_user.username} check this out')
    _login(client, regular_user.email)
    r = client.get(f'/clubs/{sample_club.slug}/board/')
    assert f'/users/{second_user.username}'.encode() in r.data
    assert b'board-mention' in r.data
