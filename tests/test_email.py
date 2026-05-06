"""Tests for email notification helpers."""
import pytest
from datetime import date, datetime, time, timedelta
from unittest.mock import patch, MagicMock, call

from app.models import ClubInvite, EmailDeliveryLog, Ride, RideSignup, ClubMembership
from app.extensions import db


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_ride(db, club, title='Test Ride', days_ahead=1):
    ride = Ride(
        club_id=club.id,
        title=title,
        date=date.today() + timedelta(days=days_ahead),
        time=time(17, 0),
        meeting_location='Test Location',
        distance_miles=25.0,
        pace_category='B',
        ride_type='road',
    )
    db.session.add(ride)
    db.session.commit()
    return ride


def _sign_up(db, user, ride):
    signup = RideSignup(ride_id=ride.id, user_id=user.id)
    db.session.add(signup)
    db.session.commit()
    return signup


def _assert_paceline_branding(msg):
    assert 'paceline' in msg.html.lower()
    assert 'paceline.club' in msg.html
    assert 'https://paceline.club' in msg.html


# ── Cancellation email tests ──────────────────────────────────────────────────

def test_cancellation_email_sent_to_signups(app, sample_club, regular_user):
    """Cancellation email is sent to all signed-up riders."""
    ride = _make_ride(db, sample_club)
    _sign_up(db, regular_user, ride)

    with patch('app.email.mail') as mock_mail:
        from app.email import send_cancellation_emails
        send_cancellation_emails(ride)
        mock_mail.send.assert_called_once()
        msg = mock_mail.send.call_args[0][0]
        assert regular_user.email in msg.recipients
        assert 'Cancelled' in msg.subject
        assert ride.title in msg.subject


def test_cancellation_no_email_if_no_signups(app, sample_club):
    """No email is sent for a ride with no signups."""
    ride = _make_ride(db, sample_club)

    with patch('app.email.mail') as mock_mail:
        from app.email import send_cancellation_emails
        send_cancellation_emails(ride)
        mock_mail.send.assert_not_called()


def test_cancellation_email_multiple_recipients(app, sample_club, regular_user, second_user):
    """Cancellation email addresses all signed-up riders."""
    ride = _make_ride(db, sample_club)
    _sign_up(db, regular_user, ride)
    _sign_up(db, second_user, ride)

    with patch('app.email.mail') as mock_mail:
        from app.email import send_cancellation_emails
        send_cancellation_emails(ride)
        mock_mail.send.assert_called_once()
        msg = mock_mail.send.call_args[0][0]
        assert regular_user.email in msg.recipients
        assert second_user.email in msg.recipients


def test_cancellation_includes_cancel_reason(app, sample_club, regular_user):
    """Email body contains the cancel reason when set."""
    ride = _make_ride(db, sample_club)
    ride.is_cancelled = True
    ride.cancel_reason = 'Auto-cancelled due to weather: 90% precipitation probability'
    db.session.commit()
    _sign_up(db, regular_user, ride)

    with patch('app.email.mail') as mock_mail:
        from app.email import send_cancellation_emails
        send_cancellation_emails(ride)
        msg = mock_mail.send.call_args[0][0]
        assert '90%' in msg.html or '90%' in msg.body


def test_cancellation_email_swallows_exceptions(app, sample_club, regular_user):
    """A mail failure does not propagate as an exception."""
    ride = _make_ride(db, sample_club)
    _sign_up(db, regular_user, ride)

    with patch('app.email.mail') as mock_mail:
        mock_mail.send.side_effect = Exception('SMTP error')
        from app.email import send_cancellation_emails
        send_cancellation_emails(ride)  # must not raise


def test_resend_provider_posts_email_payload(app):
    """When configured, Resend sends through the HTTP API instead of SMTP."""
    app.config['RESEND_API_KEY'] = 're_test_key'
    app.config['MAIL_DEFAULT_SENDER'] = 'Paceline <noreply@paceline.club>'
    from app.email import _send

    mock_response = MagicMock()
    with patch('app.email.requests.post', return_value=mock_response) as mock_post, \
         patch('app.email.mail') as mock_mail:
        _send('Subject', ['rider@test.com'], '<p>Hello</p>', 'Hello')

    mock_mail.send.assert_not_called()
    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert kwargs['headers']['Authorization'] == 'Bearer re_test_key'
    assert kwargs['json'] == {
        'from': 'Paceline <noreply@paceline.club>',
        'to': ['rider@test.com'],
        'subject': 'Subject',
        'html': '<p>Hello</p>',
        'text': 'Hello',
    }
    mock_response.raise_for_status.assert_called_once()
    log = EmailDeliveryLog.query.one()
    assert log.provider == 'resend'
    assert log.status == 'sent'
    assert log.recipient_count == 1


def test_resend_provider_chunks_large_recipient_lists(app):
    """Resend accepts up to 50 `to` addresses per request."""
    app.config['RESEND_API_KEY'] = 're_test_key'
    from app.email import _send

    recipients = [f'rider{i}@example.com' for i in range(121)]
    mock_response = MagicMock()
    with patch('app.email.requests.post', return_value=mock_response) as mock_post:
        _send('Subject', recipients, '<p>Hello</p>', 'Hello')

    assert mock_post.call_count == 3
    assert len(mock_post.call_args_list[0].kwargs['json']['to']) == 50
    assert len(mock_post.call_args_list[1].kwargs['json']['to']) == 50
    assert len(mock_post.call_args_list[2].kwargs['json']['to']) == 21
    assert sum(log.recipient_count for log in EmailDeliveryLog.query.all()) == 121


def test_resend_provider_swallows_http_errors(app):
    """A Resend failure should not break the user-facing request."""
    app.config['RESEND_API_KEY'] = 're_test_key'
    from app.email import _send

    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = Exception('resend down')
    with patch('app.email.requests.post', return_value=mock_response):
        _send('Subject', ['rider@test.com'], '<p>Hello</p>', 'Hello')
    log = EmailDeliveryLog.query.one()
    assert log.provider == 'resend'
    assert log.status == 'failed'
    assert log.recipient_count == 1
    assert 'resend down' in log.error


def test_email_recipient_override_redirects_resend_recipients(app):
    app.config['RESEND_API_KEY'] = 're_test_key'
    app.config['EMAIL_RECIPIENT_OVERRIDE'] = 'delivered@resend.dev'
    from app.email import _send

    mock_response = MagicMock()
    with patch('app.email.requests.post', return_value=mock_response) as mock_post:
        _send('Subject', ['real1@example.com', 'real2@example.com'], '<p>Hello</p>', 'Hello')

    assert mock_post.call_args.kwargs['json']['to'] == ['delivered@resend.dev']
    log = EmailDeliveryLog.query.one()
    assert log.recipient_count == 1


# ── Ride reminder tests ───────────────────────────────────────────────────────

def test_reminder_email_sent_to_signups(app, sample_club, regular_user):
    """Reminder email is sent to signed-up riders."""
    ride = _make_ride(db, sample_club, days_ahead=0)
    _sign_up(db, regular_user, ride)

    with patch('app.email.mail') as mock_mail:
        from app.email import send_ride_reminder
        send_ride_reminder(ride)
        mock_mail.send.assert_called_once()
        msg = mock_mail.send.call_args[0][0]
        assert regular_user.email in msg.recipients
        assert "Today's Ride" in msg.subject
        assert ride.title in msg.subject


def test_reminder_no_email_if_no_signups(app, sample_club):
    """No reminder sent when nobody is signed up."""
    ride = _make_ride(db, sample_club, days_ahead=0)

    with patch('app.email.mail') as mock_mail:
        from app.email import send_ride_reminder
        send_ride_reminder(ride)
        mock_mail.send.assert_not_called()


def test_all_ride_email_templates_include_paceline_branding(app, sample_club, regular_user):
    ride = _make_ride(db, sample_club, days_ahead=0)
    _sign_up(db, regular_user, ride)

    with patch('app.email.mail') as mock_mail:
        from app.email import send_cancellation_emails, send_ride_reminder
        ride.is_cancelled = True
        ride.cancel_reason = 'Storms nearby'
        db.session.commit()
        send_cancellation_emails(ride)
        send_ride_reminder(ride)

    for call_item in mock_mail.send.call_args_list:
        _assert_paceline_branding(call_item.args[0])


# ── New ride notification tests ───────────────────────────────────────────────

def test_new_ride_notification_sent_to_members(app, sample_club, regular_user):
    """New ride notification is sent to all club members."""
    db.session.add(ClubMembership(user_id=regular_user.id, club_id=sample_club.id))
    db.session.commit()
    ride = _make_ride(db, sample_club)

    with patch('app.email.mail') as mock_mail:
        from app.email import send_new_ride_notification
        send_new_ride_notification(ride)
        mock_mail.send.assert_called_once()
        msg = mock_mail.send.call_args[0][0]
        assert regular_user.email in msg.recipients
        assert 'New Ride' in msg.subject


def test_new_ride_no_email_if_no_members(app, sample_club):
    """No notification sent if club has no members."""
    ride = _make_ride(db, sample_club)

    with patch('app.email.mail') as mock_mail:
        from app.email import send_new_ride_notification
        send_new_ride_notification(ride)
        mock_mail.send.assert_not_called()


def test_membership_approved_email(app, sample_club, regular_user):
    with patch('app.email.mail') as mock_mail:
        from app.email import send_membership_approved
        send_membership_approved(regular_user, sample_club)
    msg = mock_mail.send.call_args.args[0]
    assert msg.recipients == [regular_user.email]
    assert 'Membership Approved' in msg.subject
    _assert_paceline_branding(msg)


def test_membership_rejected_email(app, sample_club, regular_user):
    with patch('app.email.mail') as mock_mail:
        from app.email import send_membership_rejected
        send_membership_rejected(regular_user, sample_club)
    msg = mock_mail.send.call_args.args[0]
    assert msg.recipients == [regular_user.email]
    assert 'Membership Request' in msg.subject
    _assert_paceline_branding(msg)


def test_waitlist_promoted_email(app, sample_club, regular_user):
    ride = _make_ride(db, sample_club)
    signup = RideSignup(ride_id=ride.id, user_id=regular_user.id, is_waitlist=False)
    db.session.add(signup)
    db.session.commit()
    with patch('app.email.mail') as mock_mail:
        from app.email import send_waitlist_promoted
        send_waitlist_promoted(signup)
    msg = mock_mail.send.call_args.args[0]
    assert msg.recipients == [regular_user.email]
    assert "You're off the waitlist" in msg.subject
    _assert_paceline_branding(msg)


def test_invite_email(app, sample_club, admin_user):
    invite = ClubInvite(
        club_id=sample_club.id,
        email='invitee@example.com',
        token='invite-token',
        expires_at=datetime.now() + timedelta(days=7),
        created_by=admin_user.id,
    )
    db.session.add(invite)
    db.session.commit()
    with patch('app.email.mail') as mock_mail:
        from app.email import send_invite_email
        send_invite_email(invite)
    msg = mock_mail.send.call_args.args[0]
    assert msg.recipients == ['invitee@example.com']
    assert "You're invited" in msg.subject
    assert 'invite-token' in msg.html
    _assert_paceline_branding(msg)


def test_import_welcome_email(app, sample_club, admin_user):
    invite = ClubInvite(
        club_id=sample_club.id,
        email='newmember@example.com',
        token='setup-token',
        expires_at=datetime.now() + timedelta(days=7),
        created_by=admin_user.id,
        is_new_user=True,
    )
    db.session.add(invite)
    db.session.commit()
    with patch('app.email.mail') as mock_mail:
        from app.email import send_import_welcome_email
        send_import_welcome_email(invite)
    msg = mock_mail.send.call_args.args[0]
    assert msg.recipients == ['newmember@example.com']
    assert 'set up your Paceline account' in msg.subject
    assert 'setup-token' in msg.html
    _assert_paceline_branding(msg)


def test_import_invite_email(app, sample_club, admin_user):
    invite = ClubInvite(
        club_id=sample_club.id,
        email='existing@example.com',
        token='import-token',
        expires_at=datetime.now() + timedelta(days=7),
        created_by=admin_user.id,
    )
    db.session.add(invite)
    db.session.commit()
    with patch('app.email.mail') as mock_mail:
        from app.email import send_import_invite_email
        send_import_invite_email(invite)
    msg = mock_mail.send.call_args.args[0]
    assert msg.recipients == ['existing@example.com']
    assert "You've been added" in msg.subject
    assert 'import-token' in msg.html
    _assert_paceline_branding(msg)


def test_weekly_digest_email(app, sample_club, regular_user):
    db.session.add(ClubMembership(user_id=regular_user.id, club_id=sample_club.id, status='active'))
    ride = _make_ride(db, sample_club)
    db.session.commit()
    with patch('app.email.mail') as mock_mail:
        from app.email import send_weekly_digest
        send_weekly_digest(sample_club, [ride])
    msg = mock_mail.send.call_args.args[0]
    assert regular_user.email in msg.recipients
    assert "This week's rides" in msg.subject
    assert ride.title in msg.html
    _assert_paceline_branding(msg)


def test_feedback_notification_email(app, admin_user):
    from app.models import SiteFeedback
    feedback = SiteFeedback(name='Rider', email='rider@example.com', message='Looks good', source='test')
    db.session.add(feedback)
    db.session.commit()
    with patch('app.email.mail') as mock_mail:
        from app.email import send_feedback_notification
        send_feedback_notification(feedback)
    msg = mock_mail.send.call_args.args[0]
    assert admin_user.email in msg.recipients
    assert 'New Paceline feedback' in msg.subject
    _assert_paceline_branding(msg)


# ── Admin integration tests ───────────────────────────────────────────────────

def test_new_ride_notification_triggered_on_admin_create(
        client, app, sample_club, club_admin_user, regular_user):
    """Creating a non-recurring ride via admin sends new ride notifications."""
    db.session.add(ClubMembership(user_id=regular_user.id, club_id=sample_club.id))
    db.session.commit()

    from tests.conftest import login
    login(client, email='clubadmin@test.com')

    with patch('app.routes.admin.send_new_ride_notification') as mock_notify:
        resp = client.post(
            f'/admin/clubs/{sample_club.slug}/rides/new',
            data={
                'title': 'Notify Test Ride',
                'date': (date.today() + timedelta(days=5)).isoformat(),
                'time': '17:00',
                'meeting_location': 'Test Spot',
                'distance_miles': '25',
                'pace_category': 'B',
            },
            follow_redirects=True,
        )
    assert resp.status_code == 200
    mock_notify.assert_called_once()


def test_recurring_ride_skips_new_ride_notification(
        client, app, sample_club, club_admin_user, regular_user):
    """Creating a recurring ride does NOT send new ride notifications (too noisy)."""
    db.session.add(ClubMembership(user_id=regular_user.id, club_id=sample_club.id))
    db.session.commit()

    from tests.conftest import login
    login(client, email='clubadmin@test.com')

    with patch('app.routes.admin.send_new_ride_notification') as mock_notify:
        client.post(
            f'/admin/clubs/{sample_club.slug}/rides/new',
            data={
                'title': 'Recurring Ride',
                'date': (date.today() + timedelta(days=5)).isoformat(),
                'time': '17:00',
                'meeting_location': 'Test Spot',
                'distance_miles': '25',
                'pace_category': 'B',
                'is_recurring': 'y',
            },
            follow_redirects=True,
        )
    mock_notify.assert_not_called()


def test_cancellation_email_triggered_on_admin_edit(
        client, app, sample_club, club_admin_user, regular_user):
    """Editing a ride to mark it cancelled triggers cancellation emails."""
    ride = _make_ride(db, sample_club)
    _sign_up(db, regular_user, ride)

    from tests.conftest import login
    login(client, email='clubadmin@test.com')

    with patch('app.routes.admin.send_cancellation_emails') as mock_cancel:
        resp = client.post(
            f'/admin/clubs/{sample_club.slug}/rides/{ride.id}/edit',
            data={
                'title': ride.title,
                'date': ride.date.isoformat(),
                'time': '17:00',
                'meeting_location': ride.meeting_location,
                'distance_miles': str(ride.distance_miles),
                'pace_category': ride.pace_category,
                'ride_type': ride.ride_type or 'road',
                'is_cancelled': 'y',
            },
            follow_redirects=True,
        )
    assert resp.status_code == 200
    mock_cancel.assert_called_once()


def test_cancellation_email_not_resent_if_already_cancelled(
        client, app, sample_club, club_admin_user, regular_user):
    """Editing an already-cancelled ride does not re-send cancellation email."""
    ride = _make_ride(db, sample_club)
    ride.is_cancelled = True
    db.session.commit()
    _sign_up(db, regular_user, ride)

    from tests.conftest import login
    login(client, email='clubadmin@test.com')

    with patch('app.routes.admin.send_cancellation_emails') as mock_cancel:
        client.post(
            f'/admin/clubs/{sample_club.slug}/rides/{ride.id}/edit',
            data={
                'title': ride.title,
                'date': ride.date.isoformat(),
                'time': '17:00',
                'meeting_location': ride.meeting_location,
                'distance_miles': str(ride.distance_miles),
                'pace_category': ride.pace_category,
                'ride_type': ride.ride_type or 'road',
                'is_cancelled': 'y',
            },
            follow_redirects=True,
        )
    mock_cancel.assert_not_called()
