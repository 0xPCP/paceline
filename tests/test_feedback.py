from unittest.mock import patch

from app.extensions import db
from app.models import AdminAuditLog, SiteFeedback
from tests.conftest import login


def test_donate_page_shows_feedback_form(client):
    resp = client.get('/donate')
    assert resp.status_code == 200
    assert b'id="feedback"' in resp.data
    assert b'Send a note or suggestion' in resp.data
    assert b'name="message"' in resp.data


def test_sitewide_feedback_prompt_links_to_existing_form(client):
    resp = client.get('/')
    assert resp.status_code == 200
    assert b'class="site-feedback-fab"' in resp.data
    assert b'/donate#feedback' in resp.data
    assert b'Send Feedback' in resp.data


def test_submit_feedback_stores_item_and_sends_email(client, admin_user):
    with patch('app.routes.main.send_feedback_notification') as mock_send:
        resp = client.post('/feedback', data={
            'name': 'Local Rider',
            'email': 'rider@example.com',
            'message': 'Please add more gravel filters.',
            'source': 'donate',
        }, follow_redirects=True)
    assert resp.status_code == 200
    assert b'Thanks for the feedback' in resp.data

    item = SiteFeedback.query.first()
    assert item is not None
    assert item.name == 'Local Rider'
    assert item.email == 'rider@example.com'
    assert item.message == 'Please add more gravel filters.'
    assert item.is_read is False
    mock_send.assert_called_once_with(item)


def test_feedback_validation_rejects_empty_message(client):
    resp = client.post('/feedback', data={
        'name': 'Local Rider',
        'email': 'rider@example.com',
        'message': '',
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b'Please enter a valid message' in resp.data
    assert SiteFeedback.query.count() == 0


def test_feedback_notification_recipients_include_active_superadmins(app, db, admin_user):
    from app.email import send_feedback_notification

    item = SiteFeedback(name='Rider', email='rider@example.com', message='Hello', source='donate')
    db.session.add(item)
    db.session.commit()
    app.config['SUPERADMIN_EMAILS'] = 'phil@pcp.dev'

    with patch('app.email._send') as mock_send:
        send_feedback_notification(item)

    args = mock_send.call_args.args
    assert args[0] == 'New Paceline feedback received'
    assert 'admin@test.com' in args[1]
    assert 'phil@pcp.dev' in args[1]


def test_feedback_inbox_requires_superadmin(client, regular_user):
    login(client, regular_user.email, 'password123')
    resp = client.get('/admin/feedback/')
    assert resp.status_code == 403


def test_superadmin_can_view_and_mark_feedback_read(client, db, admin_user):
    item = SiteFeedback(name='Rider', email='rider@example.com', message='Useful idea', source='donate')
    db.session.add(item)
    db.session.commit()

    login(client, admin_user.email, 'password123')
    resp = client.get('/admin/feedback/')
    assert resp.status_code == 200
    assert b'Useful idea' in resp.data
    assert b'Unread' in resp.data

    resp = client.post(
        f'/admin/feedback/{item.id}/mark-read',
        follow_redirects=True,
    )
    assert resp.status_code == 200
    db.session.refresh(item)
    assert item.is_read is True
    assert item.read_by_id == admin_user.id
    assert item.read_at is not None
    assert AdminAuditLog.query.filter_by(action='mark_feedback_read').first() is not None


def test_dashboard_shows_unread_feedback_count(client, db, admin_user):
    db.session.add(SiteFeedback(message='Unread one', source='donate'))
    db.session.commit()

    login(client, admin_user.email, 'password123')
    resp = client.get('/admin/')
    assert resp.status_code == 200
    assert b'Unread Feedback' in resp.data
