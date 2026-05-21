"""
Email notification helpers.

All send_* functions are fire-and-forget: they log errors but never raise,
so a mail failure never breaks a user-facing request or the scheduler.

Configure RESEND_API_KEY to send through Resend. Without it, the helper falls
back to Flask-Mail/SMTP. If neither is configured, Flask-Mail suppresses sends.
"""
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from flask import render_template, current_app
from flask_mail import Message
import requests
from .extensions import mail

logger = logging.getLogger(__name__)
RESEND_BATCH_SIZE = 50
RESEND_TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}
DEFAULT_DAILY_EMAIL_CAP = 15
DEFAULT_EMAIL_PREFERENCES = {
    'ride_cancellations': True,
    'ride_reminders': True,
    'ride_waitlist': True,
    'ride_updates': True,
    'membership_updates': True,
    'club_new_rides': True,
    'club_news': True,
    'weekly_digest': True,
    'board_digest': True,
    'friend_ride_signup': True,
}


def email_preferences_for(user):
    prefs = dict(DEFAULT_EMAIL_PREFERENCES)
    prefs.update(user.email_preferences or {})
    return prefs


def user_allows_email(user, notification_key):
    if not notification_key:
        return True
    return bool(email_preferences_for(user).get(notification_key, True))


def get_site_setting(key, default=None):
    try:
        from .models import SiteSetting
        from .extensions import db
        row = db.session.get(SiteSetting, key)
        return row.value if row and row.value is not None else default
    except Exception:
        return default


def set_site_setting(key, value):
    from .models import SiteSetting
    from .extensions import db
    row = db.session.get(SiteSetting, key)
    if row is None:
        row = SiteSetting(key=key)
        db.session.add(row)
    row.value = str(value)


def daily_email_cap():
    try:
        return max(0, int(get_site_setting('email_daily_cap', DEFAULT_DAILY_EMAIL_CAP)))
    except (TypeError, ValueError):
        return DEFAULT_DAILY_EMAIL_CAP


def _cap_allows(user):
    cap = daily_email_cap()
    if cap <= 0:
        return True
    from .models import UserEmailLog
    today_start = datetime.combine(datetime.now(timezone.utc).date(), datetime.min.time())
    sent = UserEmailLog.query.filter(
        UserEmailLog.user_id == user.id,
        UserEmailLog.status == 'sent',
        UserEmailLog.created_at >= today_start,
    ).count()
    return sent < cap


def _record_user_email(user, notification_key, subject, status='sent'):
    try:
        from .models import UserEmailLog
        from .extensions import db
        db.session.add(UserEmailLog(
            user_id=user.id,
            notification_key=notification_key or 'transactional',
            subject=(subject or '')[:255],
            status=status,
        ))
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.debug('User email telemetry write failed: %s', exc)


def _send(subject, recipients, html_body, text_body=None):
    """Send a single message, swallowing all exceptions."""
    if not recipients:
        return False
    override = current_app.config.get('EMAIL_RECIPIENT_OVERRIDE', '').strip()
    if override:
        recipients = [override]
    unique_recipients = list(dict.fromkeys(recipients))
    try:
        if _use_resend():
            _send_resend(subject, unique_recipients, html_body, text_body)
        else:
            _send_smtp(subject, unique_recipients, html_body, text_body)
        return True
    except Exception as exc:
        _record_delivery(_provider_name(), subject, len(unique_recipients), 'failed', str(exc))
        logger.warning('Email send failed (%s): %s', subject, exc)
        return False


def _send_to_users(notification_key, subject, users, html_body, text_body=None, *, required=False):
    selected = []
    seen = set()
    for user in users:
        if not user or not user.email or user.id in seen:
            continue
        seen.add(user.id)
        if not required and not user_allows_email(user, notification_key):
            continue
        if not required and not _cap_allows(user):
            _record_user_email(user, notification_key, subject, status='capped')
            continue
        selected.append(user)
    if not selected:
        return False
    sent_ok = _send(subject, [user.email for user in selected], html_body, text_body)
    for user in selected:
        _record_user_email(user, notification_key, subject, status='sent' if sent_ok else 'failed')
    return sent_ok


def _use_resend():
    provider = current_app.config.get('EMAIL_PROVIDER', '')
    api_key = current_app.config.get('RESEND_API_KEY', '')
    return bool(api_key and provider in ('', 'resend'))


def _send_smtp(subject, recipients, html_body, text_body=None):
    msg = Message(
        subject=subject,
        recipients=recipients,
        html=html_body,
        body=text_body or '',
    )
    mail.send(msg)
    _record_delivery('smtp', subject, len(recipients), 'sent')


def _send_resend(subject, recipients, html_body, text_body=None):
    api_key = current_app.config['RESEND_API_KEY']
    api_url = current_app.config.get('RESEND_API_URL', 'https://api.resend.com/emails')
    timeout = current_app.config.get('RESEND_TIMEOUT_SECONDS', 10)
    sender = current_app.config.get('MAIL_DEFAULT_SENDER') or 'Paceline <noreply@paceline.club>'
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
    }
    for start in range(0, len(recipients), RESEND_BATCH_SIZE):
        batch = recipients[start:start + RESEND_BATCH_SIZE]
        payload = {
            'from': sender,
            'to': batch,
            'subject': subject,
            'html': html_body,
            'text': text_body or '',
        }
        response = _post_resend_with_retry(api_url, payload, headers, timeout)
        response.raise_for_status()
        _record_delivery('resend', subject, len(batch), 'sent')


def _post_resend_with_retry(api_url, payload, headers, timeout):
    attempts = max(1, int(current_app.config.get('RESEND_MAX_ATTEMPTS', 3)))
    for attempt in range(attempts):
        response = requests.post(api_url, json=payload, headers=headers, timeout=timeout)
        status_code = getattr(response, 'status_code', None)
        is_transient = isinstance(status_code, int) and status_code in RESEND_TRANSIENT_STATUS_CODES
        if is_transient and attempt < attempts - 1:
            time.sleep(_resend_retry_delay(response, attempt))
            continue
        return response
    return response


def _resend_retry_delay(response, attempt):
    retry_after = getattr(response, 'headers', {}).get('Retry-After')
    if retry_after:
        try:
            return max(0, int(retry_after))
        except ValueError:
            pass
    delays = current_app.config.get('RESEND_RETRY_BACKOFF_SECONDS', (2, 5, 15))
    if isinstance(delays, str):
        delays = [int(value.strip()) for value in delays.split(',') if value.strip()]
    if not delays:
        return 0
    return delays[min(attempt, len(delays) - 1)]


def _provider_name():
    if _use_resend():
        return 'resend'
    return 'smtp'


def _record_delivery(provider, subject, recipient_count, status, error=None):
    try:
        from .models import EmailDeliveryLog
        from .extensions import db
        db.session.add(EmailDeliveryLog(
            provider=provider,
            subject=(subject or '')[:255],
            recipient_count=recipient_count,
            status=status,
            error=(error or '')[:1000] or None,
        ))
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.debug('Email telemetry write failed: %s', exc)


def send_cancellation_emails(ride):
    """
    Notify all signed-up riders that a ride has been cancelled.
    Called when ride.is_cancelled is set to True (manual or auto).
    """
    users = [s.user for s in ride.signups]
    if not users:
        return
    html = render_template('email/cancellation.html', ride=ride)
    text = render_template('email/cancellation.txt', ride=ride)
    subject = f'Ride Cancelled: {ride.title} — {ride.club.name}'
    _send_to_users('ride_cancellations', subject, users, html, text)
    logger.info('Cancellation emails queued for ride %d to %d signed-up user(s)', ride.id, len(users))


def send_ride_reminder(ride):
    """
    Send a morning-of reminder to all signed-up riders.
    Called by the scheduler at 6 AM on the day of the ride.
    """
    users = [s.user for s in ride.signups]
    if not users:
        return
    html = render_template('email/reminder.html', ride=ride)
    text = render_template('email/reminder.txt', ride=ride)
    subject = f"Today's Ride: {ride.title} — {ride.club.name}"
    _send_to_users('ride_reminders', subject, users, html, text)
    logger.info('Reminder emails queued for ride %d to %d signed-up user(s)', ride.id, len(users))


def send_membership_approved(user, club):
    """Notify a user that their membership request was approved."""
    if not user.email:
        return
    html = render_template('email/membership_approved.html', club=club)
    text = render_template('email/membership_approved.txt', club=club)
    _send_to_users('membership_updates', f'Membership Approved — {club.name}', [user], html, text)
    logger.info('Membership approved email sent to %s for club %d', user.email, club.id)


def send_membership_rejected(user, club):
    """Notify a user that their membership request was rejected."""
    if not user.email:
        return
    html = render_template('email/membership_rejected.html', club=club)
    text = render_template('email/membership_rejected.txt', club=club)
    _send_to_users('membership_updates', f'Membership Request — {club.name}', [user], html, text)
    logger.info('Membership rejected email sent to %s for club %d', user.email, club.id)


def send_new_ride_notification(ride):
    """
    Notify all club members when a new ride is created.
    Called when an admin creates a new (non-recurring-instance) ride.
    """
    from .models import ClubMembership
    memberships = ClubMembership.query.filter_by(club_id=ride.club_id, status='active').all()
    users = [m.user for m in memberships]
    if not users:
        return
    html = render_template('email/new_ride.html', ride=ride)
    text = render_template('email/new_ride.txt', ride=ride)
    subject = f'New Ride: {ride.title} — {ride.club.name}'
    _send_to_users('club_new_rides', subject, users, html, text)
    logger.info('New ride notification queued for ride %d to %d member(s)', ride.id, len(users))


def send_club_news_notification(post):
    """Notify active club members when a club admin publishes a news post."""
    from .models import ClubMembership
    memberships = ClubMembership.query.filter_by(club_id=post.club_id, status='active').all()
    users = [m.user for m in memberships]
    if not users:
        return False
    html = render_template('email/club_news.html', post=post)
    text = render_template('email/club_news.txt', post=post)
    subject = f'Club update: {post.title} — {post.club.name}'
    sent = _send_to_users('club_news', subject, users, html, text)
    logger.info('Club news notification queued for post %d to %d member(s)', post.id, len(users))
    return sent


def send_club_contact_message(club, sender, subject, message):
    """Relay a logged-in user's message to a club without exposing admin email addresses."""
    from .models import ClubAdmin

    recipients = set()
    if club.contact_email:
        recipients.add(club.contact_email)
    if club.owner and club.owner.email:
        recipients.add(club.owner.email)
    admin_rows = ClubAdmin.query.filter_by(club_id=club.id, role='admin').all()
    recipients.update(row.user.email for row in admin_rows if row.user and row.user.email)

    recipients = sorted(email for email in recipients if email)
    if not recipients:
        return False

    html = render_template('email/club_contact.html',
                           club=club, sender=sender, subject=subject, message=message)
    text = render_template('email/club_contact.txt',
                           club=club, sender=sender, subject=subject, message=message)
    sent = _send(f'[{club.name}] Message from {sender.username}: {subject}', recipients, html, text)
    logger.info('Club contact message for club %d sent to %d recipient(s)', club.id, len(recipients))
    return sent


def send_waitlist_promoted(signup):
    """Notify a user they've been promoted from the waitlist to confirmed."""
    ride = signup.ride
    user = signup.user
    if not user.email:
        return
    html = render_template('email/waitlist_promoted.html', ride=ride)
    text = render_template('email/waitlist_promoted.txt', ride=ride)
    subject = f"You're off the waitlist — {ride.title}"
    _send_to_users('ride_waitlist', subject, [user], html, text)
    logger.info('Waitlist promotion email sent to %s for ride %d', user.email, ride.id)


def send_invite_email(invite):
    """Send a club membership invite to the specified email address."""
    from flask import url_for
    claim_url = url_for('clubs.invite_claim', token=invite.token, _external=True)
    html = render_template('email/invite.html', invite=invite, claim_url=claim_url)
    text = render_template('email/invite.txt', invite=invite, claim_url=claim_url)
    subject = f"You're invited to join {invite.club.name}"
    _send(subject, [invite.email], html, text)
    logger.info('Invite email sent to %s for club %d', invite.email, invite.club_id)


def send_import_welcome_email(invite):
    """
    Send a new-account welcome email to a user created via bulk import.
    Includes a link to set their password and activate their Paceline account.
    """
    from flask import url_for
    setup_url = url_for('auth.setup_account', token=invite.token, _external=True)
    html = render_template('email/import_welcome.html', invite=invite, setup_url=setup_url)
    text = render_template('email/import_welcome.txt', invite=invite, setup_url=setup_url)
    subject = f"Welcome to {invite.club.name} — set up your Paceline account"
    _send(subject, [invite.email], html, text)
    logger.info('Import welcome email sent to %s for club %d', invite.email, invite.club_id)


def send_import_invite_email(invite):
    """
    Notify an existing Paceline user that a club admin has added them to a club.
    They must click to confirm before being added.
    """
    from flask import url_for
    claim_url = url_for('clubs.invite_claim', token=invite.token, _external=True)
    html = render_template('email/import_invite.html', invite=invite, claim_url=claim_url)
    text = render_template('email/import_invite.txt', invite=invite, claim_url=claim_url)
    subject = f"You've been added to {invite.club.name} on Paceline"
    _send(subject, [invite.email], html, text)
    logger.info('Import invite email sent to %s for club %d', invite.email, invite.club_id)


def send_dues_reminder(membership, days_until_expiry):
    """Notify a member that their club dues are expiring soon (or today)."""
    user = membership.user
    club = membership.club
    if not user or not user.email:
        return False
    if days_until_expiry == 0:
        subject = f'Your {club.name} membership expires today'
    else:
        subject = f'Your {club.name} membership expires in {days_until_expiry} day{"s" if days_until_expiry != 1 else ""}'
    html = render_template('email/dues_reminder.html', user=user, club=club,
                           membership=membership, days_until_expiry=days_until_expiry)
    text = render_template('email/dues_reminder.txt', user=user, club=club,
                           membership=membership, days_until_expiry=days_until_expiry)
    sent = _send_to_users('membership_updates', subject, [user], html, text)
    if sent:
        logger.info('Dues reminder (%dd) sent to %s for club %d', days_until_expiry, user.email, club.id)
    return sent


def send_password_reset_email(user, reset_url):
    """Send an email-verified password setup/reset link."""
    if not user.email:
        return
    html = render_template('email/password_reset.html', user=user, reset_url=reset_url)
    text = render_template('email/password_reset.txt', user=user, reset_url=reset_url)
    _send('Set or reset your Paceline password', [user.email], html, text)
    logger.info('Password reset email sent to %s', user.email)


def send_club_ownership_transfer_email(transfer, accept_url):
    """Ask the proposed new club owner to confirm an ownership transfer."""
    user = transfer.to_user
    if not user or not user.email:
        return
    html = render_template('email/club_ownership_transfer.html',
                           transfer=transfer, accept_url=accept_url)
    text = render_template('email/club_ownership_transfer.txt',
                           transfer=transfer, accept_url=accept_url)
    _send(f'Confirm ownership transfer — {transfer.club.name}', [user.email], html, text)
    logger.info('Club ownership transfer email sent to %s for club %d',
                user.email, transfer.club_id)


def send_weekly_digest(club, rides):
    """
    Send the Sunday weekly digest to all active club members.
    `rides` is the list of upcoming rides for the next 7 days, pre-queried by the caller.
    """
    from .models import ClubMembership
    memberships = ClubMembership.query.filter_by(club_id=club.id, status='active').all()
    users = [m.user for m in memberships]
    if not users:
        return
    html = render_template('email/weekly_digest.html', club=club, rides=rides)
    text = render_template('email/weekly_digest.txt', club=club, rides=rides)
    subject = f"This week's rides — {club.name}"
    _send_to_users('weekly_digest', subject, users, html, text)
    logger.info('Weekly digest queued for club %d (%s) to %d member(s)', club.id, club.name, len(users))


def send_reply_notification(reply):
    """Notify the post author that someone replied to their post."""
    post = reply.post
    user = post.author
    if not user.email:
        return
    html = render_template('email/reply_notification.html', reply=reply, post=post)
    text = render_template('email/reply_notification.txt', reply=reply, post=post)
    subject = f'[{post.club.name}] {reply.author.username} replied to your post'
    _send(subject, [user.email], html, text)
    logger.info('Reply notification sent to %s for post %d', user.email, post.id)


def send_mention_notification(user, author, post, body):
    """Notify a user they were @mentioned in a board post or reply."""
    if not user.email:
        return
    html = render_template('email/mention_notification.html',
                           user=user, author=author, post=post, body=body)
    text = render_template('email/mention_notification.txt',
                           user=user, author=author, post=post, body=body)
    subject = f'[{post.club.name}] {author.username} mentioned you on the board'
    _send(subject, [user.email], html, text)
    logger.info('Mention notification sent to %s for post %d', user.email, post.id)


def send_board_post_notification(post, user):
    """Notify a board subscriber that a new post was made."""
    if not user.email:
        return
    html = render_template('email/board_notification.html', post=post, user=user)
    text = render_template('email/board_notification.txt', post=post, user=user)
    subject = f'[{post.club.name}] New post from {post.author.username}'
    _send(subject, [user.email], html, text)
    logger.info('Board notification sent to %s for post %d', user.email, post.id)


def send_board_digest(user, items):
    if not user.email or not items:
        return False
    if not user_allows_email(user, 'board_digest') or not _cap_allows(user):
        return False
    grouped = defaultdict(list)
    for item in items:
        grouped[item.club].append(item)
    html = render_template('email/board_digest.html', user=user, grouped=grouped)
    text = render_template('email/board_digest.txt', user=user, grouped=grouped)
    subject = 'Your Paceline board activity digest'
    return _send_to_users('board_digest', subject, [user], html, text)


def send_friend_ride_notification(recipient, signer, ride):
    """Notify a user that an accepted friend just signed up for a ride they can see.

    recipient — the friend who should receive the notification
    signer    — the user who just signed up
    ride      — the Ride object
    """
    if not user_allows_email(recipient, 'friend_ride_signup'):
        return
    if not recipient.email:
        return
    try:
        from flask import url_for
        if ride.owner_id and not ride.club_id:
            ride_url = url_for('user_rides.detail', ride_id=ride.id, _external=True)
        elif ride.club_id:
            ride_url = url_for('clubs.ride_detail', slug=ride.club.slug, ride_id=ride.id, _external=True)
        else:
            ride_url = url_for('main.discover', _external=True)
        subject = f'@{signer.username} signed up for {ride.title}'
        date_str = ride.date.strftime('%B %-d')
        text = (
            f'Hi @{recipient.username},\n\n'
            f'Your friend @{signer.username} just signed up for "{ride.title}" on {date_str}.\n\n'
            f'View the ride: {ride_url}\n\n'
            f'To stop receiving these notifications, update your preferences: '
            f'{url_for("auth.profile", _external=True)}#notifications\n\n'
            f'— Paceline'
        )
        html = (
            f'<p>Hi @{recipient.username},</p>'
            f'<p>Your friend <strong>@{signer.username}</strong> just signed up for '
            f'<strong>{ride.title}</strong> on {date_str}.</p>'
            f'<p><a href="{ride_url}">View the ride →</a></p>'
            f'<p style="color:#888;font-size:.9em">To stop receiving these notifications, '
            f'<a href="{url_for("auth.profile", _external=True)}#notifications">update your preferences</a>.</p>'
        )
        _send(subject, [recipient.email], html, text)
    except Exception:
        logger.exception('Failed to send friend ride notification to user %d', recipient.id)


def send_stripe_error_alert(event_type, payment_intent_id, error_message, payment=None):
    """Alert the platform owner about a Stripe payment failure."""
    recipient = 'phil@pcp.dev'
    club_name = payment.membership.club.name if payment and payment.membership else 'Unknown'
    username = payment.user.username if payment and payment.user else 'Unknown'
    amount_str = f'${payment.amount_cents / 100:.2f}' if payment else '—'

    html = render_template(
        'email/stripe_error_alert.html',
        event_type=event_type,
        payment_intent_id=payment_intent_id,
        error_message=error_message,
        club_name=club_name,
        username=username,
        amount_str=amount_str,
        payment=payment,
    )
    text = render_template(
        'email/stripe_error_alert.txt',
        event_type=event_type,
        payment_intent_id=payment_intent_id,
        error_message=error_message,
        club_name=club_name,
        username=username,
        amount_str=amount_str,
        payment=payment,
    )
    try:
        _send(f'[Paceline] Stripe payment failure: {event_type}', [recipient], html, text)
        logger.info('Stripe error alert sent to %s for %s', recipient, payment_intent_id)
    except Exception:
        logger.exception('Failed to send Stripe error alert for %s', payment_intent_id)


def send_feedback_notification(feedback):
    """Notify superadmins that new site feedback was submitted."""
    from .admin_stats import configured_superadmin_emails
    from .models import User

    configured = configured_superadmin_emails()
    active_admins = User.query.filter_by(is_admin=True, is_active=True).all()
    recipients = sorted({
        email
        for email in configured | {user.email for user in active_admins if user.email}
        if email
    })
    if not recipients:
        return
    html = render_template('email/feedback_notification.html', feedback=feedback)
    text = render_template('email/feedback_notification.txt', feedback=feedback)
    _send('New Paceline feedback received', recipients, html, text)
    logger.info('Feedback notification sent for feedback %d to %d recipient(s)', feedback.id, len(recipients))
