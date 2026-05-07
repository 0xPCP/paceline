from functools import wraps
import time
from datetime import date, datetime, timedelta, timezone
from flask import Blueprint, render_template, redirect, url_for, flash, abort, request
from flask_login import login_required, current_user, login_fresh
import secrets
import string
from markupsafe import Markup, escape as html_escape
from sqlalchemy import or_, func
from ..extensions import db, bcrypt
from ..models import (AdminAuditLog, Club, Ride, RideSignup, SiteFeedback, User,
                      ClubMembership, ClubAdmin, ClubPost, ClubLeader, ClubSponsor,
                      ClubInvite, ClubOwnershipTransfer)
from ..forms import RideForm, ClubForm, ClubSettingsForm, ClubPostForm, ClubLeaderForm, ClubSponsorForm, ClubInviteForm, BulkImportForm
from ..recurrence import generate_instances, delete_future_instances
from ..geocoding import geocode_zip
from ..admin_stats import (active_superadmin_count, configured_superadmin_emails,
                           platform_report)
from ..email import (send_cancellation_emails, send_new_ride_notification,
                     send_membership_approved, send_membership_rejected, send_invite_email,
                     send_import_welcome_email, send_import_invite_email,
                     send_club_ownership_transfer_email)

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
    membership.status = 'active'
    membership.dues_paid_until = _default_dues_expiration(membership.club)
    membership.dues_confirmed_at = datetime.now(timezone.utc)
    membership.dues_confirmed_by_id = confirmed_by.id


def _can_transfer_club_owner(club):
    owner = club.effective_owner
    if current_user.is_admin:
        return True
    if owner and owner.id == current_user.id:
        return True
    return owner is None and current_user.is_club_admin(club)


def _find_user_by_email(email):
    email = (email or '').strip().lower()
    if not email:
        return None
    return User.query.filter(func.lower(User.email) == email).first()


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
    return _add_months(date.today(), club.membership_duration_months or 12)


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

@admin_bp.route('/')
@superadmin_required
def dashboard():
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
    return render_template('admin/dashboard.html', stats=stats, clubs=clubs,
                           super_admins=super_admins, popular=popular,
                           ungeocodeable_count=ungeocodeable_count,
                           report=report, recent_audit=recent_audit,
                           unread_feedback_count=unread_feedback_count)


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


@admin_bp.route('/users/<int:user_id>')
@superadmin_required
def user_detail(user_id):
    profile_user   = User.query.get_or_404(user_id)
    recent_signups = (RideSignup.query
                      .filter_by(user_id=user_id)
                      .order_by(RideSignup.id.desc())
                      .limit(10).all())
    return render_template('admin/user_detail.html',
                           profile_user=profile_user,
                           recent_signups=recent_signups)


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
    return render_template('admin/club_dashboard.html', club=club,
                           upcoming=upcoming, stats=stats,
                           is_full_admin=is_full_admin)


@admin_bp.route('/clubs/<slug>/settings', methods=['GET', 'POST'])
@club_admin_required
def club_settings(slug):
    club = _get_club_or_404(slug)
    form = ClubSettingsForm(obj=club)
    if form.validate_on_submit():
        club.name         = form.name.data
        club.tagline      = form.tagline.data or None
        club.description  = form.description.data or None
        club.city         = form.city.data or None
        club.state        = form.state.data or None
        club.address      = form.address.data or None
        club.contact_email = form.contact_email.data or None
        club.logo_url     = form.logo_url.data or None

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

        raw_strava = (form.strava_club_id.data or '').strip()
        club.strava_club_id = int(raw_strava) if raw_strava.isdigit() else None

        club.auto_cancel_enabled = form.auto_cancel_enabled.data
        club.cancel_rain_prob    = form.cancel_rain_prob.data or 80
        club.cancel_wind_mph     = form.cancel_wind_mph.data or 35
        club.cancel_temp_min_f   = form.cancel_temp_min_f.data if form.cancel_temp_min_f.data is not None else 28
        club.cancel_temp_max_f   = form.cancel_temp_max_f.data if form.cancel_temp_max_f.data is not None else 100

        club.is_private         = form.is_private.data
        club.require_membership = form.require_membership.data
        club.join_approval      = form.join_approval.data if form.join_approval.data in ('auto', 'manual') else 'auto'
        club.membership_dues_required = form.membership_dues_required.data
        club.membership_dues_url = form.membership_dues_url.data or None
        club.membership_duration_months = form.membership_duration_months.data or 12

        club.facebook_url      = form.facebook_url.data or None
        club.instagram_url     = form.instagram_url.data or None
        club.twitter_url       = form.twitter_url.data or None
        club.newsletter_url    = form.newsletter_url.data or None
        club.bylaws_url        = form.bylaws_url.data or None
        club.safety_guidelines = form.safety_guidelines.data or None

        db.session.commit()
        flash('Club settings updated.', 'success')
        return redirect(url_for('admin.club_settings', slug=slug))

    return render_template('admin/club_settings.html', form=form, club=club)


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
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Username', 'Email', 'Status', 'Joined',
                     'Emergency Contact', 'Emergency Phone'])
    for m in memberships:
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
    all_rides = (Ride.query.filter_by(club_id=club.id)
                 .order_by(Ride.date.desc()).all())
    return render_template('admin/club_rides.html', club=club, rides=all_rides)


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
    if form.validate_on_submit():
        leader_id, ride_leader = _resolve_leader(club)
        ride = Ride(
            club_id=club.id,
            title=form.title.data,
            date=form.date.data,
            time=form.time.data,
            meeting_location=form.meeting_location.data,
            distance_miles=form.distance_miles.data,
            elevation_feet=form.elevation_feet.data,
            pace_category=form.pace_category.data,
            ride_type=form.ride_type.data,
            max_riders=form.max_riders.data or None,
            leader_id=leader_id,
            ride_leader=ride_leader,
            route_url=form.route_url.data or None,
            video_url=form.video_url.data or None,
            garmin_groupride_code=(form.garmin_groupride_code.data or '').strip() or None,
            description=form.description.data or None,
            is_cancelled=form.is_cancelled.data,
            is_recurring=form.is_recurring.data,
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
    if form.validate_on_submit():
        was_recurring  = ride.is_recurring
        was_cancelled  = ride.is_cancelled
        leader_id, ride_leader = _resolve_leader(club)
        ride.title          = form.title.data
        ride.date           = form.date.data
        ride.time           = form.time.data
        ride.meeting_location = form.meeting_location.data
        ride.distance_miles = form.distance_miles.data
        ride.elevation_feet = form.elevation_feet.data
        ride.pace_category  = form.pace_category.data
        ride.ride_type      = form.ride_type.data or None
        ride.max_riders     = form.max_riders.data or None
        ride.leader_id      = leader_id
        ride.ride_leader    = ride_leader
        ride.route_url      = form.route_url.data or None
        ride.video_url      = form.video_url.data or None
        ride.garmin_groupride_code = (form.garmin_groupride_code.data or '').strip() or None
        ride.description    = form.description.data or None
        ride.is_cancelled   = form.is_cancelled.data
        ride.is_recurring   = form.is_recurring.data
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
    row = ClubMembership.query.filter_by(user_id=uid, club_id=club.id, status='pending_payment').first_or_404()
    _confirm_membership_dues(row, current_user)
    db.session.commit()
    send_membership_approved(row.user, club)
    flash(f'{row.user.username} dues confirmed through {row.dues_paid_until:%b %d, %Y}. Membership is active.', 'success')
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


@admin_bp.route('/clubs/<slug>/posts/new', methods=['GET', 'POST'])
@club_content_required
def post_new(slug):
    club = _get_club_or_404(slug)
    form = ClubPostForm()
    if form.validate_on_submit():
        post = ClubPost(
            club_id=club.id,
            author_id=current_user.id,
            title=form.title.data,
            body=form.body.data,
        )
        db.session.add(post)
        db.session.commit()
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
        db.session.commit()
        flash('Post updated.', 'success')
        return redirect(url_for('admin.club_posts', slug=slug))
    return render_template('admin/post_form.html', form=form, club=club, title='Edit Post', post=post)


@admin_bp.route('/clubs/<slug>/posts/<int:post_id>/delete', methods=['POST'])
@club_content_required
def post_delete(slug, post_id):
    club = _get_club_or_404(slug)
    post = ClubPost.query.filter_by(id=post_id, club_id=club.id).first_or_404()
    db.session.delete(post)
    db.session.commit()
    flash('Post deleted.', 'info')
    return redirect(url_for('admin.club_posts', slug=slug))


# ── Ride leaders roster ───────────────────────────────────────────────────────

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
    if form.validate_on_submit():
        db.session.add(ClubLeader(
            club_id=club.id,
            name=form.name.data,
            bio=form.bio.data or None,
            photo_url=form.photo_url.data or None,
            display_order=form.display_order.data or 0,
        ))
        db.session.commit()
        flash('Leader added.', 'success')
        return redirect(url_for('admin.club_leaders', slug=slug))
    return render_template('admin/leader_form.html', form=form, club=club, title='Add Leader')


@admin_bp.route('/clubs/<slug>/leaders/<int:leader_id>/edit', methods=['GET', 'POST'])
@club_admin_required
def leader_edit(slug, leader_id):
    club = _get_club_or_404(slug)
    leader = ClubLeader.query.filter_by(id=leader_id, club_id=club.id).first_or_404()
    form = ClubLeaderForm(obj=leader)
    if form.validate_on_submit():
        leader.name          = form.name.data
        leader.bio           = form.bio.data or None
        leader.photo_url     = form.photo_url.data or None
        leader.display_order = form.display_order.data or 0
        db.session.commit()
        flash('Leader updated.', 'success')
        return redirect(url_for('admin.club_leaders', slug=slug))
    return render_template('admin/leader_form.html', form=form, club=club, title='Edit Leader')


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


@admin_bp.route('/clubs/<slug>/sponsors/new', methods=['GET', 'POST'])
@club_admin_required
def sponsor_new(slug):
    club = _get_club_or_404(slug)
    form = ClubSponsorForm()
    if form.validate_on_submit():
        db.session.add(ClubSponsor(
            club_id=club.id,
            name=form.name.data,
            logo_url=form.logo_url.data or None,
            website=form.website.data or None,
            display_order=form.display_order.data or 0,
        ))
        db.session.commit()
        flash('Sponsor added.', 'success')
        return redirect(url_for('admin.club_sponsors', slug=slug))
    return render_template('admin/sponsor_form.html', form=form, club=club, title='Add Sponsor')


@admin_bp.route('/clubs/<slug>/sponsors/<int:sponsor_id>/edit', methods=['GET', 'POST'])
@club_admin_required
def sponsor_edit(slug, sponsor_id):
    club = _get_club_or_404(slug)
    sponsor = ClubSponsor.query.filter_by(id=sponsor_id, club_id=club.id).first_or_404()
    form = ClubSponsorForm(obj=sponsor)
    if form.validate_on_submit():
        sponsor.name          = form.name.data
        sponsor.logo_url      = form.logo_url.data or None
        sponsor.website       = form.website.data or None
        sponsor.display_order = form.display_order.data or 0
        db.session.commit()
        flash('Sponsor updated.', 'success')
        return redirect(url_for('admin.club_sponsors', slug=slug))
    return render_template('admin/sponsor_form.html', form=form, club=club, title='Edit Sponsor')


@admin_bp.route('/clubs/<slug>/sponsors/<int:sponsor_id>/delete', methods=['POST'])
@club_admin_required
def sponsor_delete(slug, sponsor_id):
    club = _get_club_or_404(slug)
    sponsor = ClubSponsor.query.filter_by(id=sponsor_id, club_id=club.id).first_or_404()
    db.session.delete(sponsor)
    db.session.commit()
    flash('Sponsor removed.', 'info')
    return redirect(url_for('admin.club_sponsors', slug=slug))


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
