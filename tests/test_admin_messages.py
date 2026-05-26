"""Tests for superadmin ↔ club admin messaging."""
import pytest
from app.models import AdminMessage, ClubAdmin


# ── Helpers ───────────────────────────────────────────────────────────────────

def login(client, email, password='password123'):
    return client.post('/auth/login', data={'email': email, 'password': password},
                       follow_redirects=True)


def _make_root(db, club, sender):
    """Create a root-level AdminMessage from superadmin to club."""
    msg = AdminMessage(
        club_id=club.id,
        sender_id=sender.id,
        is_from_superadmin=True,
        subject='Test Subject',
        body='Hello from Paceline.',
        parent_id=None,
        is_read=False,
    )
    db.session.add(msg)
    db.session.commit()
    return msg


def _make_reply(db, club, sender, parent, from_superadmin=False):
    """Create a reply AdminMessage."""
    msg = AdminMessage(
        club_id=club.id,
        sender_id=sender.id,
        is_from_superadmin=from_superadmin,
        body='A reply.',
        parent_id=parent.id,
        is_read=False,
    )
    db.session.add(msg)
    db.session.commit()
    return msg


# ── Access control ────────────────────────────────────────────────────────────

def test_messages_inbox_requires_superadmin(client, db, regular_user, sample_club):
    login(client, regular_user.email)
    rv = client.get('/admin/messages')
    assert rv.status_code in (302, 403)


def test_messages_club_thread_requires_superadmin(client, db, regular_user, sample_club):
    login(client, regular_user.email)
    rv = client.get(f'/admin/messages/club/{sample_club.slug}')
    assert rv.status_code in (302, 403)


def test_messages_broadcast_requires_superadmin(client, db, regular_user):
    login(client, regular_user.email)
    rv = client.get('/admin/messages/broadcast')
    assert rv.status_code in (302, 403)


def test_club_messages_requires_club_admin(client, db, regular_user, sample_club):
    login(client, regular_user.email)
    rv = client.get(f'/admin/clubs/{sample_club.slug}/messages')
    assert rv.status_code in (302, 403)


# ── Superadmin inbox ──────────────────────────────────────────────────────────

def test_messages_inbox_loads(client, db, admin_user, sample_club):
    login(client, admin_user.email)
    rv = client.get('/admin/messages')
    assert rv.status_code == 200
    assert b'Messages' in rv.data


def test_messages_inbox_shows_club_with_message(client, db, admin_user, sample_club):
    _make_root(db, sample_club, admin_user)
    login(client, admin_user.email)
    rv = client.get('/admin/messages')
    assert rv.status_code == 200
    assert sample_club.name.encode() in rv.data


# ── Superadmin → club: send new message ──────────────────────────────────────

def test_superadmin_can_send_message_to_club(client, db, admin_user, sample_club):
    login(client, admin_user.email)
    rv = client.post(f'/admin/messages/club/{sample_club.slug}',
                     data={'subject': 'Welcome', 'body': 'Hi there!'},
                     follow_redirects=True)
    assert rv.status_code == 200
    msg = AdminMessage.query.filter_by(club_id=sample_club.id, parent_id=None).first()
    assert msg is not None
    assert msg.subject == 'Welcome'
    assert msg.body == 'Hi there!'
    assert msg.is_from_superadmin is True


def test_superadmin_send_requires_body(client, db, admin_user, sample_club):
    login(client, admin_user.email)
    rv = client.post(f'/admin/messages/club/{sample_club.slug}',
                     data={'subject': 'No body here', 'body': ''},
                     follow_redirects=True)
    assert rv.status_code == 200
    count = AdminMessage.query.filter_by(club_id=sample_club.id).count()
    assert count == 0


def test_superadmin_can_reply_to_existing_thread(client, db, admin_user, sample_club):
    root = _make_root(db, sample_club, admin_user)
    login(client, admin_user.email)
    rv = client.post(f'/admin/messages/club/{sample_club.slug}',
                     data={'body': 'Follow-up from Paceline.', 'parent_id': str(root.id)},
                     follow_redirects=True)
    assert rv.status_code == 200
    reply = AdminMessage.query.filter_by(parent_id=root.id).first()
    assert reply is not None
    assert reply.body == 'Follow-up from Paceline.'


# ── Thread view marks replies as read ─────────────────────────────────────────

def test_superadmin_viewing_thread_marks_club_replies_read(
        client, db, admin_user, club_admin_user, sample_club):
    root = _make_root(db, sample_club, admin_user)
    reply = _make_reply(db, sample_club, club_admin_user, root, from_superadmin=False)
    assert reply.is_read is False

    login(client, admin_user.email)
    client.get(f'/admin/messages/club/{sample_club.slug}')

    db.session.refresh(reply)
    assert reply.is_read is True


def test_club_admin_viewing_messages_marks_superadmin_msgs_read(
        client, db, admin_user, club_admin_user, sample_club):
    root = _make_root(db, sample_club, admin_user)
    assert root.is_read is False

    login(client, club_admin_user.email)
    client.get(f'/admin/clubs/{sample_club.slug}/messages')

    db.session.refresh(root)
    assert root.is_read is True


# ── Club admin view ──────────────────────────────────────────────────────────

def test_club_admin_can_view_messages(client, db, admin_user, club_admin_user, sample_club):
    _make_root(db, sample_club, admin_user)
    login(client, club_admin_user.email)
    rv = client.get(f'/admin/clubs/{sample_club.slug}/messages')
    assert rv.status_code == 200
    assert b'Hello from Paceline.' in rv.data


def test_club_admin_can_reply(client, db, admin_user, club_admin_user, sample_club):
    root = _make_root(db, sample_club, admin_user)
    login(client, club_admin_user.email)
    rv = client.post(f'/admin/clubs/{sample_club.slug}/messages',
                     data={'body': 'Thanks for the message!', 'parent_id': str(root.id)},
                     follow_redirects=True)
    assert rv.status_code == 200
    reply = AdminMessage.query.filter_by(parent_id=root.id).first()
    assert reply is not None
    assert reply.body == 'Thanks for the message!'
    assert reply.is_from_superadmin is False


def test_club_admin_reply_requires_body(client, db, admin_user, club_admin_user, sample_club):
    root = _make_root(db, sample_club, admin_user)
    login(client, club_admin_user.email)
    rv = client.post(f'/admin/clubs/{sample_club.slug}/messages',
                     data={'body': '', 'parent_id': str(root.id)},
                     follow_redirects=True)
    assert rv.status_code == 200
    assert AdminMessage.query.filter_by(parent_id=root.id).count() == 0


def test_club_messages_empty_state(client, db, club_admin_user, sample_club):
    login(client, club_admin_user.email)
    rv = client.get(f'/admin/clubs/{sample_club.slug}/messages')
    assert rv.status_code == 200
    assert b'No messages from Paceline' in rv.data


# ── Broadcast ─────────────────────────────────────────────────────────────────

def test_broadcast_page_loads(client, db, admin_user):
    login(client, admin_user.email)
    rv = client.get('/admin/messages/broadcast')
    assert rv.status_code == 200


def test_superadmin_can_send_broadcast(client, db, admin_user):
    login(client, admin_user.email)
    rv = client.post('/admin/messages/broadcast',
                     data={'subject': 'Platform update', 'body': 'New features shipped.'},
                     follow_redirects=True)
    assert rv.status_code == 200
    bcast = AdminMessage.query.filter_by(club_id=None, parent_id=None).first()
    assert bcast is not None
    assert bcast.subject == 'Platform update'
    assert bcast.is_from_superadmin is True


def test_broadcast_requires_subject_and_body(client, db, admin_user):
    login(client, admin_user.email)
    rv = client.post('/admin/messages/broadcast',
                     data={'subject': '', 'body': 'body only'},
                     follow_redirects=True)
    assert rv.status_code == 200
    assert AdminMessage.query.filter_by(club_id=None).count() == 0

    rv = client.post('/admin/messages/broadcast',
                     data={'subject': 'subject only', 'body': ''},
                     follow_redirects=True)
    assert AdminMessage.query.filter_by(club_id=None).count() == 0


def test_broadcast_appears_in_club_messages(client, db, admin_user, club_admin_user, sample_club):
    # Create broadcast (no club_id)
    bcast = AdminMessage(
        club_id=None,
        sender_id=admin_user.id,
        is_from_superadmin=True,
        subject='Big news',
        body='Something for all clubs.',
        parent_id=None,
        is_read=False,
    )
    db.session.add(bcast)
    db.session.commit()

    login(client, club_admin_user.email)
    rv = client.get(f'/admin/clubs/{sample_club.slug}/messages')
    assert rv.status_code == 200
    assert b'Big news' in rv.data


# ── Unread badge in club_dashboard ───────────────────────────────────────────

def test_unread_badge_shows_on_club_dashboard(client, db, admin_user, club_admin_user, sample_club):
    _make_root(db, sample_club, admin_user)
    login(client, club_admin_user.email)
    rv = client.get(f'/admin/clubs/{sample_club.slug}/')
    assert rv.status_code == 200
    assert b'Messages' in rv.data


def test_unread_count_clears_after_view(client, db, admin_user, club_admin_user, sample_club):
    _make_root(db, sample_club, admin_user)
    login(client, club_admin_user.email)
    client.get(f'/admin/clubs/{sample_club.slug}/messages')

    # Now visit club dashboard — unread count should be 0
    rv = client.get(f'/admin/clubs/{sample_club.slug}/')
    assert rv.status_code == 200
    # The badge should not show (no unread messages)
    remaining = AdminMessage.query.filter_by(
        club_id=sample_club.id, is_from_superadmin=True, is_read=False
    ).count()
    assert remaining == 0
