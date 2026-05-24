"""
APScheduler background job: weather-based ride auto-cancel.

Runs once daily (configurable via AUTO_CANCEL_HOUR, default 6 AM local time).
For every club with auto_cancel_enabled=True, checks all non-cancelled rides
scheduled for today and marks them cancelled if weather exceeds thresholds.
"""
import logging
from datetime import date

from .weather import get_weather_for_rides
from .email import send_board_digest, send_cancellation_emails, send_dues_reminder, send_ride_reminder, send_weekly_digest
from .storage import get_storage

logger = logging.getLogger(__name__)


def check_auto_cancels(app):
    """Called by the scheduler; runs inside a pushed app context."""
    with app.app_context():
        from .extensions import db
        from .models import Club, Ride

        today = date.today()
        clubs = Club.query.filter_by(is_active=True, auto_cancel_enabled=True).all()

        cancelled_count = 0
        for club in clubs:
            rides_today = (
                Ride.query
                .filter_by(club_id=club.id, is_cancelled=False)
                .filter(Ride.date == today)
                .all()
            )
            if not rides_today:
                continue

            lat = club.lat or None
            lng = club.lng or None
            weather = get_weather_for_rides(rides_today, lat=lat, lng=lng)

            for ride in rides_today:
                w = weather.get(ride.id)
                if w is None:
                    continue

                reasons = []
                if w['precip_prob'] >= club.cancel_rain_prob:
                    reasons.append(f"{w['precip_prob']}% precipitation probability (threshold {club.cancel_rain_prob}%)")
                if w['wind_mph'] >= club.cancel_wind_mph:
                    reasons.append(f"{w['wind_mph']} mph winds (threshold {club.cancel_wind_mph} mph)")
                if w['temp_f'] < club.cancel_temp_min_f:
                    reasons.append(f"{w['temp_f']}°F below minimum {club.cancel_temp_min_f}°F")
                if w['temp_f'] > club.cancel_temp_max_f:
                    reasons.append(f"{w['temp_f']}°F above maximum {club.cancel_temp_max_f}°F")

                if reasons:
                    ride.is_cancelled = True
                    ride.cancel_reason = 'Auto-cancelled due to weather: ' + '; '.join(reasons)
                    cancelled_count += 1
                    logger.info('Auto-cancelled ride %d (%s) — %s', ride.id, ride.title, ride.cancel_reason)

            db.session.commit()

            # Send cancellation emails after committing so ride state is final
            for ride in rides_today:
                if ride.is_cancelled and ride.cancel_reason and 'Auto-cancelled' in ride.cancel_reason:
                    send_cancellation_emails(ride)

        if cancelled_count:
            logger.info('Auto-cancel job: %d ride(s) cancelled for %s', cancelled_count, today)
        else:
            logger.debug('Auto-cancel job: no cancellations for %s', today)


def send_reminders(app):
    """Send morning-of ride reminders to all signed-up riders."""
    with app.app_context():
        from .extensions import db
        from .models import Ride
        today = date.today()
        rides_today = (
            Ride.query
            .filter_by(is_cancelled=False)
            .filter(Ride.date == today)
            .all()
        )
        for ride in rides_today:
            if ride.signups:
                send_ride_reminder(ride)
        logger.debug('Reminder job: processed %d ride(s) for %s', len(rides_today), today)


def send_weekly_digests(app):
    """Send the Sunday morning ride preview digest to all active club members."""
    with app.app_context():
        from .models import Club, Ride
        from datetime import timedelta
        today = date.today()
        week_end = today + timedelta(days=7)
        clubs = Club.query.filter_by(is_active=True).all()
        for club in clubs:
            upcoming = (
                Ride.query
                .filter_by(club_id=club.id, is_cancelled=False)
                .filter(Ride.date >= today, Ride.date < week_end)
                .order_by(Ride.date, Ride.time)
                .all()
            )
            send_weekly_digest(club, upcoming)
        logger.info('Weekly digest job: processed %d club(s)', len(clubs))


def send_board_activity_digests(app):
    """Send daily board activity digests for queued board notifications."""
    with app.app_context():
        from datetime import datetime, timezone
        from .extensions import db
        from .models import BoardDigestItem, User

        user_ids = [
            user_id for (user_id,) in
            db.session.query(BoardDigestItem.user_id)
            .filter(BoardDigestItem.sent_at.is_(None))
            .distinct()
            .all()
        ]
        sent_count = 0
        now = datetime.now(timezone.utc)
        for user_id in user_ids:
            user = db.session.get(User, user_id)
            if not user or not user.is_active:
                continue
            items = (
                BoardDigestItem.query
                .filter(BoardDigestItem.user_id == user_id, BoardDigestItem.sent_at.is_(None))
                .order_by(BoardDigestItem.created_at.asc())
                .limit(50)
                .all()
            )
            if send_board_digest(user, items):
                for item in items:
                    item.sent_at = now
                sent_count += 1
        db.session.commit()
        logger.info('Board digest job: sent %d digest email(s)', sent_count)


def send_dues_expiry_reminders(app):
    """Send dues renewal reminders at 30, 7, and 0 days before expiry."""
    from datetime import timedelta
    with app.app_context():
        from .extensions import db
        from .models import ClubMembership
        today = date.today()
        thresholds = [30, 7, 0]
        target_dates = {d: today + timedelta(days=d) for d in thresholds}
        candidates = (
            ClubMembership.query
            .filter(
                ClubMembership.status == 'active',
                ClubMembership.dues_paid_until.in_(target_dates.values()),
            )
            .all()
        )
        sent_count = 0
        for membership in candidates:
            if not membership.club.membership_dues_required:
                continue
            days_out = (membership.dues_paid_until - today).days
            key = str(days_out)
            already_sent = (membership.dues_reminder_sent or {}).get(key)
            if already_sent:
                continue
            if send_dues_reminder(membership, days_out):
                sent = dict(membership.dues_reminder_sent or {})
                sent[key] = today.isoformat()
                membership.dues_reminder_sent = sent
                sent_count += 1
        if sent_count:
            db.session.commit()
        logger.info('Dues reminder job: sent %d reminder(s) for %s', sent_count, today)


def purge_expired_media(app):
    """
    Delete ride media and board media older than MEDIA_EXPIRY_DAYS (default 90).
    Runs nightly. Removes both DB records and files from the active storage backend
    (local filesystem or DigitalOcean Spaces).
    """
    from datetime import timedelta
    with app.app_context():
        from .extensions import db
        from .models import ClubBoardMedia, ClubBoardPost, Ride, RideMedia
        expiry_days = app.config.get('MEDIA_EXPIRY_DAYS', 90)
        upload_folder = app.config.get('UPLOAD_FOLDER', '')
        storage = get_storage(app)
        cutoff = date.today() - timedelta(days=expiry_days)

        # Ride media
        expired_ride = (RideMedia.query
                        .join(Ride, RideMedia.ride_id == Ride.id)
                        .filter(Ride.date < cutoff)
                        .all())
        deleted_files = 0
        for item in expired_ride:
            if item.file_path:
                storage.delete(item.file_path, upload_folder=upload_folder)
                deleted_files += 1
            db.session.delete(item)

        # Board media — keyed on post.created_at
        from datetime import datetime, timezone
        board_cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=expiry_days)
        expired_board = (ClubBoardMedia.query
                         .join(ClubBoardPost, ClubBoardMedia.post_id == ClubBoardPost.id)
                         .filter(ClubBoardPost.created_at < board_cutoff)
                         .all())
        for item in expired_board:
            if item.file_path:
                storage.delete(item.file_path, upload_folder=upload_folder)
                deleted_files += 1
            db.session.delete(item)

        db.session.commit()
        total = len(expired_ride) + len(expired_board)
        if total:
            logger.info('Media purge: removed %d records (%d files) older than %d days',
                        total, deleted_files, expiry_days)


def purge_old_error_logs(app):
    """Delete app_error_logs entries older than ERROR_LOG_RETENTION_DAYS (default 30)."""
    from datetime import timedelta, datetime, timezone
    with app.app_context():
        from .extensions import db
        from .models import AppErrorLog
        retention_days = app.config.get('ERROR_LOG_RETENTION_DAYS', 30)
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        deleted = AppErrorLog.query.filter(AppErrorLog.created_at < cutoff).delete()
        if deleted:
            db.session.commit()
            logger.info('Error log purge: removed %d entries older than %d days', deleted, retention_days)


def process_expired_polls(app):
    """Close open polls whose closes_at has passed; auto-finalize if mode='auto'."""
    from datetime import datetime
    with app.app_context():
        from .extensions import db
        from .models import RidePoll
        now = datetime.utcnow()
        expired = RidePoll.query.filter(
            RidePoll.status == 'open',
            RidePoll.closes_at <= now,
        ).all()
        for poll in expired:
            poll.status = 'closed'
            db.session.commit()
            if poll.finalize_mode == 'auto':
                try:
                    from .routes.polls import _auto_finalize_poll
                    _auto_finalize_poll(poll, poll.club)
                except Exception:
                    logger.exception('Auto-finalize failed for poll %d', poll.id)
            else:
                try:
                    from .email import send_poll_closed_leader
                    send_poll_closed_leader(poll)
                except Exception:
                    logger.exception('Poll closed email failed for poll %d', poll.id)
            logger.info('Poll %d (%s) closed via scheduler', poll.id, poll.title)


def init_scheduler(app):
    """Start the APScheduler background scheduler if AUTO_CANCEL_ENABLED config is set."""
    if not app.config.get('AUTO_CANCEL_ENABLED', True):
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        logger.warning('APScheduler not installed — weather auto-cancel disabled')
        return

    hour = app.config.get('AUTO_CANCEL_HOUR', 6)
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(
        func=check_auto_cancels,
        trigger=CronTrigger(hour=hour, minute=0),
        args=[app],
        id='weather_auto_cancel',
        name='Weather-based ride auto-cancel',
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        func=send_reminders,
        trigger=CronTrigger(hour=hour, minute=15),
        args=[app],
        id='ride_reminders',
        name='Morning ride reminders',
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        func=send_weekly_digests,
        trigger=CronTrigger(day_of_week='sun', hour=7, minute=0),
        args=[app],
        id='weekly_digest',
        name='Sunday weekly ride digest',
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        func=send_board_activity_digests,
        trigger=CronTrigger(hour=18, minute=0),
        args=[app],
        id='board_activity_digest',
        name='Daily board activity digest',
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        func=send_dues_expiry_reminders,
        trigger=CronTrigger(hour=8, minute=0),
        args=[app],
        id='dues_expiry_reminders',
        name='Dues expiry reminder emails',
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        func=purge_expired_media,
        trigger=CronTrigger(hour=2, minute=30),
        args=[app],
        id='media_purge',
        name='Purge expired ride media',
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        func=purge_old_error_logs,
        trigger=CronTrigger(hour=3, minute=0),
        args=[app],
        id='error_log_purge',
        name='Purge old error log entries',
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        func=process_expired_polls,
        trigger='interval',
        minutes=10,
        args=[app],
        id='poll_expiry',
        name='Process expired ride polls',
        replace_existing=True,
        misfire_grace_time=600,
    )
    scheduler.start()
    logger.info('Auto-cancel scheduler started (runs daily at %02d:00)', hour)
    return scheduler
