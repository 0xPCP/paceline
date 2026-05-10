import os
import shutil
import time
from collections import OrderedDict
from datetime import date, datetime, timedelta, timezone

from flask import current_app
from sqlalchemy import func

from .extensions import db
from .models import AppErrorLog, Club, EmailDeliveryLog, Ride, RideMedia, RideSignup, User


def configured_superadmin_emails():
    raw = current_app.config.get('SUPERADMIN_EMAILS', '')
    return {
        email.strip().lower()
        for email in raw.split(',')
        if email.strip()
    }


def active_superadmin_count(exclude_user_id=None):
    query = User.query.filter_by(is_admin=True, is_active=True)
    if exclude_user_id is not None:
        query = query.filter(User.id != exclude_user_id)
    return query.count()


def _month_start(day):
    return date(day.year, day.month, 1)


def _add_months(day, months):
    month = day.month - 1 + months
    year = day.year + month // 12
    month = month % 12 + 1
    return date(year, month, 1)


def _last_months(count=12):
    start = _add_months(_month_start(date.today()), -(count - 1))
    return [_add_months(start, idx) for idx in range(count)]


def _count_by_month(rows, attr_name):
    counts = OrderedDict((month, 0) for month in _last_months())
    first_month = next(iter(counts))
    for row in rows:
        value = getattr(row, attr_name)
        if isinstance(value, datetime):
            value = value.date()
        if not value:
            continue
        month = _month_start(value)
        if month >= first_month and month in counts:
            counts[month] += 1
    return [
        {'label': month.strftime('%b %Y'), 'count': count}
        for month, count in counts.items()
    ]


def _with_bar_width(points):
    max_count = max([point['count'] for point in points] or [0])
    for point in points:
        point['width'] = 0 if max_count == 0 else max(4, round((point['count'] / max_count) * 100))
    return points


def _directory_size(path):
    total = 0
    if not path or not os.path.exists(path):
        return 0
    for root, _, files in os.walk(path):
        for filename in files:
            try:
                total += os.path.getsize(os.path.join(root, filename))
            except OSError:
                continue
    return total


def _bytes_label(value):
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    size = float(value or 0)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f'{size:.1f} {unit}' if unit != 'B' else f'{int(size)} B'
        size /= 1024
    return f'{size:.1f} TB'


def storage_report():
    upload_folder = current_app.config.get('UPLOAD_FOLDER', '')
    media_bytes = _directory_size(upload_folder)

    disk = None
    disk_percent = None
    disk_warning = None
    using_spaces = bool(current_app.config.get('SPACES_BUCKET', '').strip())

    if not using_spaces:
        # Local storage: probe the upload folder's filesystem
        probe_path = upload_folder
        while probe_path and not os.path.exists(probe_path):
            parent = os.path.dirname(probe_path)
            if parent == probe_path:
                break
            probe_path = parent
        if probe_path and os.path.exists(probe_path):
            try:
                usage = shutil.disk_usage(probe_path)
                disk_percent = round((usage.used / usage.total) * 100, 1) if usage.total else 0
                disk = {
                    'total': usage.total,
                    'used': usage.used,
                    'free': usage.free,
                    'percent': disk_percent,
                    'total_label': _bytes_label(usage.total),
                    'used_label': _bytes_label(usage.used),
                    'free_label': _bytes_label(usage.free),
                    'backend': 'local',
                }
            except OSError:
                disk = None

        warning_pct = current_app.config.get('STORAGE_WARNING_PERCENT', 80)
        critical_pct = current_app.config.get('STORAGE_CRITICAL_PERCENT', 90)
        if disk_percent is not None:
            if disk_percent >= critical_pct:
                disk_warning = 'critical'
            elif disk_percent >= warning_pct:
                disk_warning = 'warning'
    else:
        disk = {
            'backend': 'spaces',
            'bucket': current_app.config.get('SPACES_BUCKET', ''),
            'region': current_app.config.get('SPACES_REGION', ''),
        }

    media_warning_mb = current_app.config.get('MEDIA_STORAGE_WARNING_MB', 1024)
    media_warning = media_bytes >= media_warning_mb * 1024 * 1024

    return {
        'upload_folder': upload_folder,
        'media_bytes': media_bytes,
        'media_label': _bytes_label(media_bytes),
        'photo_count': RideMedia.query.filter_by(media_type='photo').count(),
        'video_count': RideMedia.query.filter_by(media_type='video_link').count(),
        'disk': disk,
        'disk_warning': disk_warning,
        'media_warning': media_warning,
    }


def email_report():
    now = datetime.now(timezone.utc)
    today_start = datetime.combine(now.date(), datetime.min.time())
    month_start = datetime(now.year, now.month, 1)
    year_start = datetime(now.year, 1, 1)

    def count_since(status, start):
        return (
            db.session.query(func.sum(EmailDeliveryLog.recipient_count))
            .filter(EmailDeliveryLog.status == status, EmailDeliveryLog.created_at >= start)
            .scalar()
            or 0
        )

    total_sent = (
        db.session.query(func.sum(EmailDeliveryLog.recipient_count))
        .filter(EmailDeliveryLog.status == 'sent')
        .scalar()
        or 0
    )
    failed_30d = (
        db.session.query(func.count(EmailDeliveryLog.id))
        .filter(
            EmailDeliveryLog.status == 'failed',
            EmailDeliveryLog.created_at >= now - timedelta(days=30),
        )
        .scalar()
        or 0
    )
    last_success = (
        EmailDeliveryLog.query
        .filter_by(status='sent')
        .order_by(EmailDeliveryLog.created_at.desc())
        .first()
    )
    last_failure = (
        EmailDeliveryLog.query
        .filter_by(status='failed')
        .order_by(EmailDeliveryLog.created_at.desc())
        .first()
    )

    provider = current_app.config.get('EMAIL_PROVIDER') or ('resend' if current_app.config.get('RESEND_API_KEY') else 'smtp')
    resend_configured = bool(current_app.config.get('RESEND_API_KEY'))
    smtp_configured = bool(current_app.config.get('MAIL_SERVER'))
    configured = resend_configured if provider == 'resend' else smtp_configured
    status = 'configured' if configured else 'not_configured'
    if configured and last_failure and (not last_success or last_failure.created_at > last_success.created_at):
        status = 'attention'

    return {
        'provider': provider,
        'status': status,
        'resend_configured': resend_configured,
        'smtp_configured': smtp_configured,
        'from_address': current_app.config.get('MAIL_DEFAULT_SENDER', ''),
        'recipient_override': current_app.config.get('EMAIL_RECIPIENT_OVERRIDE', ''),
        'sent_today': count_since('sent', today_start),
        'sent_month': count_since('sent', month_start),
        'sent_year': count_since('sent', year_start),
        'total_sent': total_sent,
        'failed_30d': failed_30d,
        'last_success': last_success,
        'last_failure': last_failure,
    }


def error_report():
    now = datetime.now(timezone.utc)
    cutoff_24h = now - timedelta(hours=24)
    cutoff_7d = now - timedelta(days=7)

    errors_24h = AppErrorLog.query.filter(AppErrorLog.created_at >= cutoff_24h).count()
    errors_24h_500 = (AppErrorLog.query
                      .filter(AppErrorLog.created_at >= cutoff_24h, AppErrorLog.status_code >= 500)
                      .count())
    errors_7d = AppErrorLog.query.filter(AppErrorLog.created_at >= cutoff_7d).count()
    recent = (AppErrorLog.query
              .order_by(AppErrorLog.created_at.desc())
              .limit(20)
              .all())

    return {
        'errors_24h': errors_24h,
        'errors_24h_500': errors_24h_500,
        'errors_7d': errors_7d,
        'recent': recent,
    }


def platform_report(started_at):
    today = date.today()
    thirty_days_ago = datetime.combine(today - timedelta(days=30), datetime.min.time())
    seven_days_ago = datetime.combine(today - timedelta(days=7), datetime.min.time())

    total_miles = (db.session.query(func.sum(Ride.distance_miles))
                   .filter(Ride.is_cancelled == False).scalar() or 0)
    active_rider_ids = {
        user_id for (user_id,) in db.session.query(RideSignup.user_id).distinct().all()
    } | {
        user_id for (user_id,) in db.session.query(Ride.created_by)
        .filter(Ride.created_by.isnot(None)).distinct().all()
    }

    stats = {
        'total_clubs': Club.query.filter_by(is_active=True).count(),
        'inactive_clubs': Club.query.filter_by(is_active=False).count(),
        'total_members': User.query.count(),
        'active_users': User.query.filter_by(is_active=True).count(),
        'inactive_users': User.query.filter_by(is_active=False).count(),
        'new_users_7d': User.query.filter(User.created_at >= seven_days_ago).count(),
        'new_users_30d': User.query.filter(User.created_at >= thirty_days_ago).count(),
        'new_clubs_30d': Club.query.filter(Club.created_at >= thirty_days_ago).count(),
        'rides_30d': Ride.query.filter(Ride.date >= today - timedelta(days=30), Ride.date <= today).count(),
        'upcoming_rides': Ride.query.filter(Ride.date >= today, Ride.is_cancelled == False).count(),
        'total_rides': Ride.query.count(),
        'total_signups': RideSignup.query.count(),
        'active_riders': len(active_rider_ids),
        'total_miles': round(total_miles),
    }

    user_growth = _with_bar_width(_count_by_month(User.query.all(), 'created_at'))
    club_growth = _with_bar_width(_count_by_month(Club.query.all(), 'created_at'))
    ride_growth = _with_bar_width(_count_by_month(Ride.query.all(), 'date'))

    elapsed_ms = round((time.perf_counter() - started_at) * 1000)
    slow_threshold = current_app.config.get('ADMIN_DASHBOARD_SLOW_MS', 1500)

    return {
        'stats': stats,
        'user_growth': user_growth,
        'club_growth': club_growth,
        'ride_growth': ride_growth,
        'storage': storage_report(),
        'email': email_report(),
        'errors': error_report(),
        'dashboard_elapsed_ms': elapsed_ms,
        'dashboard_slow': elapsed_ms >= slow_threshold,
        'slow_threshold_ms': slow_threshold,
    }
