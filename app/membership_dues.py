import calendar
from datetime import date, datetime, timezone


def add_months(start_date, months):
    month = start_date.month - 1 + max(1, int(months or 12))
    year = start_date.year + month // 12
    month = month % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(start_date.day, last_day))


def default_dues_expiration(club, start_date=None):
    return add_months(start_date or date.today(), club.membership_duration_months or 12)


def activate_membership_dues(membership, confirmed_by=None, paid_at=None):
    membership.status = 'active'
    # If renewing early, stack from the existing expiry date rather than today.
    start = membership.dues_paid_until if membership.dues_paid_until and membership.dues_paid_until > date.today() else None
    membership.dues_paid_until = default_dues_expiration(membership.club, start_date=start)
    membership.dues_confirmed_at = paid_at or datetime.now(timezone.utc)
    membership.dues_confirmed_by_id = confirmed_by.id if confirmed_by else None
    membership.dues_reminder_sent = None
