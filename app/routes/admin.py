from functools import wraps
import io
import re
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from flask import Blueprint, render_template, redirect, url_for, flash, abort, request, current_app
from flask_login import login_required, current_user, login_fresh
import secrets
import string
from markupsafe import Markup, escape as html_escape
from sqlalchemy import or_, func
from ..extensions import db, bcrypt
from ..models import (AdminAuditLog, AdminMessage, AppErrorLog, BoardDigestItem, Club,
                      ClubBoardPost, ClubBoardReaction, ClubBoardReply,
                      ClubBoardSubscription, Ride, RideComment, RideMedia,
                      RideSignup, PlatformPost, SiteFeedback, User, UserEmailLog,
                      ClubMembership, ClubMembershipPayment, ClubAdmin, ClubPost,
                      ClubLeader, ClubSponsor, ClubInvite, ClubOwnershipTransfer,
                      ClubShopItem, ClubShopOrder, UserRecommendationHidden)
from ..forms import RideForm, ClubForm, ClubSettingsForm, ClubPostForm, PlatformPostForm, ClubLeaderForm, ClubSponsorForm, ClubInviteForm, BulkImportForm, ClubShopItemForm, ClubShopSettingsForm, selected_ride_paces, validate_ride_paces, populate_ride_pace_fields
from ..recurrence import generate_instances, delete_future_instances
from ..geocoding import geocode_zip
from ..storage import get_storage
from ..utils import process_logo_image, process_post_image
from ..membership_dues import activate_membership_dues, default_dues_expiration
from ..admin_stats import (active_superadmin_count, configured_superadmin_emails,
                           platform_report)
from ..email import (send_cancellation_emails, send_new_ride_notification,
                     send_membership_approved, send_membership_rejected, send_invite_email,
                     send_import_welcome_email, send_import_invite_email,
                     send_club_ownership_transfer_email, send_club_news_notification,
                     set_site_setting,
                     send_admin_message_to_club, send_club_reply_to_superadmin,
                     send_broadcast_to_club_admins)

admin_bp = Blueprint('admin', __name__)


def _audit(action, target_user=None, details=None):
    db.session.add(AdminAuditLog(
        actor_id=current_user.id if current_user.is_authenticated else None,
        target_user_id=target_user.id if target_user else None,
        action=action,
        details=details,
    ))


def _get_club_or_404(slug):
    return Club.query.filter_by(slug=slug, is_active=True).first_or_404()


def _ensure_owner_membership_and_admin(club, user):
    membership = ClubMembership.query.filter_by(user_id=user.id, club_id=club.id).first()
    if membership:
        membership.status = 'active'
    else:
        db.session.add(ClubMembership(user_id=user.id, club_id=club.id, status='active'))

    admin_row = ClubAdmin.query.filter_by(user_id=user.id, club_id=club.id).first()
    if admin_row:
        admin_row.role = 'admin'
    else:
        db.session.add(ClubAdmin(user_id=user.id, club_id=club.id, role='admin'))

    club.owner_id = user.id


def _confirm_membership_dues(membership, confirmed_by):
    activate_membership_dues(membership, confirmed_by=confirmed_by)


def _can_transfer_club_owner(club):
    owner = club.effective_owner
    if current_user.is_admin:
        return True
    if owner and owner.id == current_user.id:
        return True
    return owner is None and current_user.is_club_admin(club)


def _club_admin_activity_stats(club, today=None):
    today = today or date.today()
    window_start = today - timedelta(days=30)
    window_end = today + timedelta(days=30)
    now = datetime.now(timezone.utc)
    window_start_dt = now - timedelta(days=30)

    ride_type_rows = (db.session.query(Ride.ride_type, func.count(Ride.id))
                      .filter(
                          Ride.club_id == club.id,
                          Ride.date >= window_start,
                          Ride.date <= window_end,
                          Ride.is_cancelled == False,  # noqa: E712
                      )
                      .group_by(Ride.ride_type)
                      .order_by(func.count(Ride.id).desc())
                      .limit(4)
                      .all())
    ride_type_counts = [
        {
            'label': (ride_type or 'road').replace('_', ' ').title(),
            'count': int(count or 0),
        }
        for ride_type, count in ride_type_rows
    ]

    dues_revenue = (db.session.query(func.coalesce(func.sum(ClubMembershipPayment.amount_cents), 0))
                    .filter(
                        ClubMembershipPayment.club_id == club.id,
                        ClubMembershipPayment.status == 'paid',
                        ClubMembershipPayment.paid_at >= window_start_dt,
                    )
                    .scalar() or 0)
    shop_revenue = (db.session.query(func.coalesce(func.sum(ClubShopOrder.amount_cents), 0))
                    .filter(
                        ClubShopOrder.club_id == club.id,
                        ClubShopOrder.status == 'paid',
                        ClubShopOrder.paid_at >= window_start_dt,
                    )
                    .scalar() or 0)

    return {
        'members_30d': ClubMembership.query.filter(
            ClubMembership.club_id == club.id,
            ClubMembership.status == 'active',
            ClubMembership.joined_at >= window_start_dt,
        ).count(),
        'rides_last_30d': Ride.query.filter(
            Ride.club_id == club.id,
            Ride.date >= window_start,
            Ride.date < today,
            Ride.is_cancelled == False,  # noqa: E712
        ).count(),
        'rides_next_30d': Ride.query.filter(
            Ride.club_id == club.id,
            Ride.date >= today,
            Ride.date <= window_end,
            Ride.is_cancelled == False,  # noqa: E712
        ).count(),
        'signups_30d': (RideSignup.query
                        .join(Ride, RideSignup.ride_id == Ride.id)
                        .filter(
                            Ride.club_id == club.id,
                            RideSignup.created_at >= window_start_dt,
                        )
                        .count()),
        'waitlist_30d': (RideSignup.query
                         .join(Ride, RideSignup.ride_id == Ride.id)
                         .filter(
                             Ride.club_id == club.id,
                             RideSignup.created_at >= window_start_dt,
                             RideSignup.is_waitlist == True,  # noqa: E712
                         )
                         .count()),
        'dues_revenue_30d': int(dues_revenue),
        'shop_revenue_30d': int(shop_revenue),
        'ride_type_counts': ride_type_counts,
    }


def _find_user_by_email(email):
    email = (email or '').strip().lower()
    if not email:
        return None
    return User.query.filter(func.lower(User.email) == email).first()


def _is_deletable_test_user(user):
    if user is None or user.is_admin:
        return False
    email = (user.email or '').lower()
    username = (user.username or '').lower()
    return (
        re.fullmatch(r'audit_[a-z0-9_]+_\d{14}@example\.com', email) is not None
        or email.endswith('@test.paceline.local')
        or username.startswith('audit_')
    )


def _delete_test_user_records(user):
    """Delete artifacts for an obvious test user.

    This is intentionally narrower than a general user-delete feature. It is for
    repeatable live smoke tests and refuses accounts that do not look generated.
    """
    owned_clubs = Club.query.filter_by(owner_id=user.id).all()
    non_test_clubs = [club.slug for club in owned_clubs if not club.slug.startswith('audit-')]
    if non_test_clubs:
        return False, f'This test user still owns non-test clubs: {", ".join(non_test_clubs)}.'

    deleted_clubs = 0
    for club in owned_clubs:
        db.session.delete(club)
        deleted_clubs += 1

    deleted_rides = 0
    for ride in Ride.query.filter_by(owner_id=user.id).all():
        db.session.delete(ride)
        deleted_rides += 1

    Ride.query.filter_by(leader_id=user.id).update({'leader_id': None}, synchronize_session=False)
    Ride.query.filter_by(created_by=user.id).update({'created_by': None}, synchronize_session=False)
    ClubMembership.query.filter_by(dues_confirmed_by_id=user.id).update({'dues_confirmed_by_id': None}, synchronize_session=False)
    ClubPost.query.filter_by(author_id=user.id).update({'author_id': None}, synchronize_session=False)
    ClubLeader.query.filter_by(user_id=user.id).update({'user_id': None}, synchronize_session=False)
    BoardDigestItem.query.filter_by(actor_id=user.id).update({'actor_id': None}, synchronize_session=False)
    ClubInvite.query.filter_by(used_by_user_id=user.id).update({'used_by_user_id': None}, synchronize_session=False)
    AdminAuditLog.query.filter_by(actor_id=user.id).update({'actor_id': None}, synchronize_session=False)
    AdminAuditLog.query.filter_by(target_user_id=user.id).update({'target_user_id': None}, synchronize_session=False)
    SiteFeedback.query.filter_by(user_id=user.id).update({'user_id': None}, synchronize_session=False)
    SiteFeedback.query.filter_by(read_by_id=user.id).update({'read_by_id': None}, synchronize_session=False)
    AppErrorLog.query.filter_by(user_id=user.id).update({'user_id': None}, synchronize_session=False)

    ClubMembershipPayment.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    ClubOwnershipTransfer.query.filter(
        or_(ClubOwnershipTransfer.from_user_id == user.id, ClubOwnershipTransfer.to_user_id == user.id)
    ).delete(synchronize_session=False)
    RideSignup.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    RideMedia.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    RideComment.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    ClubBoardSubscription.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    ClubBoardReaction.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    ClubBoardReply.query.filter_by(author_id=user.id).delete(synchronize_session=False)
    for post in ClubBoardPost.query.filter_by(author_id=user.id).all():
        db.session.delete(post)
    ClubInvite.query.filter_by(created_by=user.id).delete(synchronize_session=False)
    BoardDigestItem.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    UserEmailLog.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    UserRecommendationHidden.query.filter_by(user_id=user.id).delete(synchronize_session=False)

    user_id = user.id
    email = user.email
    username = user.username
    db.session.delete(user)
    _audit('delete_test_user', details=f'user_id={user_id}; email={email}; username={username}; deleted_clubs={deleted_clubs}; deleted_rides={deleted_rides}')
    return True, f'Deleted test user {username} and related test artifacts.'


def _delete_user_records(user):
    """Permanently delete a user and detach/delete dependent records.

    This is intentionally explicit instead of relying on database-level cascade
    behavior because Paceline uses a mix of nullable attribution fields and
    required ownership fields.
    """
    from ..models import DuesEditLog, UserBike, UserFriend, UserRideInvite

    user_id = user.id
    email = user.email
    username = user.username

    owned_club_count = Club.query.filter_by(owner_id=user_id).update(
        {'owner_id': None}, synchronize_session=False)

    owned_ride_count = 0
    for ride in Ride.query.filter_by(owner_id=user_id).all():
        db.session.delete(ride)
        owned_ride_count += 1

    Ride.query.filter_by(leader_id=user_id).update({'leader_id': None}, synchronize_session=False)
    Ride.query.filter_by(created_by=user_id).update({'created_by': None}, synchronize_session=False)
    ClubMembership.query.filter_by(dues_confirmed_by_id=user_id).update({'dues_confirmed_by_id': None}, synchronize_session=False)
    ClubPost.query.filter_by(author_id=user_id).update({'author_id': None}, synchronize_session=False)
    PlatformPost.query.filter_by(author_id=user_id).update({'author_id': None}, synchronize_session=False)
    ClubLeader.query.filter_by(user_id=user_id).update({'user_id': None}, synchronize_session=False)
    BoardDigestItem.query.filter_by(actor_id=user_id).update({'actor_id': None}, synchronize_session=False)
    ClubInvite.query.filter_by(used_by_user_id=user_id).update({'used_by_user_id': None}, synchronize_session=False)
    AdminAuditLog.query.filter_by(actor_id=user_id).update({'actor_id': None}, synchronize_session=False)
    AdminAuditLog.query.filter_by(target_user_id=user_id).update({'target_user_id': None}, synchronize_session=False)
    SiteFeedback.query.filter_by(user_id=user_id).update({'user_id': None}, synchronize_session=False)
    SiteFeedback.query.filter_by(read_by_id=user_id).update({'read_by_id': None}, synchronize_session=False)
    AppErrorLog.query.filter_by(user_id=user_id).update({'user_id': None}, synchronize_session=False)

    membership_ids = [m.id for m in ClubMembership.query.filter_by(user_id=user_id).all()]
    if membership_ids:
        DuesEditLog.query.filter(DuesEditLog.membership_id.in_(membership_ids)).delete(synchronize_session=False)
    DuesEditLog.query.filter_by(edited_by_id=user_id).delete(synchronize_session=False)

    for post in ClubBoardPost.query.filter_by(author_id=user_id).all():
        BoardDigestItem.query.filter_by(post_id=post.id).delete(synchronize_session=False)
        db.session.delete(post)

    ClubMembershipPayment.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    ClubShopOrder.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    ClubOwnershipTransfer.query.filter(
        or_(ClubOwnershipTransfer.from_user_id == user_id, ClubOwnershipTransfer.to_user_id == user_id)
    ).delete(synchronize_session=False)
    RideSignup.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    RideMedia.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    RideComment.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    ClubBoardSubscription.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    ClubBoardReaction.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    ClubBoardReply.query.filter_by(author_id=user_id).delete(synchronize_session=False)
    ClubInvite.query.filter_by(created_by=user_id).delete(synchronize_session=False)
    BoardDigestItem.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    UserEmailLog.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    UserRecommendationHidden.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    UserRideInvite.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    UserFriend.query.filter(
        or_(UserFriend.requester_id == user_id, UserFriend.addressee_id == user_id)
    ).delete(synchronize_session=False)
    UserBike.query.filter_by(user_id=user_id).delete(synchronize_session=False)

    db.session.delete(user)
    _audit(
        'delete_user',
        details=(
            f'user_id={user_id}; email={email}; username={username}; '
            f'detached_owned_clubs={owned_club_count}; deleted_owned_rides={owned_ride_count}'
        ),
    )
    return f'Permanently deleted user {username}. Detached {owned_club_count} owned club(s).'


def _add_months(start_date, months):
    month = start_date.month - 1 + max(1, int(months or 12))
    year = start_date.year + month // 12
    month = month % 12 + 1
    last_day = [
        31,
        29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
        31, 30, 31, 30, 31, 31, 30, 31, 30, 31,
    ][month - 1]
    return date(year, month, min(start_date.day, last_day))


def _default_dues_expiration(club):
    return default_dues_expiration(club)


def _require_fresh_auth():
    if login_fresh():
        return None
    flash('Please sign in again to continue.', 'info')
    return redirect(url_for('auth.login', next=request.full_path.rstrip('?')))


def club_admin_required(f):
    """Decorator: user must be club admin (or global superadmin) for the club in the URL."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(403)
        fresh_response = _require_fresh_auth()
        if fresh_response:
            return fresh_response
        slug = kwargs.get('slug')
        if slug:
            club = _get_club_or_404(slug)
            if not current_user.is_club_admin(club):
                abort(403)
        elif not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return login_required(decorated)


def club_ride_admin_required(f):
    """Decorator: user must be able to manage rides (full admin OR ride_manager)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(403)
        fresh_response = _require_fresh_auth()
        if fresh_response:
            return fresh_response
        slug = kwargs.get('slug')
        if slug:
            club = _get_club_or_404(slug)
            if not current_user.can_manage_rides(club):
                abort(403)
        elif not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return login_required(decorated)


def superadmin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        fresh_response = _require_fresh_auth()
        if fresh_response:
            return fresh_response
        return f(*args, **kwargs)
    return login_required(decorated)


def club_content_required(f):
    """Decorator: user must be able to manage content (admin OR content_editor)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(403)
        fresh_response = _require_fresh_auth()
        if fresh_response:
            return fresh_response
        slug = kwargs.get('slug')
        if slug:
            club = _get_club_or_404(slug)
            if not current_user.can_manage_content(club):
                abort(403)
        elif not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return login_required(decorated)


def club_member_view_required(f):
    """Decorator: user must be able to view member data (admin OR treasurer)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(403)
        fresh_response = _require_fresh_auth()
        if fresh_response:
            return fresh_response
        slug = kwargs.get('slug')
        if slug:
            club = _get_club_or_404(slug)
            if not current_user.can_view_members(club):
                abort(403)
        elif not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return login_required(decorated)


# ── Global superadmin ─────────────────────────────────────────────────────────

@admin_bp.route('/', methods=['GET', 'POST'])
@superadmin_required
def dashboard():
    if request.method == 'POST' and request.form.get('action') == 'email_settings':
        try:
            cap = max(0, min(500, int(request.form.get('email_daily_cap', 15))))
        except (TypeError, ValueError):
            flash('Enter a valid daily email cap.', 'danger')
            return redirect(url_for('admin.dashboard'))
        set_site_setting('email_daily_cap', cap)
        _audit('update_email_settings', details=f'email_daily_cap={cap}')
        db.session.commit()
        flash('Email notification settings updated.', 'success')
        return redirect(url_for('admin.dashboard'))

    started_at = time.perf_counter()
    today = date.today()
    report = platform_report(started_at)
    stats = report['stats']

    # Popular clubs by active member count
    popular = (db.session.query(Club, func.count(ClubMembership.id).label('mc'))
               .outerjoin(ClubMembership,
                          (Club.id == ClubMembership.club_id) & (ClubMembership.status == 'active'))
               .group_by(Club.id)
               .order_by(func.count(ClubMembership.id).desc())
               .limit(5).all())

    # Enrich clubs with upcoming ride count
    clubs_raw = Club.query.order_by(Club.name.asc()).all()
    clubs = []
    for club in clubs_raw:
        upcoming = Ride.query.filter_by(club_id=club.id, is_cancelled=False).filter(Ride.date >= today).count()
        clubs.append({'club': club, 'upcoming': upcoming})

    super_admins = User.query.filter_by(is_admin=True).order_by(User.username.asc()).all()
    ungeocodeable_count = Club.query.filter(
        Club.zip_code.isnot(None), Club.lat.is_(None)
    ).count()
    recent_audit = (AdminAuditLog.query
                    .order_by(AdminAuditLog.created_at.desc())
                    .limit(8).all())
    unread_feedback_count = SiteFeedback.query.filter_by(is_read=False).count()
    unread_messages_count = AdminMessage.query.filter_by(
        is_from_superadmin=False, is_read=False
    ).count()

    # ── Stripe monitoring ──────────────────────────────────────────────────────
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    two_hours_ago = datetime.now(timezone.utc) - timedelta(hours=2)

    stripe_stats = {
        'connected_clubs': Club.query.filter(
            Club.stripe_account_id.isnot(None),
            Club.stripe_account_connected_at.isnot(None),
        ).count(),
        'total_paid': ClubMembershipPayment.query.filter_by(status='paid').count(),
        'total_amount_cents': db.session.query(
            func.sum(ClubMembershipPayment.amount_cents)
        ).filter_by(status='paid').scalar() or 0,
        'paid_30d': ClubMembershipPayment.query.filter(
            ClubMembershipPayment.status == 'paid',
            ClubMembershipPayment.paid_at >= thirty_days_ago,
        ).count(),
        'amount_30d_cents': db.session.query(
            func.sum(ClubMembershipPayment.amount_cents)
        ).filter(
            ClubMembershipPayment.status == 'paid',
            ClubMembershipPayment.paid_at >= thirty_days_ago,
        ).scalar() or 0,
        'stuck_pending': ClubMembershipPayment.query.filter(
            ClubMembershipPayment.status == 'pending',
            ClubMembershipPayment.created_at < two_hours_ago,
        ).count(),
    }
    stripe_recent = (
        ClubMembershipPayment.query
        .filter_by(status='paid')
        .order_by(ClubMembershipPayment.paid_at.desc())
        .limit(10).all()
    )
    stripe_errors = (
        AppErrorLog.query
        .filter(AppErrorLog.error_type == 'stripe_payment_failed')
        .order_by(AppErrorLog.created_at.desc())
        .limit(10).all()
    )

    return render_template('admin/dashboard.html', stats=stats, clubs=clubs,
                           super_admins=super_admins, popular=popular,
                           ungeocodeable_count=ungeocodeable_count,
                           report=report, recent_audit=recent_audit,
                           unread_feedback_count=unread_feedback_count,
                           unread_messages_count=unread_messages_count,
                           error_report=report.get('errors', {}),
                           stripe_stats=stripe_stats,
                           stripe_recent=stripe_recent,
                           stripe_errors=stripe_errors)


@admin_bp.route('/clubs/<int:club_id>/feature', methods=['POST'])
@superadmin_required
def club_feature(club_id):
    club = Club.query.get_or_404(club_id)
    club.is_featured = bool(request.form.get('is_featured'))
    rank_raw = (request.form.get('featured_rank') or '').strip()
    if rank_raw:
        try:
            club.featured_rank = max(1, min(999, int(rank_raw)))
        except ValueError:
            flash('Featured rank must be a number.', 'danger')
            return redirect(url_for('admin.dashboard') + '#clubs')
    else:
        club.featured_rank = None
    _audit('update_featured_club', details=f'club={club.slug}; featured={club.is_featured}; rank={club.featured_rank}')
    db.session.commit()
    flash(f'Featured club settings updated for {club.name}.', 'success')
    return redirect(url_for('admin.dashboard') + '#clubs')


# ── Error log ─────────────────────────────────────────────────────────────────

@admin_bp.route('/errors/')
@superadmin_required
def error_log():
    from ..models import AppErrorLog
    from datetime import datetime, timedelta, timezone
    status = request.args.get('status', 'all')
    page = request.args.get('page', 1, type=int)
    q = AppErrorLog.query.order_by(AppErrorLog.created_at.desc())
    if status == '5xx':
        q = q.filter(AppErrorLog.status_code >= 500)
    elif status == '4xx':
        q = q.filter(AppErrorLog.status_code >= 400, AppErrorLog.status_code < 500)
    pagination = q.paginate(page=page, per_page=50, error_out=False)
    return render_template('admin/error_log.html', pagination=pagination, status=status)


@admin_bp.route('/errors/<int:error_id>')
@superadmin_required
def error_detail(error_id):
    from ..models import AppErrorLog
    entry = db.session.get(AppErrorLog, error_id)
    if entry is None:
        abort(404)
    return render_template('admin/error_detail.html', entry=entry)


# ── User management ───────────────────────────────────────────────────────────

@admin_bp.route('/users/')
@superadmin_required
def users():
    q           = request.args.get('q', '').strip()
    page        = request.args.get('page', 1, type=int)
    filter_type = request.args.get('filter', 'all')

    query = User.query
    if q:
        query = query.filter(
            or_(User.username.ilike(f'%{q}%'), User.email.ilike(f'%{q}%'))
        )
    if filter_type == 'admins':
        query = query.filter_by(is_admin=True)
    elif filter_type == 'inactive':
        query = query.filter_by(is_active=False)

    pagination = (query.order_by(User.created_at.desc())
                  .paginate(page=page, per_page=25, error_out=False))
    return render_template('admin/users.html', pagination=pagination,
                           q=q, filter_type=filter_type)


@admin_bp.route('/user-rides/')
@superadmin_required
def user_rides():
    q = request.args.get('q', '').strip()
    privacy = request.args.get('privacy', 'all')
    page = request.args.get('page', 1, type=int)

    query = Ride.query.filter(Ride.owner_id.isnot(None)).join(User, Ride.owner_id == User.id)
    if q:
        query = query.filter(or_(
            Ride.title.ilike(f'%{q}%'),
            User.username.ilike(f'%{q}%'),
            User.email.ilike(f'%{q}%'),
        ))
    if privacy == 'private':
        query = query.filter(Ride.is_private == True)
    elif privacy == 'public':
        query = query.filter(Ride.is_private == False)

    pagination = (query.order_by(Ride.date.desc(), Ride.time.desc())
                  .paginate(page=page, per_page=25, error_out=False))
    return render_template('admin/user_rides.html', pagination=pagination,
                           q=q, privacy=privacy)


@admin_bp.route('/feedback/')
@superadmin_required
def feedback():
    filter_type = request.args.get('filter', 'unread')
    query = SiteFeedback.query
    if filter_type != 'all':
        query = query.filter_by(is_read=False)
    items = query.order_by(SiteFeedback.created_at.desc()).all()
    unread_count = SiteFeedback.query.filter_by(is_read=False).count()
    return render_template('admin/feedback.html', items=items,
                           filter_type=filter_type, unread_count=unread_count)


@admin_bp.route('/feedback/<int:feedback_id>/mark-read', methods=['POST'])
@superadmin_required
def feedback_mark_read(feedback_id):
    item = SiteFeedback.query.get_or_404(feedback_id)
    if not item.is_read:
        item.is_read = True
        item.read_at = datetime.now(timezone.utc)
        item.read_by_id = current_user.id
        _audit('mark_feedback_read', details=f'feedback_id={item.id}')
        db.session.commit()
        flash('Feedback marked as read.', 'success')
    return redirect(url_for('admin.feedback', filter=request.args.get('filter', 'unread')))


# ── Platform posts ────────────────────────────────────────────────────────────

@admin_bp.route('/platform-posts/')
@superadmin_required
def platform_posts():
    posts = (PlatformPost.query
             .order_by(PlatformPost.published_at.desc(), PlatformPost.id.desc())
             .all())
    return render_template('admin/platform_posts.html', posts=posts)


@admin_bp.route('/platform-posts/new', methods=['GET', 'POST'])
@superadmin_required
def platform_post_new():
    form = PlatformPostForm()
    if form.validate_on_submit():
        post = PlatformPost(
            author_id=current_user.id,
            title=form.title.data.strip(),
            summary=(form.summary.data or '').strip() or None,
            body=form.body.data.strip(),
            is_published=form.is_published.data,
        )
        db.session.add(post)
        _audit('create_platform_post', details=f'title={post.title}; published={post.is_published}')
        db.session.commit()
        flash('Homepage post saved.', 'success')
        return redirect(url_for('admin.platform_posts'))
    return render_template('admin/platform_post_form.html', form=form, post=None, title='New Homepage Post')


@admin_bp.route('/platform-posts/<int:post_id>/edit', methods=['GET', 'POST'])
@superadmin_required
def platform_post_edit(post_id):
    post = PlatformPost.query.get_or_404(post_id)
    form = PlatformPostForm(obj=post)
    if form.validate_on_submit():
        post.title = form.title.data.strip()
        post.summary = (form.summary.data or '').strip() or None
        post.body = form.body.data.strip()
        post.is_published = form.is_published.data
        post.updated_at = datetime.now(timezone.utc)
        _audit('update_platform_post', details=f'post_id={post.id}; title={post.title}; published={post.is_published}')
        db.session.commit()
        flash('Homepage post updated.', 'success')
        return redirect(url_for('admin.platform_posts'))
    return render_template('admin/platform_post_form.html', form=form, post=post, title='Edit Homepage Post')


@admin_bp.route('/platform-posts/<int:post_id>/delete', methods=['POST'])
@superadmin_required
def platform_post_delete(post_id):
    post = PlatformPost.query.get_or_404(post_id)
    title = post.title
    db.session.delete(post)
    _audit('delete_platform_post', details=f'post_id={post_id}; title={title}')
    db.session.commit()
    flash('Homepage post deleted.', 'info')
    return redirect(url_for('admin.platform_posts'))


@admin_bp.route('/users/<int:user_id>')
@superadmin_required
def user_detail(user_id):
    from ..models import DuesEditLog
    profile_user   = User.query.get_or_404(user_id)
    recent_signups = (RideSignup.query
                      .filter_by(user_id=user_id)
                      .order_by(RideSignup.id.desc())
                      .limit(10).all())
    memberships = (ClubMembership.query
                   .filter_by(user_id=user_id)
                   .join(Club, ClubMembership.club_id == Club.id)
                   .order_by(Club.name.asc())
                   .all())
    edit_logs = {}
    if memberships:
        m_ids = [m.id for m in memberships]
        logs = (DuesEditLog.query
                .filter(DuesEditLog.membership_id.in_(m_ids))
                .order_by(DuesEditLog.edited_at.desc())
                .all())
        for log in logs:
            edit_logs.setdefault(log.membership_id, []).append(log)
    from datetime import date as _date
    return render_template('admin/user_detail.html',
                           profile_user=profile_user,
                           recent_signups=recent_signups,
                           can_delete_test_user=_is_deletable_test_user(profile_user),
                           memberships=memberships,
                           edit_logs=edit_logs,
                           today=_date.today())


@admin_bp.route('/users/<int:user_id>/memberships/<int:membership_id>/edit-dues', methods=['POST'])
@superadmin_required
def edit_member_dues(user_id, membership_id):
    from ..models import DuesEditLog
    from datetime import date as _date
    membership = ClubMembership.query.get_or_404(membership_id)
    if membership.user_id != user_id:
        abort(404)

    old_paid_until = membership.dues_paid_until
    old_status = membership.status

    raw_date = request.form.get('dues_paid_until', '').strip()
    new_paid_until = None
    if raw_date:
        try:
            new_paid_until = _date.fromisoformat(raw_date)
        except ValueError:
            flash('Invalid date format.', 'danger')
            return redirect(url_for('admin.user_detail', user_id=user_id))

    new_status = request.form.get('status', '').strip()
    if new_status not in ('active', 'pending', 'pending_payment'):
        new_status = old_status

    note = request.form.get('note', '').strip() or None

    membership.dues_paid_until = new_paid_until
    membership.status = new_status

    log = DuesEditLog(
        membership_id=membership.id,
        edited_by_id=current_user.id,
        old_dues_paid_until=old_paid_until,
        new_dues_paid_until=new_paid_until,
        old_status=old_status,
        new_status=new_status,
        note=note,
    )
    db.session.add(log)
    _audit('edit_member_dues',
           target_user=membership.user,
           details=f'club_id={membership.club_id}; '
                   f'paid_until: {old_paid_until} → {new_paid_until}; '
                   f'status: {old_status} → {new_status}')
    db.session.commit()
    flash(f'Dues updated for {membership.user.username} in {membership.club.name}.', 'success')
    return redirect(url_for('admin.user_detail', user_id=user_id))


@admin_bp.route('/users/<int:user_id>/reset-password', methods=['POST'])
@superadmin_required
def reset_user_password(user_id):
    user   = User.query.get_or_404(user_id)
    alpha  = string.ascii_letters + string.digits
    tmp_pw = ''.join(secrets.choice(alpha) for _ in range(12))
    user.password_hash = bcrypt.generate_password_hash(tmp_pw).decode('utf-8')
    user.revoke_sessions()
    _audit('reset_password', target_user=user)
    db.session.commit()
    flash(Markup(
        f'Password reset for <strong>{html_escape(user.username)}</strong>. '
        f'Temporary password: <code class="user-select-all fw-bold">{tmp_pw}</code> '
        f'— share this with the user immediately.'
    ), 'warning')
    return redirect(url_for('admin.user_detail', user_id=user_id))


@admin_bp.route('/users/<int:user_id>/toggle-admin', methods=['POST'])
@superadmin_required
def toggle_admin(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('You cannot change your own super admin status.', 'danger')
        return redirect(url_for('admin.user_detail', user_id=user_id))
    if user.is_admin and user.email.lower() in configured_superadmin_emails():
        flash('This account is configured as a bootstrap superadmin and cannot be revoked in the app.', 'danger')
        return redirect(url_for('admin.user_detail', user_id=user_id))
    if user.is_admin and active_superadmin_count(exclude_user_id=user.id) == 0:
        flash('You must keep at least one active super admin account.', 'danger')
        return redirect(url_for('admin.user_detail', user_id=user_id))
    user.is_admin = not user.is_admin
    _audit('grant_superadmin' if user.is_admin else 'revoke_superadmin', target_user=user)
    db.session.commit()
    action = 'granted' if user.is_admin else 'revoked'
    flash(f'Super admin access {action} for {user.username}.', 'success')
    return redirect(url_for('admin.user_detail', user_id=user_id))


@admin_bp.route('/users/<int:user_id>/toggle-active', methods=['POST'])
@superadmin_required
def toggle_active(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('You cannot deactivate your own account.', 'danger')
        return redirect(url_for('admin.user_detail', user_id=user_id))
    if user.is_active and user.is_admin and active_superadmin_count(exclude_user_id=user.id) == 0:
        flash('You must keep at least one active super admin account.', 'danger')
        return redirect(url_for('admin.user_detail', user_id=user_id))
    user.is_active = not user.is_active
    user.revoke_sessions()
    _audit('reactivate_account' if user.is_active else 'deactivate_account', target_user=user)
    db.session.commit()
    action = 'reactivated' if user.is_active else 'deactivated'
    flash(f'Account {action} for {user.username}.', 'success')
    return redirect(url_for('admin.user_detail', user_id=user_id))


@admin_bp.route('/users/<int:user_id>/delete-test-user', methods=['POST'])
@superadmin_required
def delete_test_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('You cannot delete your own account.', 'danger')
        return redirect(url_for('admin.user_detail', user_id=user_id))
    if not _is_deletable_test_user(user):
        flash('Only generated test users can be permanently deleted from this action.', 'danger')
        return redirect(url_for('admin.user_detail', user_id=user_id))

    confirmation = (request.form.get('confirmation') or '').strip()
    expected = f'DELETE TEST USER {user.email}'
    if confirmation != expected:
        flash(f'Type "{expected}" to permanently delete this generated test user.', 'danger')
        return redirect(url_for('admin.user_detail', user_id=user_id))

    ok, message = _delete_test_user_records(user)
    if not ok:
        flash(message, 'danger')
        return redirect(url_for('admin.user_detail', user_id=user_id))
    db.session.commit()
    flash(message, 'success')
    return redirect(url_for('admin.users', filter='inactive'))


@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@superadmin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('You cannot permanently delete your own account.', 'danger')
        return redirect(url_for('admin.user_detail', user_id=user_id))
    if user.is_admin and user.email.lower() in configured_superadmin_emails():
        flash('This account is configured as a bootstrap superadmin and cannot be deleted in the app.', 'danger')
        return redirect(url_for('admin.user_detail', user_id=user_id))
    if user.is_admin and active_superadmin_count(exclude_user_id=user.id) == 0:
        flash('You must keep at least one active super admin account.', 'danger')
        return redirect(url_for('admin.user_detail', user_id=user_id))

    confirmation = (request.form.get('confirmation') or '').strip()
    expected = f'DELETE USER {user.email}'
    if confirmation != expected:
        flash(f'Type "{expected}" to permanently delete this user.', 'danger')
        return redirect(url_for('admin.user_detail', user_id=user_id))

    message = _delete_user_records(user)
    db.session.commit()
    flash(message, 'success')
    return redirect(url_for('admin.users'))


@admin_bp.route('/users/<int:user_id>/revoke-sessions', methods=['POST'])
@superadmin_required
def revoke_user_sessions(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('You cannot revoke your own active session from this panel.', 'danger')
        return redirect(url_for('admin.user_detail', user_id=user_id))
    user.revoke_sessions()
    _audit('revoke_sessions', target_user=user)
    db.session.commit()
    flash(f'All existing sessions revoked for {user.username}.', 'success')
    return redirect(url_for('admin.user_detail', user_id=user_id))


@admin_bp.route('/geocode-clubs', methods=['POST'])
@superadmin_required
def geocode_clubs():
    """Bulk geocode all clubs that have a zip_code but no lat/lng."""
    clubs = Club.query.filter(
        Club.zip_code.isnot(None),
        Club.lat.is_(None),
    ).all()
    succeeded, failed = 0, 0
    for club in clubs:
        coords = geocode_zip(club.zip_code)
        if coords:
            club.lat, club.lng = coords
            succeeded += 1
        else:
            failed += 1
    _audit('bulk_geocode_clubs', details=f'succeeded={succeeded}; failed={failed}')
    db.session.commit()
    msg = f'Geocoded {succeeded} club{"s" if succeeded != 1 else ""}.'
    if failed:
        msg += f' {failed} could not be resolved.'
    flash(msg, 'success' if not failed else 'warning')
    return redirect(url_for('admin.dashboard'))


@admin_bp.route('/clubs/new', methods=['GET', 'POST'])
@superadmin_required
def club_new():
    form = ClubForm()
    if form.validate_on_submit():
        from app.routes.clubs import _RESERVED_SLUGS
        slug = form.slug.data.strip().lower()
        if Club.query.filter_by(slug=slug).first() or slug in _RESERVED_SLUGS:
            flash('That slug is already taken or reserved.', 'danger')
            return render_template('admin/club_form.html', form=form, title='New Club', club=None)

        club = Club(
            slug=slug,
            name=form.name.data,
            description=form.description.data or None,
            city=form.city.data or None,
            state=form.state.data or None,
            zip_code=form.zip_code.data or None,
            address=form.address.data or None,
            contact_email=form.contact_email.data or None,
            logo_url=form.logo_url.data or None,
            is_active=form.is_active.data,
        )
        if club.zip_code:
            coords = geocode_zip(club.zip_code)
            if coords:
                club.lat, club.lng = coords
        db.session.add(club)
        db.session.commit()
        flash(f'Club "{club.name}" created.', 'success')
        return redirect(url_for('admin.club_dashboard', slug=club.slug))

    return render_template('admin/club_form.html', form=form, title='New Club', club=None)


@admin_bp.route('/clubs/<slug>/superadmin')
@superadmin_required
def club_superadmin(slug):
    club = Club.query.filter_by(slug=slug).first_or_404()
    stats = {
        'members': ClubMembership.query.filter_by(club_id=club.id).count(),
        'rides': Ride.query.filter_by(club_id=club.id).count(),
        'signups': (RideSignup.query
                    .join(Ride, RideSignup.ride_id == Ride.id)
                    .filter(Ride.club_id == club.id).count()),
        'posts': ClubPost.query.filter_by(club_id=club.id).count(),
    }
    return render_template('admin/club_superadmin.html', club=club, stats=stats,
                           owner=club.effective_owner)


@admin_bp.route('/clubs/<slug>/superadmin/transfer-owner', methods=['POST'])
@superadmin_required
def club_superadmin_transfer_owner(slug):
    club = Club.query.filter_by(slug=slug).first_or_404()
    email = (request.form.get('email') or '').strip()
    confirm_email = (request.form.get('confirm_email') or '').strip()
    if email.lower() != confirm_email.lower():
        flash('Email confirmation must match the new owner email.', 'danger')
        return redirect(url_for('admin.club_superadmin', slug=club.slug))

    user = _find_user_by_email(email)
    if not user:
        flash(f'No active Paceline user was found with email "{email}".', 'danger')
        return redirect(url_for('admin.club_superadmin', slug=club.slug))
    if not user.is_active:
        flash('That account is disabled and cannot own a club.', 'danger')
        return redirect(url_for('admin.club_superadmin', slug=club.slug))

    previous_owner_id = club.owner_id
    _ensure_owner_membership_and_admin(club, user)
    _audit('manual_transfer_club_owner', target_user=user,
           details=f'club_id={club.id}; from_user_id={previous_owner_id}; to_user_id={user.id}')
    db.session.commit()
    flash(f'{club.name} ownership was transferred to {user.username}.', 'success')
    return redirect(url_for('admin.club_superadmin', slug=club.slug))


@admin_bp.route('/clubs/<slug>/toggle-private', methods=['POST'])
@superadmin_required
def club_toggle_private(slug):
    club = Club.query.filter_by(slug=slug).first_or_404()
    club.is_private = not club.is_private
    _audit('toggle_club_private', details=f'club_id={club.id}; private={club.is_private}')
    db.session.commit()
    flash(f'{club.name} is now {"private" if club.is_private else "public"}.', 'success')
    return redirect(url_for('admin.club_superadmin', slug=club.slug))


@admin_bp.route('/clubs/<slug>/toggle-verified', methods=['POST'])
@superadmin_required
def club_toggle_verified(slug):
    club = Club.query.filter_by(slug=slug).first_or_404()
    club.is_verified = not club.is_verified
    _audit('toggle_club_verified', details=f'club_id={club.id}; verified={club.is_verified}')
    db.session.commit()
    status = 'verified' if club.is_verified else 'unverified'
    flash(f'{club.name} is now {status}.', 'success')
    return redirect(url_for('admin.club_superadmin', slug=club.slug))


@admin_bp.route('/clubs/<slug>/delete', methods=['POST'])
@superadmin_required
def club_delete(slug):
    club = Club.query.filter_by(slug=slug).first_or_404()
    confirmation = (request.form.get('confirmation') or '').strip()
    expected = f'DELETE {club.slug}'
    if confirmation != expected:
        flash(f'Type "{expected}" to permanently delete this club.', 'danger')
        return redirect(url_for('admin.club_superadmin', slug=club.slug))

    name = club.name
    club_id = club.id
    db.session.delete(club)
    _audit('delete_club', details=f'club_id={club_id}; slug={slug}; name={name}')
    db.session.commit()
    flash(f'Club "{name}" deleted.', 'success')
    return redirect(url_for('admin.dashboard'))


# ── Club admin ────────────────────────────────────────────────────────────────

@admin_bp.route('/clubs/<slug>/')
@club_ride_admin_required
def club_dashboard(slug):
    club = _get_club_or_404(slug)
    today = date.today()
    upcoming = (Ride.query.filter_by(club_id=club.id)
                .filter(Ride.date >= today)
                .order_by(Ride.date.asc()).limit(5).all())
    stats = {
        'members':        ClubMembership.query.filter_by(club_id=club.id, status='active').count(),
        'pending':        ClubMembership.query.filter_by(club_id=club.id, status='pending').count(),
        'upcoming_rides': Ride.query.filter_by(club_id=club.id).filter(Ride.date >= today).count(),
        'total_rides':    Ride.query.filter_by(club_id=club.id).count(),
        'total_signups':  (RideSignup.query
                           .join(Ride, RideSignup.ride_id == Ride.id)
                           .filter(Ride.club_id == club.id).count()),
    }
    is_full_admin = current_user.is_club_admin(club)
    unread_messages = AdminMessage.query.filter_by(
        club_id=club.id, is_from_superadmin=True, is_read=False
    ).count()
    activity_stats = _club_admin_activity_stats(club, today=today)
    leader_count = ClubLeader.query.filter_by(club_id=club.id).count()
    setup_items = [
        {
            'label': 'Add club branding',
            'detail': 'Logo, banner, description, and location help riders recognize the club.',
            'complete': bool((club.logo_key or club.logo_url) and club.description),
            'url': url_for('admin.club_settings', slug=club.slug),
        },
        {
            'label': 'Create the first ride',
            'detail': 'A visible upcoming ride makes the club page immediately useful.',
            'complete': stats['total_rides'] > 0,
            'url': url_for('admin.ride_new', slug=club.slug),
        },
        {
            'label': 'Invite or import members',
            'detail': 'Seed the roster so riders know the club is active.',
            'complete': stats['members'] > 1,
            'url': url_for('admin.club_invites', slug=club.slug),
        },
        {
            'label': 'Add ride leaders',
            'detail': 'Leaders make ride pages feel trustworthy and easier to contact.',
            'complete': leader_count > 0,
            'url': url_for('admin.club_leaders', slug=club.slug),
        },
        {
            'label': 'Review payments and shop',
            'detail': 'Connect Stripe only if this club will collect dues or sell items.',
            'complete': bool(club.stripe_connect_ready or not club.membership_dues_required),
            'url': url_for('admin.club_settings', slug=club.slug) + '#membership-section',
        },
        {
            'label': 'Share or embed rides',
            'detail': 'Use the club page or embedded ride list on an existing website.',
            'complete': stats['total_rides'] > 0,
            'url': url_for('clubs.embed', slug=club.slug),
        },
    ]
    return render_template('admin/club_dashboard.html', club=club,
                           upcoming=upcoming, stats=stats,
                           is_full_admin=is_full_admin,
                           unread_messages=unread_messages,
                           setup_items=setup_items,
                           activity_stats=activity_stats)


@admin_bp.route('/clubs/<slug>/settings', methods=['GET', 'POST'])
@club_admin_required
def club_settings(slug):
    club = _get_club_or_404(slug)
    form = ClubSettingsForm(obj=club)
    if request.method == 'GET' and club.membership_dues_amount_cents:
        form.membership_dues_amount.data = club.membership_dues_amount_cents / 100
    if request.method == 'GET' and not club.stripe_connect_ready:
        form.membership_dues_required.data = False
    # Passive Stripe status sync: if the account exists but connected_at was never
    # set (e.g. due to a timing race on the return URL), re-check on each GET.
    if request.method == 'GET' and club.stripe_account_id and not club.stripe_account_connected_at:
        try:
            from ..stripe_connect import retrieve_connected_account
            account = retrieve_connected_account(club.stripe_account_id)
            if account.get('charges_enabled'):
                club.stripe_account_connected_at = datetime.now(timezone.utc)
                db.session.commit()
        except Exception:
            pass
    if form.validate_on_submit():
        club.name         = form.name.data
        club.tagline      = form.tagline.data or None
        club.description  = form.description.data or None
        club.city         = form.city.data or None
        club.state        = form.state.data or None
        club.address      = form.address.data or None
        club.contact_email = form.contact_email.data or None
        if form.logo_file.data and form.logo_file.data.filename:
            _delete_club_logo(club.logo_key)
            club.logo_key = _save_club_logo(form.logo_file.data, club.id)
            club.logo_url = None
        elif form.logo_url.data:
            _delete_club_logo(club.logo_key)
            club.logo_key = None
            club.logo_url = form.logo_url.data or None
        # if neither provided, keep existing logo_key/logo_url unchanged

        new_zip = (form.zip_code.data or '').strip()
        if new_zip != (club.zip_code or ''):
            club.zip_code = new_zip or None
            club.lat = None
            club.lng = None
            if new_zip:
                coords = geocode_zip(new_zip)
                if coords:
                    club.lat, club.lng = coords
                else:
                    flash('Zip code saved but could not be geocoded.', 'warning')

        club.theme_primary = (form.theme_primary.data or '').strip().lower() or None
        club.theme_accent  = (form.theme_accent.data or '').strip().lower() or None
        club.banner_url    = form.banner_url.data or None
        raw_homepage_layout = form.homepage_layout.data or 'magazine'
        club.homepage_layout = (
            raw_homepage_layout
            if raw_homepage_layout in ('magazine', 'dashboard', 'newspaper')
            else 'magazine'
        )

        raw_strava = (form.strava_club_id.data or '').strip()
        club.strava_club_id = int(raw_strava) if raw_strava.isdigit() else None

        club.auto_cancel_enabled = form.auto_cancel_enabled.data
        club.cancel_rain_prob    = form.cancel_rain_prob.data or 80
        club.cancel_wind_mph     = form.cancel_wind_mph.data or 35
        club.cancel_temp_min_f   = form.cancel_temp_min_f.data if form.cancel_temp_min_f.data is not None else 28
        club.cancel_temp_max_f   = form.cancel_temp_max_f.data if form.cancel_temp_max_f.data is not None else 100

        raw_mode = form.hosting_mode.data or 'full'
        club.hosting_mode       = raw_mode if raw_mode in ('full', 'rides_only') else 'full'
        club.is_hidden           = form.is_hidden.data
        club.is_private         = form.is_private.data
        club.require_membership = form.require_membership.data
        club.join_approval      = form.join_approval.data if form.join_approval.data in ('auto', 'manual') else 'auto'
        wants_paid_dues = bool(form.membership_dues_required.data)
        if wants_paid_dues and not club.stripe_connect_ready:
            club.membership_dues_required = False
            club.membership_dues_mode = 'manual'
            flash('Connect Stripe before enabling paid dues. Paid dues are only available through Stripe Connect.', 'warning')
        else:
            club.membership_dues_required = wants_paid_dues
            club.membership_dues_mode = 'stripe_connect' if wants_paid_dues else 'manual'
        if form.membership_dues_amount.data is not None:
            club.membership_dues_amount_cents = int(round(float(form.membership_dues_amount.data) * 100))
        else:
            club.membership_dues_amount_cents = None
        club.membership_dues_currency = 'usd'
        club.membership_duration_months = form.membership_duration_months.data or 12

        club.facebook_url      = form.facebook_url.data or None
        club.instagram_url     = form.instagram_url.data or None
        club.twitter_url       = form.twitter_url.data or None
        club.newsletter_url    = form.newsletter_url.data or None
        club.whatsapp_url      = form.whatsapp_url.data or None
        club.bylaws_url        = form.bylaws_url.data or None
        club.safety_guidelines = form.safety_guidelines.data or None

        db.session.commit()
        flash('Club settings updated.', 'success')
        return redirect(url_for('admin.club_settings', slug=slug))

    if request.method == 'POST':
        for field_name, errors in form.errors.items():
            for error in errors:
                current_app.logger.error('[club_settings] slug=%s field=%s error=%s', slug, field_name, error)
        if form.errors:
            flash('Settings not saved. Check the highlighted fields below.', 'danger')
    return render_template('admin/club_settings.html', form=form, club=club)


@admin_bp.route('/clubs/<slug>/members/')
@club_member_view_required
def club_members(slug):
    """Full member roster with dues status — accessible to club admins."""
    from datetime import date as _date
    club = _get_club_or_404(slug)
    q = request.args.get('q', '').strip()
    status_filter = request.args.get('status', 'all')

    query = (ClubMembership.query.filter_by(club_id=club.id)
             .join(ClubMembership.user))
    if q:
        query = query.filter(
            or_(User.username.ilike(f'%{q}%'), User.email.ilike(f'%{q}%'))
        )
    if status_filter == 'active':
        query = query.filter(ClubMembership.status == 'active')
    elif status_filter == 'pending':
        query = query.filter(ClubMembership.status == 'pending')
    elif status_filter == 'pending_payment':
        query = query.filter(ClubMembership.status == 'pending_payment')
    elif status_filter == 'expired':
        query = query.filter(
            ClubMembership.status == 'active',
            ClubMembership.dues_paid_until < _date.today(),
        )

    memberships = query.order_by(User.username.asc()).all()
    today = _date.today()

    # For clubs with dues, fetch the most recent paid payment per membership.
    payments_by_membership_id = {}
    if club.membership_dues_required and memberships:
        m_ids = [m.id for m in memberships]
        paid_payments = (
            ClubMembershipPayment.query
            .filter(
                ClubMembershipPayment.membership_id.in_(m_ids),
                ClubMembershipPayment.status == 'paid',
            )
            .order_by(ClubMembershipPayment.paid_at.desc())
            .all()
        )
        for p in paid_payments:
            if p.membership_id not in payments_by_membership_id:
                payments_by_membership_id[p.membership_id] = p

    return render_template('admin/club_members.html', club=club,
                           memberships=memberships, today=today,
                           payments_by_membership_id=payments_by_membership_id,
                           q=q, status_filter=status_filter)


@admin_bp.route('/clubs/<slug>/members/export')
@club_member_view_required
def club_members_export(slug):
    """Download active member list as CSV."""
    import csv
    import io
    from flask import Response
    club = _get_club_or_404(slug)
    memberships = (ClubMembership.query.filter_by(club_id=club.id)
                   .join(ClubMembership.user).order_by(User.username).all())
    # Fetch most recent paid payment per membership for dues clubs
    dues_payments = {}
    if club.membership_dues_required:
        m_ids = [m.id for m in memberships]
        for p in (ClubMembershipPayment.query
                  .filter(ClubMembershipPayment.membership_id.in_(m_ids),
                          ClubMembershipPayment.status == 'paid')
                  .order_by(ClubMembershipPayment.paid_at.desc()).all()):
            dues_payments.setdefault(p.membership_id, p)

    output = io.StringIO()
    writer = csv.writer(output)
    if club.membership_dues_required:
        writer.writerow(['Username', 'Email', 'Status', 'Joined',
                         'Dues Paid', 'Transaction ID', 'Expires',
                         'Emergency Contact', 'Emergency Phone'])
    else:
        writer.writerow(['Username', 'Email', 'Status', 'Joined',
                         'Emergency Contact', 'Emergency Phone'])
    for m in memberships:
        p = dues_payments.get(m.id)
        if club.membership_dues_required:
            writer.writerow([
                m.user.username,
                m.user.email,
                m.status,
                m.joined_at.strftime('%Y-%m-%d') if m.joined_at else '',
                p.paid_at.strftime('%Y-%m-%d') if p and p.paid_at else
                    (m.dues_confirmed_at.strftime('%Y-%m-%d') if m.dues_confirmed_at else ''),
                p.provider_payment_intent_id or '' if p else '',
                m.dues_paid_until.strftime('%Y-%m-%d') if m.dues_paid_until else '',
                m.user.emergency_contact_name or '',
                m.user.emergency_contact_phone or '',
            ])
        else:
            writer.writerow([
                m.user.username,
                m.user.email,
                m.status,
                m.joined_at.strftime('%Y-%m-%d') if m.joined_at else '',
                m.user.emergency_contact_name or '',
                m.user.emergency_contact_phone or '',
            ])
    output.seek(0)
    filename = f'{club.slug}_members.csv'
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


@admin_bp.route('/clubs/<slug>/rides')
@club_ride_admin_required
def club_rides(slug):
    club = _get_club_or_404(slug)
    page = request.args.get('page', 1, type=int)
    rides_paginated = (Ride.query.filter_by(club_id=club.id)
                       .order_by(Ride.date.desc())
                       .paginate(page=page, per_page=50, error_out=False))
    from ..models import RidePoll
    polls = (RidePoll.query.filter_by(club_id=club.id)
             .order_by(RidePoll.ride_date.desc()).limit(50).all())
    return render_template('admin/club_rides.html', club=club, rides=rides_paginated, polls=polls)


@admin_bp.route('/clubs/<slug>/rides/<int:ride_id>/roster')
@club_ride_admin_required
def ride_roster(slug, ride_id):
    club = _get_club_or_404(slug)
    ride = Ride.query.filter_by(id=ride_id, club_id=club.id).first_or_404()
    active = [s for s in ride.signups if not s.is_waitlist]
    waitlist = [s for s in ride.signups if s.is_waitlist]
    return render_template('admin/ride_roster.html', club=club, ride=ride,
                           active=active, waitlist=waitlist, today=date.today())


@admin_bp.route('/clubs/<slug>/rides/<int:ride_id>/attendance', methods=['POST'])
@club_ride_admin_required
def ride_attendance(slug, ride_id):
    club = _get_club_or_404(slug)
    ride = Ride.query.filter_by(id=ride_id, club_id=club.id).first_or_404()
    if ride.date >= date.today():
        flash('Attendance can only be recorded after the ride has taken place.', 'warning')
        return redirect(url_for('admin.ride_roster', slug=slug, ride_id=ride_id))
    active = [s for s in ride.signups if not s.is_waitlist]
    attended_ids = set(request.form.getlist('attended', type=int))
    for signup in active:
        signup.attended = signup.id in attended_ids
    db.session.commit()
    flash('Attendance saved.', 'success')
    return redirect(url_for('admin.ride_roster', slug=slug, ride_id=ride_id))


def _resolve_leader(club):
    """Read leader_id from form; return (leader_id, ride_leader_text)."""
    lid = request.form.get('leader_id', type=int)
    if lid:
        member = ClubMembership.query.filter_by(user_id=lid, club_id=club.id, status='active').first()
        if member:
            return lid, member.user.username
    return None, request.form.get('ride_leader_text', '').strip() or None


@admin_bp.route('/clubs/<slug>/rides/new', methods=['GET', 'POST'])
@club_ride_admin_required
def ride_new(slug):
    club = _get_club_or_404(slug)
    form = RideForm()
    members = (ClubMembership.query.filter_by(club_id=club.id, status='active')
               .join(ClubMembership.user).order_by(User.username).all())
    if form.validate_on_submit() and validate_ride_paces(form):
        is_virtual = form.is_virtual.data
        if not is_virtual and not form.meeting_location.data:
            form.meeting_location.errors.append('Meeting location is required for in-person rides.')
            return render_template('admin/ride_form.html', form=form, club=club,
                                   members=members, title='New Ride')
        leader_id, ride_leader = _resolve_leader(club)
        pace_categories = selected_ride_paces(form)
        ride = Ride(
            club_id=club.id,
            title=form.title.data,
            date=form.date.data,
            time=form.time.data,
            meeting_location=form.meeting_location.data or None,
            distance_miles=form.distance_miles.data,
            elevation_feet=form.elevation_feet.data,
            pace_category=pace_categories[0],
            is_multi_pace=form.is_multi_pace.data,
            pace_categories=pace_categories if form.is_multi_pace.data else None,
            ride_type=form.ride_type.data,
            max_riders=form.max_riders.data or None,
            leader_id=leader_id,
            ride_leader=ride_leader,
            route_url=form.route_url.data or None,
            video_url=form.video_url.data or None,
            garmin_groupride_code=(form.garmin_groupride_code.data or '').strip() or None,
            description=form.description.data or None,
            is_newbie_friendly=form.is_newbie_friendly.data,
            is_cancelled=form.is_cancelled.data,
            is_recurring=form.is_recurring.data,
            is_virtual=is_virtual,
            virtual_platform=form.virtual_platform.data or None,
            virtual_platform_url=form.virtual_platform_url.data or None,
            created_by=current_user.id,
        )
        db.session.add(ride)
        db.session.commit()
        if ride.is_recurring:
            count = len(generate_instances(ride))
            flash(f'Ride created with {count} recurring instances.', 'success')
        else:
            flash('Ride created.', 'success')
            send_new_ride_notification(ride)
        return redirect(url_for('admin.club_rides', slug=slug))
    return render_template('admin/ride_form.html', form=form, club=club,
                           members=members, title='New Ride')


@admin_bp.route('/clubs/<slug>/rides/<int:ride_id>/edit', methods=['GET', 'POST'])
@club_ride_admin_required
def ride_edit(slug, ride_id):
    club = _get_club_or_404(slug)
    ride = Ride.query.filter_by(id=ride_id, club_id=club.id).first_or_404()
    form = RideForm(obj=ride)
    members = (ClubMembership.query.filter_by(club_id=club.id, status='active')
               .join(ClubMembership.user).order_by(User.username).all())
    if request.method == 'GET':
        populate_ride_pace_fields(form, ride)
    if form.validate_on_submit() and validate_ride_paces(form):
        is_virtual = form.is_virtual.data
        if not is_virtual and not form.meeting_location.data:
            form.meeting_location.errors.append('Meeting location is required for in-person rides.')
            return render_template('admin/ride_form.html', form=form, club=club,
                                   members=members, title='Edit Ride', ride=ride)
        was_recurring  = ride.is_recurring
        was_cancelled  = ride.is_cancelled
        leader_id, ride_leader = _resolve_leader(club)
        pace_categories = selected_ride_paces(form)
        ride.title          = form.title.data
        ride.date           = form.date.data
        ride.time           = form.time.data
        ride.meeting_location = form.meeting_location.data or None
        ride.distance_miles = form.distance_miles.data
        ride.elevation_feet = form.elevation_feet.data
        ride.pace_category  = pace_categories[0]
        ride.is_multi_pace  = form.is_multi_pace.data
        ride.pace_categories = pace_categories if form.is_multi_pace.data else None
        ride.ride_type      = form.ride_type.data or None
        ride.max_riders     = form.max_riders.data or None
        ride.leader_id      = leader_id
        ride.ride_leader    = ride_leader
        ride.route_url      = form.route_url.data or None
        ride.video_url      = form.video_url.data or None
        ride.garmin_groupride_code = (form.garmin_groupride_code.data or '').strip() or None
        ride.description    = form.description.data or None
        ride.is_newbie_friendly = form.is_newbie_friendly.data
        ride.is_cancelled   = form.is_cancelled.data
        ride.is_recurring   = form.is_recurring.data
        ride.is_virtual     = is_virtual
        ride.virtual_platform = form.virtual_platform.data or None
        ride.virtual_platform_url = form.virtual_platform_url.data or None
        db.session.commit()
        if not was_cancelled and ride.is_cancelled:
            send_cancellation_emails(ride)
        # Regenerate instances if this is (or was) a recurring template
        if ride.is_recurring or was_recurring:
            delete_future_instances(ride)
            if ride.is_recurring:
                count = len(generate_instances(ride))
                flash(f'Ride updated — {count} upcoming instances regenerated.', 'success')
            else:
                flash('Ride updated — recurrence removed, future instances deleted.', 'success')
        else:
            flash('Ride updated.', 'success')
        return redirect(url_for('admin.club_rides', slug=slug))
    return render_template('admin/ride_form.html', form=form, club=club,
                           members=members, title='Edit Ride', ride=ride)


@admin_bp.route('/clubs/<slug>/rides/<int:ride_id>/delete', methods=['POST'])
@club_ride_admin_required
def ride_delete(slug, ride_id):
    club = _get_club_or_404(slug)
    ride = Ride.query.filter_by(id=ride_id, club_id=club.id).first_or_404()
    db.session.delete(ride)
    db.session.commit()
    flash('Ride deleted.', 'info')
    return redirect(url_for('admin.club_rides', slug=slug))


# ── Club team (admin role) management ─────────────────────────────────────────

@admin_bp.route('/clubs/<slug>/team')
@club_admin_required
def club_team(slug):
    club = _get_club_or_404(slug)
    admins = (ClubAdmin.query.filter_by(club_id=club.id)
              .join(User, ClubAdmin.user_id == User.id)
              .add_entity(User).all())
    members = (ClubMembership.query.filter_by(club_id=club.id, status='active')
               .join(User, ClubMembership.user_id == User.id)
               .add_entity(User).all())
    pending = (ClubMembership.query.filter_by(club_id=club.id, status='pending')
               .join(User, ClubMembership.user_id == User.id)
               .add_entity(User).all())
    pending_payment = (ClubMembership.query.filter_by(club_id=club.id, status='pending_payment')
                       .join(User, ClubMembership.user_id == User.id)
                       .add_entity(User).all())
    pending_transfers = (ClubOwnershipTransfer.query
                         .filter_by(club_id=club.id, status='pending')
                         .order_by(ClubOwnershipTransfer.created_at.desc())
                         .all())
    return render_template('admin/club_team.html', club=club,
                           admins=admins, members=members, pending=pending,
                           pending_payment=pending_payment,
                           owner=club.effective_owner,
                           can_transfer_owner=_can_transfer_club_owner(club),
                           pending_transfers=pending_transfers)


@admin_bp.route('/clubs/<slug>/team/transfer-owner', methods=['POST'])
@club_admin_required
def club_team_transfer_owner(slug):
    club = _get_club_or_404(slug)
    if not _can_transfer_club_owner(club):
        abort(403)

    email = (request.form.get('email') or '').strip()
    confirm_email = (request.form.get('confirm_email') or '').strip()
    if email.lower() != confirm_email.lower():
        flash('Email confirmation must match the new owner email.', 'danger')
        return redirect(url_for('admin.club_team', slug=slug))

    user = _find_user_by_email(email)
    if not user:
        flash(f'No active Paceline user was found with email "{email}".', 'danger')
        return redirect(url_for('admin.club_team', slug=slug))
    if not user.is_active:
        flash('That account is disabled and cannot own a club.', 'danger')
        return redirect(url_for('admin.club_team', slug=slug))
    if user.id == getattr(club.effective_owner, 'id', None):
        flash(f'{user.username} already owns this club.', 'info')
        return redirect(url_for('admin.club_team', slug=slug))

    now = datetime.now(timezone.utc)
    ClubOwnershipTransfer.query.filter_by(club_id=club.id, status='pending').update({
        'status': 'cancelled',
        'cancelled_at': now,
    })
    transfer = ClubOwnershipTransfer(
        club_id=club.id,
        from_user_id=current_user.id,
        to_user_id=user.id,
        expires_at=now + timedelta(days=7),
    )
    db.session.add(transfer)
    _audit('request_club_owner_transfer', target_user=user,
           details=f'club_id={club.id}; from_user_id={current_user.id}; to_user_id={user.id}')
    db.session.commit()

    accept_url = url_for('admin.club_ownership_transfer_accept',
                         token=transfer.token, _external=True)
    send_club_ownership_transfer_email(transfer, accept_url)
    flash(f'Ownership transfer sent to {user.email}. They must accept it before ownership changes.', 'success')
    return redirect(url_for('admin.club_team', slug=slug))


@admin_bp.route('/ownership-transfer/<token>', methods=['GET', 'POST'])
@login_required
def club_ownership_transfer_accept(token):
    fresh_response = _require_fresh_auth()
    if fresh_response:
        return fresh_response
    transfer = ClubOwnershipTransfer.query.filter_by(token=token).first_or_404()
    if transfer.to_user_id != current_user.id:
        flash('Sign in as the user this ownership transfer was sent to.', 'danger')
        return redirect(url_for('main.index'))
    if transfer.status != 'pending' or transfer.is_expired:
        flash('This ownership transfer is no longer available.', 'danger')
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        _ensure_owner_membership_and_admin(transfer.club, current_user)
        transfer.status = 'accepted'
        transfer.accepted_at = datetime.now(timezone.utc)
        _audit('accept_club_owner_transfer', target_user=current_user,
               details=f'club_id={transfer.club_id}; from_user_id={transfer.from_user_id}; to_user_id={transfer.to_user_id}')
        db.session.commit()
        flash(f'You are now the owner of {transfer.club.name}.', 'success')
        return redirect(url_for('admin.club_dashboard', slug=transfer.club.slug))

    return render_template('admin/club_ownership_transfer.html', transfer=transfer)


@admin_bp.route('/clubs/<slug>/team/add', methods=['POST'])
@club_admin_required
def club_team_add(slug):
    club = _get_club_or_404(slug)
    identifier = request.form.get('identifier', '').strip()
    role = request.form.get('role', 'admin')
    if role not in ('admin', 'ride_manager', 'content_editor', 'treasurer'):
        abort(400)

    user = (User.query.filter(
        (User.email == identifier) | (User.username == identifier)
    ).first())
    if not user:
        flash(f'No user found with email or username "{identifier}".', 'danger')
        return redirect(url_for('admin.club_team', slug=slug))

    existing = ClubAdmin.query.filter_by(user_id=user.id, club_id=club.id).first()
    if existing:
        existing.role = role
        db.session.commit()
        flash(f'{user.username} role updated to {role}.', 'success')
    else:
        db.session.add(ClubAdmin(user_id=user.id, club_id=club.id, role=role))
        db.session.commit()
        flash(f'{user.username} added as {role}.', 'success')

    return redirect(url_for('admin.club_team', slug=slug))


@admin_bp.route('/clubs/<slug>/team/<int:admin_id>/remove', methods=['POST'])
@club_admin_required
def club_team_remove(slug, admin_id):
    club = _get_club_or_404(slug)
    row = ClubAdmin.query.filter_by(id=admin_id, club_id=club.id).first_or_404()

    # Prevent removing self if you're the only full admin
    full_admins = ClubAdmin.query.filter_by(club_id=club.id, role='admin').count()
    if row.user_id == current_user.id and full_admins <= 1:
        flash('Cannot remove yourself — you are the only club admin.', 'danger')
        return redirect(url_for('admin.club_team', slug=slug))

    username = row.user.username
    db.session.delete(row)
    db.session.commit()
    flash(f'{username} removed from club team.', 'info')
    return redirect(url_for('admin.club_team', slug=slug))


@admin_bp.route('/clubs/<slug>/members/add', methods=['POST'])
@club_admin_required
def club_member_add(slug):
    club = _get_club_or_404(slug)
    identifier = request.form.get('identifier', '').strip()
    user = User.query.filter(
        (User.email == identifier) | (User.username == identifier)
    ).first()
    if not user:
        flash(f'No user found with email or username "{identifier}".', 'danger')
        return redirect(url_for('admin.club_team', slug=slug))

    existing = ClubMembership.query.filter_by(user_id=user.id, club_id=club.id).first()
    if existing:
        if existing.status == 'active':
            flash(f'{user.username} is already a member.', 'info')
        else:
            existing.status = 'active'
            db.session.commit()
            flash(f'{user.username} approved and added as a member.', 'success')
    else:
        db.session.add(ClubMembership(user_id=user.id, club_id=club.id, status='active'))
        db.session.commit()
        flash(f'{user.username} added as a member.', 'success')

    return redirect(url_for('admin.club_team', slug=slug))


@admin_bp.route('/clubs/<slug>/members/<int:uid>/remove', methods=['POST'])
@club_admin_required
def club_member_remove(slug, uid):
    club = _get_club_or_404(slug)
    row = ClubMembership.query.filter_by(user_id=uid, club_id=club.id).first_or_404()
    username = row.user.username
    db.session.delete(row)
    db.session.commit()
    flash(f'{username} removed from club.', 'info')
    return redirect(url_for('admin.club_team', slug=slug))


@admin_bp.route('/clubs/<slug>/members/<int:uid>/approve', methods=['POST'])
@club_admin_required
def club_member_approve(slug, uid):
    club = _get_club_or_404(slug)
    row = ClubMembership.query.filter_by(user_id=uid, club_id=club.id, status='pending').first_or_404()
    row.status = 'active'
    db.session.commit()
    send_membership_approved(row.user, club)
    flash(f'{row.user.username} approved and is now an active member.', 'success')
    return redirect(url_for('admin.club_team', slug=slug))


@admin_bp.route('/clubs/<slug>/members/<int:uid>/confirm-dues', methods=['POST'])
@club_admin_required
def club_member_confirm_dues(slug, uid):
    club = _get_club_or_404(slug)
    ClubMembership.query.filter_by(user_id=uid, club_id=club.id, status='pending_payment').first_or_404()
    flash('Paid dues must be completed through Stripe Connect. Manual dues confirmation is not available.', 'warning')
    return redirect(url_for('admin.club_team', slug=slug))


@admin_bp.route('/clubs/<slug>/members/<int:uid>/reject', methods=['POST'])
@club_admin_required
def club_member_reject(slug, uid):
    club = _get_club_or_404(slug)
    row = (ClubMembership.query
           .filter(ClubMembership.user_id == uid,
                   ClubMembership.club_id == club.id,
                   ClubMembership.status.in_(('pending', 'pending_payment')))
           .first_or_404())
    username = row.user.username
    send_membership_rejected(row.user, club)
    db.session.delete(row)
    db.session.commit()
    flash(f'{username}\'s membership request was rejected.', 'info')
    return redirect(url_for('admin.club_team', slug=slug))


# ── Club news/announcements ───────────────────────────────────────────────────

@admin_bp.route('/clubs/<slug>/posts')
@club_content_required
def club_posts(slug):
    club = _get_club_or_404(slug)
    posts = (ClubPost.query.filter_by(club_id=club.id)
             .order_by(ClubPost.published_at.desc()).all())
    return render_template('admin/club_posts.html', club=club, posts=posts)


def _save_post_image(file, club_id):
    """Process and store a news post header image. Returns the storage key."""
    data = process_post_image(file.stream.read())
    key = f'post_images/{club_id}/{uuid.uuid4().hex}.jpg'
    storage = get_storage()
    storage.save(key, data, upload_folder=current_app.config['UPLOAD_FOLDER'])
    return key


def _delete_post_image(key):
    if key:
        try:
            get_storage().delete(key, upload_folder=current_app.config['UPLOAD_FOLDER'])
        except Exception:
            pass


@admin_bp.route('/clubs/<slug>/posts/new', methods=['GET', 'POST'])
@club_content_required
def post_new(slug):
    club = _get_club_or_404(slug)
    form = ClubPostForm()
    if form.validate_on_submit():
        image_key = None
        if form.image_file.data and form.image_file.data.filename:
            image_key = _save_post_image(form.image_file.data, club.id)
        post = ClubPost(
            club_id=club.id,
            author_id=current_user.id,
            title=form.title.data,
            body=form.body.data,
            image_key=image_key,
        )
        db.session.add(post)
        db.session.commit()
        send_club_news_notification(post)
        flash('Post published.', 'success')
        return redirect(url_for('admin.club_posts', slug=slug))
    return render_template('admin/post_form.html', form=form, club=club, title='New Post', post=None)


@admin_bp.route('/clubs/<slug>/posts/<int:post_id>/edit', methods=['GET', 'POST'])
@club_content_required
def post_edit(slug, post_id):
    club = _get_club_or_404(slug)
    post = ClubPost.query.filter_by(id=post_id, club_id=club.id).first_or_404()
    form = ClubPostForm(obj=post)
    if form.validate_on_submit():
        post.title = form.title.data
        post.body  = form.body.data
        if form.image_file.data and form.image_file.data.filename:
            _delete_post_image(post.image_key)
            post.image_key = _save_post_image(form.image_file.data, club.id)
        db.session.commit()
        flash('Post updated.', 'success')
        return redirect(url_for('admin.club_posts', slug=slug))
    return render_template('admin/post_form.html', form=form, club=club, title='Edit Post', post=post)


@admin_bp.route('/clubs/<slug>/posts/<int:post_id>/delete', methods=['POST'])
@club_content_required
def post_delete(slug, post_id):
    club = _get_club_or_404(slug)
    post = ClubPost.query.filter_by(id=post_id, club_id=club.id).first_or_404()
    _delete_post_image(post.image_key)
    db.session.delete(post)
    db.session.commit()
    flash('Post deleted.', 'info')
    return redirect(url_for('admin.club_posts', slug=slug))


# ── Ride leaders roster ───────────────────────────────────────────────────────

def _eligible_leader_members(club):
    """Active members in good standing (dues current if required), sorted by username."""
    today = date.today()
    query = (ClubMembership.query
             .filter_by(club_id=club.id, status='active')
             .join(ClubMembership.user))
    if club.membership_dues_required:
        query = query.filter(
            ClubMembership.dues_paid_until.isnot(None),
            ClubMembership.dues_paid_until >= today,
        )
    return query.order_by(User.username.asc()).all()


@admin_bp.route('/clubs/<slug>/leaders')
@club_admin_required
def club_leaders(slug):
    club = _get_club_or_404(slug)
    return render_template('admin/club_leaders.html', club=club, leaders=club.leaders)


@admin_bp.route('/clubs/<slug>/leaders/new', methods=['GET', 'POST'])
@club_admin_required
def leader_new(slug):
    club = _get_club_or_404(slug)
    form = ClubLeaderForm()
    eligible = _eligible_leader_members(club)
    if request.method == 'POST':
        user_id = request.form.get('user_id', type=int)
        user = User.query.get(user_id) if user_id else None
        eligible_user_ids = {row.user_id for row in eligible}
        if not user:
            flash('Please select a member.', 'danger')
        elif user_id not in eligible_user_ids:
            flash('Please select an active member in good standing.', 'danger')
        elif ClubLeader.query.filter_by(club_id=club.id, user_id=user_id).first():
            flash(f'{user.username} is already on the leaders roster.', 'warning')
        elif form.validate():
            db.session.add(ClubLeader(
                club_id=club.id,
                user_id=user_id,
                name=user.username,
                bio=form.bio.data.strip() or None,
                display_order=form.display_order.data or 0,
            ))
            db.session.commit()
            flash(f'{user.username} added to the leaders roster.', 'success')
            return redirect(url_for('admin.club_leaders', slug=slug))
    return render_template('admin/leader_form.html', form=form, club=club,
                           title='Add Ride Leader', eligible=eligible, leader=None)


@admin_bp.route('/clubs/<slug>/leaders/<int:leader_id>/edit', methods=['GET', 'POST'])
@club_admin_required
def leader_edit(slug, leader_id):
    club = _get_club_or_404(slug)
    leader = ClubLeader.query.filter_by(id=leader_id, club_id=club.id).first_or_404()
    form = ClubLeaderForm(obj=leader)
    eligible = _eligible_leader_members(club)
    if request.method == 'POST':
        user_id = request.form.get('user_id', type=int)
        user = User.query.get(user_id) if user_id else None
        eligible_user_ids = {row.user_id for row in eligible}
        if not user:
            flash('Please select a member.', 'danger')
        elif user_id not in eligible_user_ids and user_id != leader.user_id:
            flash('Please select an active member in good standing.', 'danger')
        elif form.validate():
            # Allow re-selecting the same user on edit; block switching to a duplicate
            existing = ClubLeader.query.filter_by(club_id=club.id, user_id=user_id).first()
            if existing and existing.id != leader.id:
                flash(f'{user.username} is already on the leaders roster.', 'warning')
            else:
                leader.user_id       = user_id
                leader.name          = user.username
                leader.bio           = form.bio.data.strip() or None
                leader.display_order = form.display_order.data or 0
                db.session.commit()
                flash('Leader updated.', 'success')
                return redirect(url_for('admin.club_leaders', slug=slug))
    return render_template('admin/leader_form.html', form=form, club=club,
                           title='Edit Ride Leader', eligible=eligible, leader=leader)


@admin_bp.route('/clubs/<slug>/leaders/<int:leader_id>/delete', methods=['POST'])
@club_admin_required
def leader_delete(slug, leader_id):
    club = _get_club_or_404(slug)
    leader = ClubLeader.query.filter_by(id=leader_id, club_id=club.id).first_or_404()
    db.session.delete(leader)
    db.session.commit()
    flash('Leader removed.', 'info')
    return redirect(url_for('admin.club_leaders', slug=slug))


# ── Sponsors ──────────────────────────────────────────────────────────────────

@admin_bp.route('/clubs/<slug>/sponsors')
@club_admin_required
def club_sponsors(slug):
    club = _get_club_or_404(slug)
    return render_template('admin/club_sponsors.html', club=club, sponsors=club.sponsors)


def _save_sponsor_logo(file, club_id):
    """Process and store an uploaded sponsor logo. Returns the storage key."""
    data = process_logo_image(file.stream.read())
    key = f'sponsor_logos/{club_id}/{uuid.uuid4().hex}.jpg'
    storage = get_storage()
    storage.save(key, data, upload_folder=current_app.config['UPLOAD_FOLDER'])
    return key


def _delete_sponsor_logo(key):
    if key:
        try:
            get_storage().delete(key, upload_folder=current_app.config['UPLOAD_FOLDER'])
        except Exception:
            pass


def _save_club_logo(file, club_id):
    data = process_logo_image(file.stream.read())
    key = f'club_logos/{club_id}/{uuid.uuid4().hex}.jpg'
    storage = get_storage()
    storage.save(key, data, upload_folder=current_app.config['UPLOAD_FOLDER'])
    return key


def _delete_club_logo(key):
    if key:
        try:
            get_storage().delete(key, upload_folder=current_app.config['UPLOAD_FOLDER'])
        except Exception:
            pass


@admin_bp.route('/clubs/<slug>/sponsors/new', methods=['GET', 'POST'])
@club_admin_required
def sponsor_new(slug):
    club = _get_club_or_404(slug)
    form = ClubSponsorForm()
    if form.validate_on_submit():
        logo_key = None
        logo_url = form.logo_url.data or None
        if form.logo_file.data and form.logo_file.data.filename:
            logo_key = _save_sponsor_logo(form.logo_file.data, club.id)
            logo_url = None
        db.session.add(ClubSponsor(
            club_id=club.id,
            name=form.name.data,
            logo_url=logo_url,
            logo_key=logo_key,
            website=form.website.data or None,
            display_order=form.display_order.data or 0,
        ))
        db.session.commit()
        flash('Sponsor added.', 'success')
        return redirect(url_for('admin.club_sponsors', slug=slug))
    return render_template('admin/sponsor_form.html', form=form, club=club, title='Add Sponsor', sponsor=None)


@admin_bp.route('/clubs/<slug>/sponsors/<int:sponsor_id>/edit', methods=['GET', 'POST'])
@club_admin_required
def sponsor_edit(slug, sponsor_id):
    club = _get_club_or_404(slug)
    sponsor = ClubSponsor.query.filter_by(id=sponsor_id, club_id=club.id).first_or_404()
    form = ClubSponsorForm(obj=sponsor)
    if form.validate_on_submit():
        sponsor.name          = form.name.data
        sponsor.website       = form.website.data or None
        sponsor.display_order = form.display_order.data or 0
        if form.logo_file.data and form.logo_file.data.filename:
            _delete_sponsor_logo(sponsor.logo_key)
            sponsor.logo_key = _save_sponsor_logo(form.logo_file.data, club.id)
            sponsor.logo_url = None
        elif form.logo_url.data:
            _delete_sponsor_logo(sponsor.logo_key)
            sponsor.logo_key = None
            sponsor.logo_url = form.logo_url.data
        db.session.commit()
        flash('Sponsor updated.', 'success')
        return redirect(url_for('admin.club_sponsors', slug=slug))
    return render_template('admin/sponsor_form.html', form=form, club=club, title='Edit Sponsor', sponsor=sponsor)


@admin_bp.route('/clubs/<slug>/sponsors/<int:sponsor_id>/delete', methods=['POST'])
@club_admin_required
def sponsor_delete(slug, sponsor_id):
    club = _get_club_or_404(slug)
    sponsor = ClubSponsor.query.filter_by(id=sponsor_id, club_id=club.id).first_or_404()
    _delete_sponsor_logo(sponsor.logo_key)
    db.session.delete(sponsor)
    db.session.commit()
    flash('Sponsor removed.', 'info')
    return redirect(url_for('admin.club_sponsors', slug=slug))


# ── Club Shop ────────────────────────────────────────────────────────────────

@admin_bp.route('/clubs/<slug>/shop')
@club_admin_required
def club_shop(slug):
    club = _get_club_or_404(slug)
    settings_form = ClubShopSettingsForm(obj=club)
    if club.shop_shipping_fee_cents is not None:
        settings_form.shop_shipping_fee.data = club.shop_shipping_fee_cents / 100
    items = ClubShopItem.query.filter_by(club_id=club.id).order_by(
        ClubShopItem.display_order.asc(),
        ClubShopItem.name.asc(),
    ).all()
    orders = (ClubShopOrder.query
              .filter_by(club_id=club.id)
              .order_by(ClubShopOrder.created_at.desc())
              .limit(100)
              .all())
    active_count = sum(1 for item in items if item.is_active)
    return render_template(
        'admin/club_shop.html',
        club=club,
        settings_form=settings_form,
        items=items,
        orders=orders,
        active_count=active_count,
        max_items=50,
    )


def _normalize_shipping_countries(value):
    countries = []
    for raw in (value or 'US').split(','):
        country = raw.strip().upper()
        if not country:
            continue
        if not re.fullmatch(r'[A-Z]{2}', country):
            return None
        countries.append(country)
    return ','.join(dict.fromkeys(countries)) or 'US'


@admin_bp.route('/clubs/<slug>/shop/settings', methods=['POST'])
@club_admin_required
def club_shop_settings(slug):
    club = _get_club_or_404(slug)
    if not club.stripe_connect_ready:
        flash('Connect Stripe before enabling the club shop. Shop checkout is only available through Stripe Connect.', 'warning')
        return redirect(url_for('admin.club_shop', slug=slug))
    form = ClubShopSettingsForm()
    if form.validate_on_submit():
        countries = _normalize_shipping_countries(form.shop_shipping_countries.data)
        if countries is None:
            flash('Allowed shipping countries must be comma-separated two-letter country codes, like US or US,CA.', 'danger')
            return redirect(url_for('admin.club_shop', slug=slug))
        club.shop_tax_enabled = bool(form.shop_tax_enabled.data)
        club.shop_shipping_enabled = bool(form.shop_shipping_enabled.data)
        club.shop_shipping_countries = countries
        if club.shop_shipping_enabled:
            fee = form.shop_shipping_fee.data
            club.shop_shipping_fee_cents = int(round(float(fee or 0) * 100))
        else:
            club.shop_shipping_fee_cents = None
        db.session.commit()
        flash('Shop settings updated.', 'success')
    else:
        flash('Shop settings not saved. Check the highlighted fields.', 'danger')
    return redirect(url_for('admin.club_shop', slug=slug))


def _apply_shop_item_form(item, form):
    item.name = form.name.data
    item.description = form.description.data or None
    item.image_url = form.image_url.data or None
    item.price_cents = int(round(float(form.price.data) * 100))
    item.currency = 'usd'
    item.is_active = bool(form.is_active.data)
    item.display_order = form.display_order.data or 0
    item.fulfillment_notes = form.fulfillment_notes.data or None


@admin_bp.route('/clubs/<slug>/shop/new', methods=['GET', 'POST'])
@club_admin_required
def shop_item_new(slug):
    club = _get_club_or_404(slug)
    if not club.stripe_connect_ready:
        flash('Connect Stripe before adding shop items. The club shop is only available through Stripe Connect.', 'warning')
        return redirect(url_for('admin.club_shop', slug=slug))
    active_count = ClubShopItem.query.filter_by(club_id=club.id, is_active=True).count()
    form = ClubShopItemForm()
    if form.validate_on_submit():
        if form.is_active.data and active_count >= 50:
            flash('This club already has 50 active shop items. Archive an item before adding another active item.', 'warning')
            return render_template('admin/shop_item_form.html', form=form, club=club, title='Add Shop Item', item=None)
        item = ClubShopItem(club_id=club.id, price_cents=0)
        _apply_shop_item_form(item, form)
        db.session.add(item)
        db.session.commit()
        flash('Shop item added.', 'success')
        return redirect(url_for('admin.club_shop', slug=slug))
    return render_template('admin/shop_item_form.html', form=form, club=club, title='Add Shop Item', item=None)


@admin_bp.route('/clubs/<slug>/shop/<int:item_id>/edit', methods=['GET', 'POST'])
@club_admin_required
def shop_item_edit(slug, item_id):
    club = _get_club_or_404(slug)
    if not club.stripe_connect_ready:
        flash('Connect Stripe before managing shop items. The club shop is only available through Stripe Connect.', 'warning')
        return redirect(url_for('admin.club_shop', slug=slug))
    item = ClubShopItem.query.filter_by(id=item_id, club_id=club.id).first_or_404()
    form = ClubShopItemForm(obj=item)
    if request.method == 'GET':
        form.price.data = item.price_cents / 100
    if form.validate_on_submit():
        active_count = ClubShopItem.query.filter(
            ClubShopItem.club_id == club.id,
            ClubShopItem.is_active == True,
            ClubShopItem.id != item.id,
        ).count()
        if form.is_active.data and active_count >= 50:
            flash('This club already has 50 active shop items. Archive an item before activating another item.', 'warning')
            return render_template('admin/shop_item_form.html', form=form, club=club, title='Edit Shop Item', item=item)
        _apply_shop_item_form(item, form)
        db.session.commit()
        flash('Shop item updated.', 'success')
        return redirect(url_for('admin.club_shop', slug=slug))
    return render_template('admin/shop_item_form.html', form=form, club=club, title='Edit Shop Item', item=item)


@admin_bp.route('/clubs/<slug>/shop/<int:item_id>/delete', methods=['POST'])
@club_admin_required
def shop_item_delete(slug, item_id):
    club = _get_club_or_404(slug)
    if not club.stripe_connect_ready:
        flash('Connect Stripe before managing shop items. The club shop is only available through Stripe Connect.', 'warning')
        return redirect(url_for('admin.club_shop', slug=slug))
    item = ClubShopItem.query.filter_by(id=item_id, club_id=club.id).first_or_404()
    if item.orders:
        item.is_active = False
        db.session.commit()
        flash('Shop item has orders, so it was archived instead of deleted.', 'info')
        return redirect(url_for('admin.club_shop', slug=slug))
    db.session.delete(item)
    db.session.commit()
    flash('Shop item removed.', 'info')
    return redirect(url_for('admin.club_shop', slug=slug))


# ── Invites ───────────────────────────────────────────────────────────────────

@admin_bp.route('/clubs/<slug>/invites', methods=['GET', 'POST'])
@club_admin_required
def club_invites(slug):
    import secrets
    from datetime import datetime, timezone, timedelta
    club = _get_club_or_404(slug)
    form = ClubInviteForm()
    if form.validate_on_submit():
        token = secrets.token_urlsafe(32)
        invite = ClubInvite(
            club_id=club.id,
            email=form.email.data.strip().lower(),
            token=token,
            expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=7),
            created_by=current_user.id,
        )
        db.session.add(invite)
        db.session.commit()
        send_invite_email(invite)
        flash(f'Invite sent to {invite.email}.', 'success')
        return redirect(url_for('admin.club_invites', slug=slug))
    invites = (ClubInvite.query.filter_by(club_id=club.id)
               .order_by(ClubInvite.id.desc()).limit(50).all())
    now = datetime.now(timezone.utc)
    return render_template('admin/club_invites.html', club=club, form=form, invites=invites, now=now)


# ── Bulk member import ────────────────────────────────────────────────────────

def _make_username(email):
    """Derive a unique username from an email address."""
    import re as _re
    local = email.split('@')[0]
    base = _re.sub(r'[^a-zA-Z0-9._-]', '', local)[:28] or 'rider'
    candidate = base
    n = 1
    while User.query.filter_by(username=candidate).first():
        candidate = f'{base}{n}'
        n += 1
    return candidate


@admin_bp.route('/clubs/<slug>/import', methods=['GET', 'POST'])
@club_admin_required
def club_import(slug):
    import re as _re
    from datetime import datetime, timedelta
    club = _get_club_or_404(slug)
    form = BulkImportForm()
    results = None

    if form.validate_on_submit():
        rows = []
        seen_emails = set()
        default_expires_on = form.membership_expires_on.data
        for raw_line in (form.emails.data or '').splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            parts = [part.strip() for part in _re.split(r'[,;]', raw_line) if part.strip()]
            if len(parts) == 1:
                email = parts[0].lower()
                expires_on = default_expires_on
            else:
                email = parts[0].lower()
                try:
                    expires_on = datetime.strptime(parts[1], '%Y-%m-%d').date()
                except ValueError:
                    rows.append((email, default_expires_on, 'Invalid expiration date. Use YYYY-MM-DD.'))
                    continue
            if email not in seen_emails:
                rows.append((email, expires_on, None))
                seen_emails.add(email)

        MAX_IMPORT = 200
        if len(rows) > MAX_IMPORT:
            flash(f'Maximum {MAX_IMPORT} emails per import. Please split into batches.', 'danger')
            return render_template('admin/club_import.html', club=club, form=form, results=None)

        created, invited, already_members, invalid = [], [], [], []

        for email, expires_on, row_error in rows:
            if row_error:
                invalid.append(f'{email} — {row_error}')
                continue
            if not _re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
                invalid.append(email)
                continue

            existing_user = User.query.filter_by(email=email).first()

            if existing_user:
                mem = ClubMembership.query.filter_by(
                    user_id=existing_user.id, club_id=club.id
                ).first()
                if mem and mem.status == 'active':
                    if expires_on:
                        mem.dues_paid_until = expires_on
                        mem.dues_confirmed_at = datetime.now(timezone.utc)
                        mem.dues_confirmed_by_id = current_user.id
                    already_members.append(email)
                    continue
                # Existing Paceline user not yet in this club — send confirmation invite
                token = secrets.token_urlsafe(32)
                invite = ClubInvite(
                    club_id=club.id,
                    email=email,
                    token=token,
                    expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=7),
                    created_by=current_user.id,
                    is_new_user=False,
                    membership_expires_on=expires_on,
                )
                db.session.add(invite)
                db.session.flush()
                send_import_invite_email(invite)
                invited.append(email)
            else:
                # Brand-new user — create account, add to club, send setup email
                placeholder_pw = bcrypt.generate_password_hash(
                    secrets.token_hex(32)
                ).decode('utf-8')
                new_user = User(
                    username=_make_username(email),
                    email=email,
                    email_verified=False,
                    password_hash=placeholder_pw,
                )
                db.session.add(new_user)
                db.session.flush()
                db.session.add(ClubMembership(
                    user_id=new_user.id, club_id=club.id, status='active',
                    dues_paid_until=expires_on,
                    dues_confirmed_at=datetime.now(timezone.utc) if expires_on else None,
                    dues_confirmed_by_id=current_user.id if expires_on else None,
                ))
                token = secrets.token_urlsafe(32)
                invite = ClubInvite(
                    club_id=club.id,
                    email=email,
                    token=token,
                    expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=7),
                    created_by=current_user.id,
                    is_new_user=True,
                    membership_expires_on=expires_on,
                )
                db.session.add(invite)
                db.session.flush()
                send_import_welcome_email(invite)
                created.append(email)

        db.session.commit()
        results = {
            'created':         created,
            'invited':         invited,
            'already_members': already_members,
            'invalid':         invalid,
        }

    return render_template('admin/club_import.html', club=club, form=form, results=results)


# ── Superadmin ↔ Club Admin Messaging ────────────────────────────────────────

@admin_bp.route('/messages')
@superadmin_required
def messages_inbox():
    """Superadmin inbox: all club threads + recent broadcasts."""
    # One row per club that has any messages, with unread reply count
    clubs_with_msgs = (
        db.session.query(Club)
        .join(AdminMessage, AdminMessage.club_id == Club.id)
        .filter(AdminMessage.parent_id.is_(None))
        .distinct()
        .order_by(Club.name.asc())
        .all()
    )
    threads = []
    for club in clubs_with_msgs:
        root = (AdminMessage.query
                .filter_by(club_id=club.id, parent_id=None)
                .order_by(AdminMessage.created_at.desc())
                .first())
        unread = AdminMessage.query.filter_by(
            club_id=club.id, is_from_superadmin=False, is_read=False
        ).count()
        threads.append({'club': club, 'latest': root, 'unread': unread})

    broadcasts = (AdminMessage.query
                  .filter_by(club_id=None, parent_id=None)
                  .order_by(AdminMessage.created_at.desc())
                  .limit(10).all())

    all_clubs = Club.query.filter_by(is_hidden=False).order_by(Club.name.asc()).all()
    total_unread = sum(t['unread'] for t in threads)
    return render_template('admin/messages_inbox.html',
                           threads=threads, broadcasts=broadcasts,
                           all_clubs=all_clubs, total_unread=total_unread)


@admin_bp.route('/messages/club/<slug>', methods=['GET', 'POST'])
@superadmin_required
def messages_club_thread(slug):
    """Superadmin view/send for a specific club thread."""
    club = _get_club_or_404(slug)

    if request.method == 'POST':
        subject = request.form.get('subject', '').strip()
        body = request.form.get('body', '').strip()
        parent_id_raw = request.form.get('parent_id')
        if not body:
            flash('Message body cannot be empty.', 'danger')
            return redirect(url_for('admin.messages_club_thread', slug=slug))

        parent_id = int(parent_id_raw) if parent_id_raw else None
        msg = AdminMessage(
            club_id=club.id,
            sender_id=current_user.id,
            is_from_superadmin=True,
            subject=subject or None,
            body=body,
            parent_id=parent_id,
            is_read=False,
        )
        db.session.add(msg)
        db.session.commit()
        send_admin_message_to_club(msg, club)
        flash('Message sent.', 'success')
        return redirect(url_for('admin.messages_club_thread', slug=slug))

    # Mark all unread club-admin replies as read
    AdminMessage.query.filter_by(
        club_id=club.id, is_from_superadmin=False, is_read=False
    ).update({'is_read': True})
    db.session.commit()

    roots = (AdminMessage.query
             .filter_by(club_id=club.id, parent_id=None)
             .order_by(AdminMessage.created_at.asc())
             .all())
    threads = []
    for root in roots:
        replies = (AdminMessage.query
                   .filter_by(parent_id=root.id)
                   .order_by(AdminMessage.created_at.asc())
                   .all())
        threads.append({'root': root, 'replies': replies})

    return render_template('admin/messages_club_thread.html',
                           club=club, threads=threads)


@admin_bp.route('/messages/broadcast', methods=['GET', 'POST'])
@superadmin_required
def messages_broadcast():
    """Compose and send a broadcast notice to all club admins."""
    if request.method == 'POST':
        subject = request.form.get('subject', '').strip()
        body = request.form.get('body', '').strip()
        if not subject or not body:
            flash('Subject and body are required.', 'danger')
            return redirect(url_for('admin.messages_broadcast'))

        msg = AdminMessage(
            club_id=None,
            sender_id=current_user.id,
            is_from_superadmin=True,
            subject=subject,
            body=body,
            parent_id=None,
            is_read=False,
        )
        db.session.add(msg)
        db.session.commit()
        send_broadcast_to_club_admins(msg)
        _audit('broadcast_message', details=f'subject={subject[:80]}')
        flash('Broadcast sent to all club admins.', 'success')
        return redirect(url_for('admin.messages_inbox'))

    return render_template('admin/messages_broadcast.html')


# ── Club admin: view messages from superadmin and reply ──────────────────────

@admin_bp.route('/clubs/<slug>/messages', methods=['GET', 'POST'])
@club_admin_required
def club_messages(slug):
    """Club admin view of thread with superadmin; POST to reply."""
    club = _get_club_or_404(slug)

    if request.method == 'POST':
        body = request.form.get('body', '').strip()
        parent_id_raw = request.form.get('parent_id')
        if not body:
            flash('Reply cannot be empty.', 'danger')
            return redirect(url_for('admin.club_messages', slug=slug))

        parent_id = int(parent_id_raw) if parent_id_raw else None
        # If no parent provided, find the most recent root message
        if not parent_id:
            root = (AdminMessage.query
                    .filter_by(club_id=club.id, parent_id=None)
                    .order_by(AdminMessage.created_at.desc())
                    .first())
            if root:
                parent_id = root.id

        msg = AdminMessage(
            club_id=club.id,
            sender_id=current_user.id,
            is_from_superadmin=False,
            body=body,
            parent_id=parent_id,
            is_read=False,
        )
        db.session.add(msg)
        db.session.commit()
        send_club_reply_to_superadmin(msg, club)
        flash('Reply sent.', 'success')
        return redirect(url_for('admin.club_messages', slug=slug))

    # Mark all unread superadmin messages as read
    AdminMessage.query.filter_by(
        club_id=club.id, is_from_superadmin=True, is_read=False
    ).update({'is_read': True})
    db.session.commit()

    roots = (AdminMessage.query
             .filter_by(club_id=club.id, parent_id=None)
             .order_by(AdminMessage.created_at.asc())
             .all())
    threads = []
    for root in roots:
        replies = (AdminMessage.query
                   .filter_by(parent_id=root.id)
                   .order_by(AdminMessage.created_at.asc())
                   .all())
        threads.append({'root': root, 'replies': replies})

    # Recent broadcasts visible to all club admins
    broadcasts = (AdminMessage.query
                  .filter_by(club_id=None, parent_id=None)
                  .order_by(AdminMessage.created_at.desc())
                  .limit(5).all())

    return render_template('admin/club_messages.html',
                           club=club, threads=threads, broadcasts=broadcasts)
