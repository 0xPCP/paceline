import secrets
from datetime import date, datetime, timezone
from urllib.parse import urlencode
from flask import Blueprint, render_template, redirect, url_for, flash, request, session, current_app
from flask_login import (
    login_user, logout_user, login_required, current_user,
    login_fresh, fresh_login_required,
)
from flask_babel import gettext as _, refresh as refresh_locale
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
import requests
from ..extensions import db, bcrypt, limiter
from ..models import (AdminAuditLog, AppErrorLog, BoardDigestItem, Club,
                      ClubAdmin, ClubBoardPost, ClubBoardReaction, ClubBoardReply,
                      ClubBoardSubscription, ClubInvite, ClubLeader, ClubMembership,
                      ClubMembershipPayment, ClubOwnershipTransfer, ClubPost,
                      PlatformPost, Ride, RideComment, RideMedia, RideSignup,
                      SiteFeedback, User, UserBike, UserEmailLog, UserRideInvite,
                      UserRecommendationHidden, WaiverSignature)
from ..forms import (
    AccountSetupForm, DisableMfaForm, MfaCodeForm, PasswordResetRequestForm, RegisterForm,
    LoginForm, ProfileForm, SetPasswordForm, UsernameSetupForm,
)
from ..email import send_password_reset_email
from ..email import DEFAULT_EMAIL_PREFERENCES, email_preferences_for
from ..geocoding import geocode_zip
from ..gear import GEAR_CATALOG
from ..mfa import generate_backup_codes, generate_totp_secret, totp_uri, verify_totp
from ..strava_profile import canonical_strava_profile_url, strava_profile_athlete_id
from ..utils import is_safe_url

auth_bp = Blueprint('auth', __name__)


def _mark_interactive_login(trusted_browser=False):
    session.permanent = True
    session['_paceline_auth_started_at'] = datetime.now(timezone.utc).timestamp()
    session['_paceline_trusted_browser'] = bool(trusted_browser)


def _clear_pending_mfa():
    session.pop('_pending_mfa_user_id', None)
    session.pop('_pending_mfa_trusted_browser', None)
    session.pop('_pending_mfa_next', None)


def _clean_mfa_code(code):
    return ''.join(ch for ch in str(code or '') if ch.isdigit())


def _hash_backup_codes(codes):
    return [bcrypt.generate_password_hash(code).decode('utf-8') for code in codes]


def _consume_backup_code(user, code):
    code = _clean_mfa_code(code)
    remaining = []
    matched = False
    for code_hash in user.mfa_backup_codes or []:
        if not matched and bcrypt.check_password_hash(code_hash, code):
            matched = True
            continue
        remaining.append(code_hash)
    if matched:
        user.mfa_backup_codes = remaining
    return matched


def _mfa_code_valid(user, code):
    clean_code = _clean_mfa_code(code)
    if user.mfa_secret and verify_totp(user.mfa_secret, clean_code):
        return True
    if len(clean_code) == 8 and _consume_backup_code(user, clean_code):
        return True
    return False


def _password_reset_serializer():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='paceline-password-reset')


def _delete_current_user_account(user):
    owned_clubs = Club.query.filter_by(owner_id=user.id).all()
    if owned_clubs:
        names = ', '.join(club.name for club in owned_clubs[:3])
        if len(owned_clubs) > 3:
            names += ', ...'
        return False, f'Transfer or delete clubs you own before deleting your account: {names}.'

    Ride.query.filter_by(leader_id=user.id).update({'leader_id': None}, synchronize_session=False)
    Ride.query.filter_by(created_by=user.id).update({'created_by': None}, synchronize_session=False)
    ClubMembership.query.filter_by(dues_confirmed_by_id=user.id).update({'dues_confirmed_by_id': None}, synchronize_session=False)
    ClubPost.query.filter_by(author_id=user.id).update({'author_id': None}, synchronize_session=False)
    ClubLeader.query.filter_by(user_id=user.id).update({'user_id': None}, synchronize_session=False)
    PlatformPost.query.filter_by(author_id=user.id).update({'author_id': None}, synchronize_session=False)
    BoardDigestItem.query.filter_by(actor_id=user.id).update({'actor_id': None}, synchronize_session=False)
    ClubInvite.query.filter_by(used_by_user_id=user.id).update({'used_by_user_id': None}, synchronize_session=False)
    AdminAuditLog.query.filter_by(actor_id=user.id).update({'actor_id': None}, synchronize_session=False)
    AdminAuditLog.query.filter_by(target_user_id=user.id).update({'target_user_id': None}, synchronize_session=False)
    SiteFeedback.query.filter_by(user_id=user.id).update({'user_id': None}, synchronize_session=False)
    SiteFeedback.query.filter_by(read_by_id=user.id).update({'read_by_id': None}, synchronize_session=False)
    AppErrorLog.query.filter_by(user_id=user.id).update({'user_id': None}, synchronize_session=False)

    for ride in Ride.query.filter_by(owner_id=user.id).all():
        db.session.delete(ride)
    ClubMembershipPayment.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    ClubOwnershipTransfer.query.filter(
        (ClubOwnershipTransfer.from_user_id == user.id) | (ClubOwnershipTransfer.to_user_id == user.id)
    ).delete(synchronize_session=False)
    RideSignup.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    RideMedia.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    RideComment.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    ClubMembership.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    ClubAdmin.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    WaiverSignature.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    UserRideInvite.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    ClubBoardSubscription.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    ClubBoardReaction.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    ClubBoardReply.query.filter_by(author_id=user.id).delete(synchronize_session=False)
    for post in ClubBoardPost.query.filter_by(author_id=user.id).all():
        BoardDigestItem.query.filter_by(post_id=post.id).delete(synchronize_session=False)
        db.session.delete(post)
    ClubInvite.query.filter_by(created_by=user.id).delete(synchronize_session=False)
    BoardDigestItem.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    UserEmailLog.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    UserRecommendationHidden.query.filter_by(user_id=user.id).delete(synchronize_session=False)

    db.session.delete(user)
    return True, 'Your account has been deleted.'


def _password_reset_payload(user):
    return {
        'user_id': user.id,
        'email': user.email,
        'session_token_version': user.session_token_version or 0,
        'password_hash': user.password_hash[-32:],
    }


def _password_reset_token(user):
    return _password_reset_serializer().dumps(_password_reset_payload(user))


def _user_from_password_reset_token(token):
    max_age = current_app.config.get('PASSWORD_RESET_MAX_AGE_SECONDS', 3600)
    data = _password_reset_serializer().loads(token, max_age=max_age)
    user = db.session.get(User, data.get('user_id'))
    if not user or not user.is_active:
        raise BadSignature('Invalid user')
    expected = _password_reset_payload(user)
    if data != expected:
        raise BadSignature('Token does not match current account state')
    return user


def _send_password_reset(user):
    token = _password_reset_token(user)
    reset_url = url_for('auth.password_reset', token=token, _external=True)
    send_password_reset_email(user, reset_url)


def _google_oauth_configured():
    return bool(
        current_app.config.get('GOOGLE_OAUTH_CLIENT_ID')
        and current_app.config.get('GOOGLE_OAUTH_CLIENT_SECRET')
    )


def _google_redirect_uri():
    return url_for('auth.google_callback', _external=True)


def _temporary_google_username():
    while True:
        candidate = f'google-{secrets.token_hex(8)}'
        if not User.query.filter_by(username=candidate).first():
            return candidate


def _google_userinfo(code):
    token_response = requests.post(
        current_app.config.get('GOOGLE_OAUTH_TOKEN_URL', 'https://oauth2.googleapis.com/token'),
        data={
            'code': code,
            'client_id': current_app.config['GOOGLE_OAUTH_CLIENT_ID'],
            'client_secret': current_app.config['GOOGLE_OAUTH_CLIENT_SECRET'],
            'redirect_uri': _google_redirect_uri(),
            'grant_type': 'authorization_code',
        },
        timeout=10,
    )
    token_response.raise_for_status()
    access_token = token_response.json().get('access_token')
    if not access_token:
        raise ValueError('Google did not return an access token.')
    userinfo_response = requests.get(
        current_app.config.get('GOOGLE_OAUTH_USERINFO_URL', 'https://openidconnect.googleapis.com/v1/userinfo'),
        headers={'Authorization': f'Bearer {access_token}'},
        timeout=10,
    )
    userinfo_response.raise_for_status()
    return userinfo_response.json()


def _user_from_google_profile(profile):
    google_sub = profile.get('sub')
    email = (profile.get('email') or '').strip().lower()
    email_verified = profile.get('email_verified') is True or profile.get('email_verified') == 'true'
    if not google_sub or not email or not email_verified:
        raise ValueError('Google account must include a verified email address.')

    linked_user = User.query.filter_by(google_sub=google_sub).first()
    if linked_user:
        return linked_user

    user = User.query.filter_by(email=email).first()
    if user:
        user.google_sub = google_sub
        return user

    superadmin_emails = {
        address.strip().lower()
        for address in current_app.config.get('SUPERADMIN_EMAILS', '').split(',')
        if address.strip()
    }
    user = User(
        username=_temporary_google_username(),
        username_finalized=False,
        email=email,
        google_sub=google_sub,
        password_hash=bcrypt.generate_password_hash(secrets.token_urlsafe(32)).decode('utf-8'),
        is_admin=User.query.count() == 0 or email in superadmin_emails,
        is_active=True,
    )
    db.session.add(user)
    return user


@auth_bp.route('/register', methods=['GET', 'POST'])
@limiter.limit('5 per minute; 20 per hour')
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    form = RegisterForm()
    if form.validate_on_submit():
        # Check for existing email or username
        if User.query.filter_by(email=form.email.data.lower()).first():
            flash(_('An account with that email already exists.'), 'danger')
            return render_template('auth/register.html', form=form)
        if User.query.filter_by(username=form.username.data).first():
            flash(_('That username is already taken.'), 'danger')
            return render_template('auth/register.html', form=form)

        hashed = bcrypt.generate_password_hash(form.password.data).decode('utf-8')
        # First registered user becomes admin
        superadmin_emails = {
            email.strip().lower()
            for email in current_app.config.get('SUPERADMIN_EMAILS', '').split(',')
            if email.strip()
        }
        is_first_user = User.query.count() == 0
        is_configured_superadmin = form.email.data.lower() in superadmin_emails
        user = User(
            username=form.username.data,
            username_finalized=True,
            email=form.email.data.lower(),
            password_hash=hashed,
            is_admin=is_first_user or is_configured_superadmin,
        )
        db.session.add(user)
        db.session.commit()

        login_user(user)
        _mark_interactive_login()
        if is_first_user:
            flash(_('Account created — you have been granted admin access as the first user.'), 'success')
        else:
            flash(_('Welcome! Your account has been created.'), 'success')
        next_page = request.args.get('next')
        if next_page and is_safe_url(next_page):
            return redirect(next_page)
        return redirect(url_for('main.index'))

    return render_template('auth/register.html', form=form)


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit('20 per minute; 100 per hour')
def login():
    if current_user.is_authenticated and login_fresh():
        return redirect(url_for('main.index'))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower()).first()
        if user and bcrypt.check_password_hash(user.password_hash, form.password.data):
            if not user.is_active:
                flash(_('This account has been deactivated. Please contact support.'), 'danger')
                return render_template('auth/login.html', form=form)
            trusted_browser = bool(form.remember.data)
            if user.mfa_enabled:
                session['_pending_mfa_user_id'] = user.id
                session['_pending_mfa_trusted_browser'] = trusted_browser
                next_page = request.args.get('next')
                if next_page and is_safe_url(next_page):
                    session['_pending_mfa_next'] = next_page
                return redirect(url_for('auth.mfa_verify'))
            login_user(user, remember=trusted_browser)
            _mark_interactive_login(trusted_browser=trusted_browser)
            next_page = request.args.get('next')
            if next_page and is_safe_url(next_page):
                return redirect(next_page)
            return redirect(url_for('main.index'))
        flash(_('Invalid email or password.'), 'danger')

    return render_template('auth/login.html', form=form)


@auth_bp.route('/password-reset', methods=['GET', 'POST'])
@limiter.limit('5 per minute; 10 per hour')
def password_reset_request():
    if current_user.is_authenticated and login_fresh():
        return redirect(url_for('auth.profile'))

    form = PasswordResetRequestForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower()).first()
        if user and user.is_active:
            _send_password_reset(user)
        flash('If that email is on a Paceline account, a password reset link has been sent.', 'info')
        return redirect(url_for('auth.login'))

    return render_template('auth/password_reset_request.html', form=form)


@auth_bp.route('/password-reset/request-profile', methods=['POST'])
@fresh_login_required
def password_reset_profile_request():
    _send_password_reset(current_user)
    flash('We sent a password setup/reset link to your account email.', 'success')
    return redirect(url_for('auth.profile'))


@auth_bp.route('/password-reset/<token>', methods=['GET', 'POST'])
def password_reset(token):
    try:
        user = _user_from_password_reset_token(token)
    except SignatureExpired:
        flash('That password reset link has expired. Request a new one.', 'danger')
        return redirect(url_for('auth.password_reset_request'))
    except BadSignature:
        flash('That password reset link is invalid or has already been used.', 'danger')
        return redirect(url_for('auth.password_reset_request'))

    form = SetPasswordForm()
    if form.validate_on_submit():
        user.password_hash = bcrypt.generate_password_hash(form.password.data).decode('utf-8')
        user.revoke_sessions()
        db.session.commit()
        if current_user.is_authenticated:
            logout_user()
            session.pop('_paceline_auth_started_at', None)
            session.pop('_paceline_trusted_browser', None)
        flash('Password updated. Please sign in with your new password.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/password_reset.html', form=form, token=token, user=user)


@auth_bp.route('/google')
def google_login():
    if current_user.is_authenticated and login_fresh():
        return redirect(url_for('main.index'))
    if not _google_oauth_configured():
        flash('Google sign-in is not configured yet.', 'warning')
        return redirect(url_for('auth.login'))

    state = secrets.token_urlsafe(32)
    session['_google_oauth_state'] = state
    next_page = request.args.get('next')
    if next_page and is_safe_url(next_page):
        session['_google_oauth_next'] = next_page

    params = {
        'client_id': current_app.config['GOOGLE_OAUTH_CLIENT_ID'],
        'redirect_uri': _google_redirect_uri(),
        'response_type': 'code',
        'scope': 'openid email profile',
        'state': state,
        'prompt': 'select_account',
    }
    auth_url = current_app.config.get('GOOGLE_OAUTH_AUTH_URL', 'https://accounts.google.com/o/oauth2/v2/auth')
    return redirect(f"{auth_url}?{urlencode(params)}")


@auth_bp.route('/google/callback')
def google_callback():
    expected_state = session.pop('_google_oauth_state', None)
    next_page = session.pop('_google_oauth_next', None)
    state = request.args.get('state')
    code = request.args.get('code')
    if not expected_state or not state or not secrets.compare_digest(expected_state, state):
        flash('Google sign-in could not be verified. Please try again.', 'danger')
        return redirect(url_for('auth.login'))
    if not code:
        flash('Google sign-in was cancelled or did not return an authorization code.', 'warning')
        return redirect(url_for('auth.login'))

    try:
        profile = _google_userinfo(code)
        user = _user_from_google_profile(profile)
        if not user.is_active:
            db.session.rollback()
            flash(_('This account has been deactivated. Please contact support.'), 'danger')
            return redirect(url_for('auth.login'))
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Google OAuth sign-in failed')
        flash('Google sign-in failed. Please try again.', 'danger')
        return redirect(url_for('auth.login'))

    login_user(user, remember=False)
    _mark_interactive_login(trusted_browser=False)
    if not user.username_finalized:
        return redirect(url_for('auth.username_setup'))
    if next_page and is_safe_url(next_page):
        return redirect(next_page)
    return redirect(url_for('main.index'))


@auth_bp.route('/username', methods=['GET', 'POST'])
@fresh_login_required
def username_setup():
    if current_user.username_finalized:
        return redirect(url_for('main.index'))

    form = UsernameSetupForm()
    if form.validate_on_submit():
        username = form.username.data.strip()
        existing = User.query.filter(User.username == username, User.id != current_user.id).first()
        if existing:
            flash('That username is already taken.', 'danger')
            return render_template('auth/username_setup.html', form=form)
        current_user.username = username
        current_user.username_finalized = True
        db.session.commit()
        flash('Username saved.', 'success')
        return redirect(url_for('main.index'))

    return render_template('auth/username_setup.html', form=form)


@auth_bp.route('/mfa', methods=['GET', 'POST'])
@limiter.limit('5 per minute; 20 per hour')
def mfa_verify():
    user_id = session.get('_pending_mfa_user_id')
    if not user_id:
        return redirect(url_for('auth.login'))
    user = db.session.get(User, user_id)
    if user is None or not user.is_active or not user.mfa_enabled:
        _clear_pending_mfa()
        flash(_('Please sign in again.'), 'info')
        return redirect(url_for('auth.login'))

    form = MfaCodeForm()
    if form.validate_on_submit():
        if _mfa_code_valid(user, form.code.data):
            trusted_browser = bool(session.get('_pending_mfa_trusted_browser'))
            next_page = session.get('_pending_mfa_next')
            _clear_pending_mfa()
            db.session.commit()
            login_user(user, remember=trusted_browser)
            _mark_interactive_login(trusted_browser=trusted_browser)
            if next_page and is_safe_url(next_page):
                return redirect(next_page)
            return redirect(url_for('main.index'))
        db.session.rollback()
        flash(_('Invalid authentication code.'), 'danger')

    return render_template('auth/mfa_verify.html', form=form)


@auth_bp.route('/setup-account/<token>', methods=['GET', 'POST'])
def setup_account(token):
    """Password-setup landing page for users created via bulk import."""
    invite = ClubInvite.query.filter_by(token=token, is_new_user=True).first_or_404()

    if invite.used_at:
        flash('This setup link has already been used. Please sign in.', 'warning')
        return redirect(url_for('auth.login'))
    if invite.expires_at.replace(tzinfo=None) < datetime.now(timezone.utc).replace(tzinfo=None):
        flash('This setup link has expired. Ask your club admin to re-import your email.', 'danger')
        return redirect(url_for('auth.login'))

    user = User.query.filter_by(email=invite.email).first_or_404()

    # Already logged in as the right user — just mark done and send to club
    if current_user.is_authenticated:
        if current_user.id != user.id:
            flash('This setup link belongs to a different account.', 'warning')
            return redirect(url_for('main.index'))
        invite.used_at = datetime.now(timezone.utc)
        invite.used_by_user_id = user.id
        db.session.commit()
        return redirect(url_for('clubs.home', slug=invite.club.slug))

    form = AccountSetupForm()
    if form.validate_on_submit():
        user.password_hash = bcrypt.generate_password_hash(
            form.password.data
        ).decode('utf-8')
        user.revoke_sessions()
        invite.used_at = datetime.now(timezone.utc)
        invite.used_by_user_id = user.id
        db.session.commit()
        login_user(user)
        _mark_interactive_login()
        flash(f"Welcome to {invite.club.name}! Your Paceline account is ready.", 'success')
        return redirect(url_for('clubs.home', slug=invite.club.slug))

    return render_template('auth/setup_account.html', form=form, invite=invite)


@auth_bp.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    session.pop('_paceline_auth_started_at', None)
    session.pop('_paceline_trusted_browser', None)
    session.pop('_google_oauth_state', None)
    session.pop('_google_oauth_next', None)
    _clear_pending_mfa()
    return redirect(url_for('main.index'))


@auth_bp.route('/profile', methods=['GET', 'POST'])
@fresh_login_required
def profile():
    form = ProfileForm(obj=current_user)
    pref_fields = {
        'ride_cancellations': 'notify_ride_cancellations',
        'ride_reminders': 'notify_ride_reminders',
        'ride_waitlist': 'notify_ride_waitlist',
        'ride_updates': 'notify_ride_updates',
        'membership_updates': 'notify_membership_updates',
        'club_new_rides': 'notify_club_new_rides',
        'club_news': 'notify_club_news',
        'weekly_digest': 'notify_weekly_digest',
        'board_digest': 'notify_board_digest',
        'friend_ride_signup': 'notify_friend_ride_signup',
    }
    if request.method == 'GET':
        form.profile_is_public.data = current_user.profile_is_public
        form.recommendations_enabled.data = current_user.recommendations_enabled
        form.recommendation_location_enabled.data = current_user.recommendation_location_enabled
        form.recommendation_history_enabled.data = current_user.recommendation_history_enabled
        form.recommendation_friend_activity_enabled.data = current_user.recommendation_friend_activity_enabled
        form.dashboard_recommendations_hidden.data = current_user.dashboard_recommendations_hidden
        prefs = email_preferences_for(current_user)
        for key, field_name in pref_fields.items():
            getattr(form, field_name).data = prefs.get(key, DEFAULT_EMAIL_PREFERENCES.get(key, True))
    if form.validate_on_submit():
        email_changed = False
        if form.email.data.lower() != current_user.email:
            if User.query.filter_by(email=form.email.data.lower()).first():
                flash(_('An account with that email already exists.'), 'danger')
                return redirect(url_for('auth.profile'))
            email_changed = True

        old_email = current_user.email
        current_user.email     = form.email.data.lower()
        current_user.gender    = form.gender.data or None
        current_user.bio       = (form.bio.data or '').strip() or None
        strava_profile_url = canonical_strava_profile_url(form.strava_profile_url.data)
        if strava_profile_url and current_user.strava_id:
            athlete_id = strava_profile_athlete_id(strava_profile_url)
            if athlete_id != current_user.strava_id:
                flash('That Strava profile URL does not match the Strava account connected to your profile.', 'danger')
                return redirect(url_for('auth.profile'))
        current_user.strava_profile_url = strava_profile_url
        current_user.language      = form.language.data or None
        current_user.distance_unit = form.distance_unit.data or None
        current_user.emergency_contact_name  = (form.emergency_contact_name.data or '').strip() or None
        current_user.emergency_contact_phone = (form.emergency_contact_phone.data or '').strip() or None
        current_user.profile_is_public = bool(form.profile_is_public.data)
        current_user.recommendations_enabled = bool(form.recommendations_enabled.data)
        current_user.recommendation_location_enabled = bool(form.recommendation_location_enabled.data)
        current_user.recommendation_history_enabled = bool(form.recommendation_history_enabled.data)
        current_user.recommendation_friend_activity_enabled = bool(form.recommendation_friend_activity_enabled.data)
        current_user.dashboard_recommendations_hidden = bool(form.dashboard_recommendations_hidden.data)
        valid_ride_types = {'road', 'gravel', 'social', 'training', 'event', 'night', 'virtual'}
        selected_ride_types = [v for v in request.form.getlist('recommendation_ride_types') if v in valid_ride_types]
        current_user.recommendation_ride_types = selected_ride_types or None
        current_user.email_preferences = {
            key: bool(getattr(form, field_name).data)
            for key, field_name in pref_fields.items()
        }

        # Gear inventory — validate each submitted ID against the known catalog
        valid_gear_ids = {item['id'] for items in GEAR_CATALOG.values() for item in items}
        submitted_gear = [g for g in request.form.getlist('gear_items') if g in valid_gear_ids]
        current_user.gear_inventory = submitted_gear or None

        new_zip = (form.zip_code.data or '').strip()
        if new_zip != (current_user.zip_code or ''):
            current_user.zip_code = new_zip or None
            current_user.lat = None
            current_user.lng = None
            if new_zip:
                coords = geocode_zip(new_zip)
                if coords:
                    current_user.lat, current_user.lng = coords
                else:
                    flash(_('Zip code saved but could not be geocoded.'), 'warning')

        if email_changed:
            db.session.add(AdminAuditLog(
                actor_id=current_user.id,
                target_user_id=current_user.id,
                action='email_changed',
                details=f'Changed from {old_email} to {current_user.email}',
            ))
            current_user.revoke_sessions()
        db.session.commit()
        if email_changed:
            login_user(current_user)
            _mark_interactive_login()
        refresh_locale()
        flash(_('Profile updated.'), 'success')
        return redirect(url_for('auth.profile'))

    owned = set(current_user.gear_inventory or [])
    today = date.today()
    past_signups = (RideSignup.query
                    .filter_by(user_id=current_user.id, is_waitlist=False)
                    .join(Ride, RideSignup.ride_id == Ride.id)
                    .filter(Ride.date < today, Ride.is_cancelled == False)
                    .order_by(Ride.date.desc())
                    .all())
    ytd_signups = [s for s in past_signups if s.ride.date.year == today.year]
    ytd_stats = {
        'rides':     len(ytd_signups),
        'miles':     round(sum(s.ride.distance_miles for s in ytd_signups), 1),
        'elevation': sum(s.ride.elevation_feet or 0 for s in ytd_signups),
    }
    return render_template('profile.html', form=form,
                           disable_mfa_form=DisableMfaForm(),
                           gear_catalog=GEAR_CATALOG, owned_gear=owned,
                           past_signups=past_signups, ytd_stats=ytd_stats,
                           recommendation_ride_types=[
                               ('road', 'Road'),
                               ('gravel', 'Gravel'),
                               ('social', 'Social'),
                               ('training', 'Training'),
                               ('event', 'Event'),
                               ('night', 'Night'),
                               ('virtual', 'Virtual'),
                           ],
                           selected_recommendation_ride_types=set(current_user.recommendation_ride_types or []))


@auth_bp.route('/profile/photo', methods=['POST'])
@login_required
def profile_photo_upload():
    import io
    from PIL import Image
    from ..storage import get_storage

    is_xhr = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    def _err(msg, status=400):
        if is_xhr:
            from flask import jsonify
            return jsonify({'ok': False, 'error': msg}), status
        flash(msg, 'danger')
        return redirect(url_for('auth.profile'))

    f = request.files.get('photo')
    if not f or not f.filename:
        return _err('No file selected.')

    raw = f.stream.read()
    if len(raw) > 8 * 1024 * 1024:
        return _err('Photo must be under 8 MB.')

    try:
        img = Image.open(io.BytesIO(raw)).convert('RGB')
    except Exception:
        return _err('Could not read image file.')

    # Resize to 400×400 square — client already sends a square crop
    img = img.resize((400, 400), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=85, optimize=True)
    jpeg_bytes = buf.getvalue()

    key = f'avatars/{current_user.id}.jpg'
    storage = get_storage()
    try:
        # Public-read so the avatar can be served via CDN/public URL
        storage.save(key, jpeg_bytes, acl='public-read')
    except Exception as exc:
        current_app.logger.error('Avatar upload failed for user %s: %s', current_user.id, exc)
        return _err('Photo upload failed. Please try again.', 500)

    current_user.profile_photo_key = key
    db.session.commit()

    if is_xhr:
        from flask import jsonify
        photo_url = url_for('main.profile_photo', username=current_user.username,
                            _t=int(__import__('time').time()), _external=False)
        return jsonify({'ok': True, 'url': photo_url})

    flash('Profile photo updated.', 'success')
    return redirect(url_for('auth.profile'))


@auth_bp.route('/profile/photo/delete', methods=['POST'])
@login_required
def profile_photo_delete():
    from ..storage import get_storage
    if current_user.profile_photo_key:
        get_storage().delete(current_user.profile_photo_key)
        current_user.profile_photo_key = None
        db.session.commit()
        flash('Profile photo removed.', 'info')
    return redirect(url_for('auth.profile'))


@auth_bp.route('/profile/bikes', methods=['POST'])
@login_required
def add_bike():
    make_model = (request.form.get('make_model') or '').strip()
    if not make_model:
        flash('Make/model is required.', 'danger')
        return redirect(url_for('auth.profile') + '#bikes')

    bike_type = request.form.get('bike_type', 'road')
    if bike_type not in UserBike.BIKE_TYPES:
        bike_type = 'other'

    nickname = (request.form.get('nickname') or '').strip() or None
    is_primary = request.form.get('is_primary') == '1'

    if is_primary:
        # Clear existing primary flag
        for b in current_user.bikes:
            b.is_primary = False

    order = len(current_user.bikes)
    bike = UserBike(user_id=current_user.id, make_model=make_model,
                    nickname=nickname, bike_type=bike_type,
                    is_primary=is_primary, display_order=order)
    db.session.add(bike)
    db.session.commit()
    flash(f'Added {make_model}.', 'success')
    return redirect(url_for('auth.profile') + '#bikes')


@auth_bp.route('/profile/bikes/<int:bike_id>/delete', methods=['POST'])
@login_required
def delete_bike(bike_id):
    bike = UserBike.query.filter_by(id=bike_id, user_id=current_user.id).first_or_404()
    db.session.delete(bike)
    db.session.commit()
    flash('Bike removed.', 'info')
    return redirect(url_for('auth.profile') + '#bikes')


@auth_bp.route('/profile/delete-account', methods=['POST'])
@fresh_login_required
def delete_account():
    confirmation = (request.form.get('confirmation') or '').strip()
    expected = f'DELETE {current_user.email}'
    if confirmation != expected:
        flash(f'Type "{expected}" to permanently delete your account.', 'danger')
        return redirect(url_for('auth.profile'))

    user = db.session.get(User, current_user.id)
    ok, message = _delete_current_user_account(user)
    if not ok:
        flash(message, 'danger')
        return redirect(url_for('auth.profile'))

    logout_user()
    session.clear()
    db.session.commit()
    flash(message, 'success')
    return redirect(url_for('main.index'))


@auth_bp.route('/mfa/setup', methods=['GET', 'POST'])
@fresh_login_required
def mfa_setup():
    if current_user.mfa_enabled:
        flash('MFA is already enabled for your account.', 'info')
        return redirect(url_for('auth.profile'))

    secret = session.get('_mfa_setup_secret')
    if not secret:
        secret = generate_totp_secret()
        session['_mfa_setup_secret'] = secret

    form = MfaCodeForm()
    if form.validate_on_submit():
        if verify_totp(secret, form.code.data):
            backup_codes = generate_backup_codes()
            current_user.mfa_secret = secret
            current_user.mfa_backup_codes = _hash_backup_codes(backup_codes)
            current_user.mfa_enabled = True
            current_user.revoke_sessions()
            db.session.add(AdminAuditLog(
                actor_id=current_user.id,
                target_user_id=current_user.id,
                action='mfa_enabled',
            ))
            db.session.commit()
            session.pop('_mfa_setup_secret', None)
            login_user(current_user)
            _mark_interactive_login()
            return render_template('auth/mfa_backup_codes.html', backup_codes=backup_codes)
        flash('Invalid authentication code. Check the code in your authenticator app and try again.', 'danger')

    return render_template(
        'auth/mfa_setup.html',
        form=form,
        secret=secret,
        otpauth_uri=totp_uri(secret, current_user.email),
    )


@auth_bp.route('/mfa/disable', methods=['POST'])
@fresh_login_required
def mfa_disable():
    form = DisableMfaForm()
    if not form.validate_on_submit():
        flash('Enter your password to disable MFA.', 'danger')
        return redirect(url_for('auth.profile'))
    if not bcrypt.check_password_hash(current_user.password_hash, form.password.data):
        flash('Password did not match. MFA was not changed.', 'danger')
        return redirect(url_for('auth.profile'))

    current_user.mfa_enabled = False
    current_user.mfa_secret = None
    current_user.mfa_backup_codes = None
    current_user.revoke_sessions()
    db.session.add(AdminAuditLog(
        actor_id=current_user.id,
        target_user_id=current_user.id,
        action='mfa_disabled',
    ))
    db.session.commit()
    login_user(current_user)
    _mark_interactive_login()
    flash('MFA disabled.', 'success')
    return redirect(url_for('auth.profile'))
