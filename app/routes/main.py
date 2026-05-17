from datetime import date, timedelta
from urllib.parse import urlparse
from flask import Blueprint, render_template, request, redirect, url_for, current_app, flash, jsonify
from flask_login import current_user, login_required
from sqlalchemy import or_, and_, text
from ..forms import FeedbackForm
from ..models import Club, Ride, RideSignup, ClubMembership, PlatformPost, SiteFeedback, User, UserFriend
from ..storage import get_storage
from ..extensions import db
from ..email import send_feedback_notification
from ..weather import get_weather_for_rides
from ..geocoding import geocode_zip, haversine_miles

main_bp = Blueprint('main', __name__)


@main_bp.route('/health')
def health():
    """Liveness probe — bypasses beta gate, checks DB connectivity."""
    try:
        db.session.execute(text('SELECT 1'))
        return jsonify(status='ok'), 200
    except Exception as e:
        current_app.logger.error('Health check DB failure: %s', e)
        return jsonify(status='error', detail=str(e)), 503


@main_bp.route('/')
def index():
    today = date.today()
    platform_posts = _published_platform_posts(limit=3)

    if current_user.is_authenticated:
        return _user_dashboard(today, platform_posts)

    # Landing page for logged-out visitors: show club directory teaser
    clubs = _homepage_featured_clubs()
    return render_template('index.html', clubs=clubs, today=today, platform_posts=platform_posts)


def _homepage_featured_clubs(limit=10):
    visible = Club.query.filter_by(is_active=True, is_hidden=False)
    featured = (visible
                .filter_by(is_featured=True)
                .order_by(Club.featured_rank.is_(None), Club.featured_rank.asc(), Club.name.asc())
                .limit(limit)
                .all())
    if len(featured) >= limit:
        return featured
    return visible.order_by(Club.name.asc()).limit(limit).all()


def _published_platform_posts(limit=None):
    query = (PlatformPost.query
             .filter_by(is_published=True)
             .order_by(PlatformPost.published_at.desc(), PlatformPost.id.desc()))
    if limit:
        query = query.limit(limit)
    return query.all()


def _user_dashboard(today, platform_posts=None):
    """Home screen for logged-in users: upcoming rides across all subscribed clubs."""
    # Clubs the user has joined (active memberships)
    memberships = (ClubMembership.query
                   .filter_by(user_id=current_user.id)
                   .all())
    club_ids = [m.club_id for m in memberships]
    active_club_ids = [m.club_id for m in memberships if m.status == 'active']
    my_clubs = (Club.query
                .filter(Club.id.in_(active_club_ids))
                .order_by(Club.name.asc())
                .all()) if active_club_ids else []

    # Rides the user is signed up for (upcoming only), across any club
    signed_up_ride_ids = set(
        s.ride_id for s in RideSignup.query.filter_by(user_id=current_user.id).all()
    )
    my_rides = (Ride.query
                .filter(Ride.id.in_(signed_up_ride_ids),
                        Ride.date >= today,
                        Ride.is_cancelled == False)
                .order_by(Ride.date.asc(), Ride.time.asc())
                .all()) if signed_up_ride_ids else []

    # Upcoming rides from subscribed clubs (not already signed up), next 14 days
    upcoming_club_rides = []
    if club_ids:
        upcoming_club_rides = (Ride.query
                               .filter(Ride.club_id.in_(club_ids),
                                       Ride.date >= today,
                                       Ride.is_cancelled == False,
                                       ~Ride.id.in_(signed_up_ride_ids))
                               .order_by(Ride.date.asc(), Ride.time.asc())
                               .limit(10).all())

    # Friends' upcoming rides (rides their accepted friends signed up for that this user can see)
    friends_rides = _friends_upcoming_rides(
        current_user, today, signed_up_ride_ids, club_ids
    )

    all_display_rides = list({r.id: r for r in my_rides + upcoming_club_rides
                              + [r for _, r in friends_rides]}.values())
    weather = get_weather_for_rides(all_display_rides)

    # Clubs user hasn't joined yet (for discovery)
    joined_ids = set(club_ids)
    suggested_clubs = (Club.query
                       .filter_by(is_active=True, is_hidden=False)
                       .filter(~Club.id.in_(joined_ids))
                       .order_by(Club.name.asc())
                       .limit(4).all()) if True else []

    # Pre-compute signup eligibility per club (avoids N+1 queries in the template)
    signup_eligible = {}
    seen_club_ids = set()
    for ride in upcoming_club_rides:
        if ride.club_id and ride.club_id not in seen_club_ids:
            seen_club_ids.add(ride.club_id)
            club = ride.club
            signup_eligible[ride.club_id] = {
                'dues_ok': current_user.is_active_member_of(club),
                'waiver_ok': current_user.has_signed_waiver(club),
            }

    # Pending friend requests addressed to the current user
    pending_friend_requests = (
        UserFriend.query
        .filter_by(addressee_id=current_user.id, status='pending')
        .all()
    )

    return render_template('dashboard.html',
                           my_rides=my_rides,
                           upcoming_club_rides=upcoming_club_rides,
                           friends_rides=friends_rides,
                           weather=weather,
                           today=today,
                           my_clubs=my_clubs,
                           suggested_clubs=suggested_clubs,
                           signed_up_ride_ids=signed_up_ride_ids,
                           signup_eligible=signup_eligible,
                           platform_posts=platform_posts or [],
                           pending_friend_requests=pending_friend_requests)


def _friends_upcoming_rides(viewer, today, viewer_signup_ids, viewer_club_ids):
    """Return up to 10 (friend_user, ride) pairs for upcoming rides friends have signed up for.

    Visibility rules:
    - Virtual rides: always visible
    - Personal public rides (owner_id, no club_id): visible if is_private=False
    - Club rides: visible if club is not private, OR viewer is a member of that club
    """
    friend_ids = viewer.accepted_friend_ids()
    if not friend_ids:
        return []

    viewer_club_set = set(viewer_club_ids)
    friend_signups = (
        RideSignup.query
        .filter(
            RideSignup.user_id.in_(friend_ids),
            RideSignup.is_waitlist == False,   # noqa: E712
            RideSignup.is_anonymous == False,  # noqa: E712
        )
        .join(Ride, RideSignup.ride_id == Ride.id)
        .filter(
            Ride.date >= today,
            Ride.is_cancelled == False,        # noqa: E712
            ~Ride.id.in_(viewer_signup_ids),
        )
        .order_by(Ride.date.asc(), Ride.time.asc())
        .limit(50)
        .all()
    )

    result = []
    seen_ride_ids = set()
    for signup in friend_signups:
        ride = signup.ride
        if ride.id in seen_ride_ids:
            continue
        if ride.is_virtual:
            pass  # always visible
        elif ride.owner_id and not ride.club_id:
            if ride.is_private:
                continue
        elif ride.club_id:
            club = ride.club
            if club.is_private and ride.club_id not in viewer_club_set:
                continue
        else:
            continue
        result.append((User.query.get(signup.user_id), ride))
        seen_ride_ids.add(ride.id)
        if len(result) >= 10:
            break

    return result


@main_bp.route('/news/')
def platform_news():
    posts = _published_platform_posts()
    return render_template('news/index.html', posts=posts)


@main_bp.route('/news/<int:post_id>')
def platform_news_detail(post_id):
    post = PlatformPost.query.filter_by(id=post_id, is_published=True).first_or_404()
    return render_template('news/detail.html', post=post)


@main_bp.route('/set-language/<lang>')
def set_language(lang):
    flash('Language can be changed from your profile. Signed-out visitors use their browser language preference.', 'info')
    target = url_for('auth.profile') if current_user.is_authenticated else url_for('main.index')
    return redirect(target)


@main_bp.route('/about')
def about():
    return render_template('about.html')


@main_bp.route('/privacy')
def privacy():
    return render_template('privacy.html')


@main_bp.route('/data-use')
def data_use():
    return render_template('data_use.html')


@main_bp.route('/donate')
def donate():
    donate_url = (current_app.config.get('DONATE_URL') or '').strip()
    parsed = urlparse(donate_url)
    if not (donate_url and parsed.scheme in ('http', 'https') and parsed.netloc):
        donate_url = ''
    form = FeedbackForm()
    if current_user.is_authenticated:
        form.name.data = form.name.data or current_user.username
        form.email.data = form.email.data or current_user.email
    return render_template('donate.html', feedback_form=form, donate_url=donate_url)


@main_bp.route('/feedback', methods=['POST'])
def submit_feedback():
    form = FeedbackForm()
    if form.validate_on_submit():
        feedback = SiteFeedback(
            user_id=current_user.id if current_user.is_authenticated else None,
            name=(form.name.data or '').strip() or None,
            email=(form.email.data or '').strip().lower() or None,
            message=form.message.data.strip(),
            source=request.form.get('source', 'donate')[:80],
        )
        db.session.add(feedback)
        db.session.commit()
        send_feedback_notification(feedback)
        flash('Thanks for the feedback. I will review it soon.', 'success')
        return redirect(url_for('main.donate') + '#feedback')
    flash('Please enter a valid message before sending feedback.', 'danger')
    return redirect(url_for('main.donate') + '#feedback')


@main_bp.route('/help/')
def help_index():
    return render_template('help/index.html')


@main_bp.route('/help/club-managers')
def help_club_managers():
    return render_template('help/club_managers.html')


@main_bp.route('/help/riders')
def help_riders():
    return render_template('help/riders.html')


@main_bp.route('/users/<username>/photo')
def profile_photo(username):
    """Serve a user's profile photo from Spaces (or 404 if none)."""
    from flask import abort
    user = User.query.filter_by(username=username).first_or_404()
    if not user.profile_photo_key:
        abort(404)
    return get_storage().serve(user.profile_photo_key, is_private=False)


@main_bp.route('/users/<username>')
@login_required
def public_profile(username):
    profile_user = User.query.filter_by(username=username).first_or_404()
    today = date.today()
    public_signups = (RideSignup.query
                      .filter_by(user_id=profile_user.id, is_waitlist=False, is_anonymous=False)
                      .join(Ride, RideSignup.ride_id == Ride.id)
                      .filter(Ride.date < today, Ride.is_cancelled == False)
                      .order_by(Ride.date.desc())
                      .limit(15)
                      .all())
    friend_status = None
    friend_row = None
    friends_rides = []
    is_own_profile = (profile_user.id == current_user.id)

    if is_own_profile:
        signed_up_ids = {s.ride_id for s in RideSignup.query.filter_by(user_id=current_user.id).all()}
        viewer_club_ids = [m.club_id for m in current_user.club_memberships if m.status == 'active']
        friends_rides = _friends_upcoming_rides(current_user, today, signed_up_ids, viewer_club_ids)
    else:
        friend_row = current_user.friend_request_row(profile_user)
        friend_status = current_user.friend_status(profile_user)

    # Privacy gate: private profiles are visible only to the user and accepted friends
    is_private = not profile_user.profile_is_public
    can_view = (
        is_own_profile
        or current_user.is_admin
        or not is_private
        or friend_status == 'accepted'
    )

    return render_template('public_profile.html',
                           profile_user=profile_user,
                           public_signups=public_signups if can_view else [],
                           friend_status=friend_status,
                           friend_row=friend_row,
                           friends_rides=friends_rides,
                           is_own_profile=is_own_profile,
                           can_view=can_view)


@main_bp.route('/discover/')
def discover():
    today = date.today()

    # Source: which rides to show
    # 'verified' = only verified clubs (default)
    # 'clubs'    = all active clubs (verified + unverified)
    # 'all'      = clubs + personal public rides
    source = request.args.get('source', 'verified')
    if source not in ('verified', 'clubs', 'all'):
        source = 'verified'

    pace       = request.args.get('pace', '')
    ride_type  = request.args.get('type', '')
    date_range = request.args.get('range', 'week')

    # Location — either lat/lng (from geolocation) or zip code
    lat_arg = request.args.get('lat', type=float)
    lng_arg = request.args.get('lng', type=float)
    zip_q   = request.args.get('zip', '').strip()
    radius  = request.args.get('radius', 25, type=int)
    if radius not in (10, 25, 50, 100):
        radius = 25

    # Date window
    if date_range == 'weekend':
        sat = today + timedelta(days=(5 - today.weekday()) % 7 or 7)
        start_date = sat
        end_date   = sat + timedelta(days=1)
    elif date_range == 'two-weeks':
        start_date = today
        end_date   = today + timedelta(days=14)
    else:  # 'week' default
        start_date = today
        end_date   = today + timedelta(days=7)

    # Build club sets based on source
    verified_club_ids = [
        c.id for c in Club.query
        .filter_by(is_active=True, is_hidden=False, is_verified=True)
        .with_entities(Club.id).all()
    ]
    all_club_ids = [
        c.id for c in Club.query
        .filter_by(is_active=True, is_hidden=False)
        .with_entities(Club.id).all()
    ]

    if source == 'verified':
        source_filter = Ride.club_id.in_(verified_club_ids)
    elif source == 'clubs':
        source_filter = Ride.club_id.in_(all_club_ids)
    else:  # 'all'
        source_filter = or_(
            Ride.club_id.in_(all_club_ids),
            and_(Ride.owner_id.isnot(None), Ride.is_private == False),
        )

    # Virtual rides always appear regardless of source — they're online, not location-specific
    public_virtual = and_(
        Ride.is_virtual == True,            # noqa: E712
        or_(
            Ride.club_id.isnot(None),       # any club's virtual ride
            and_(Ride.owner_id.isnot(None), Ride.is_private == False),
        ),
    )
    ride_filter = or_(source_filter, public_virtual)

    query = (Ride.query
             .filter(
                 ride_filter,
                 Ride.is_cancelled == False,
                 Ride.date >= start_date,
                 Ride.date <= end_date,
             )
             .order_by(Ride.date.asc(), Ride.time.asc()))

    if pace in ('A', 'B', 'C', 'D'):
        query = query.filter(Ride.pace_category == pace)
    if ride_type == 'virtual':
        query = query.filter(Ride.is_virtual == True)   # noqa: E712
    elif ride_type in ('road', 'gravel', 'social', 'training', 'event', 'night'):
        query = query.filter(Ride.ride_type == ride_type)

    rides = query.limit(200).all()

    # Proximity filtering
    geo_error = None
    user_lat = user_lng = None
    location_label = None

    if lat_arg is not None and lng_arg is not None:
        user_lat, user_lng = lat_arg, lng_arg
        location_label = f'{lat_arg:.2f}, {lng_arg:.2f}'
    elif zip_q:
        coords = geocode_zip(zip_q)
        if coords:
            user_lat, user_lng = coords
            location_label = zip_q
        else:
            geo_error = f'Could not locate zip code "{zip_q}".'

    if user_lat is not None:
        club_cache = {}
        filtered = []
        for r in rides:
            if r.is_virtual:
                # Virtual rides are online — always include regardless of distance
                filtered.append(r)
                continue
            if r.owner_id and not r.club_id:
                # Personal rides have no location — include only when far filters removed
                filtered.append(r)
                continue
            club = club_cache.get(r.club_id)
            if club is None:
                club = Club.query.get(r.club_id)
                club_cache[r.club_id] = club
            if club and club.lat and club.lng:
                dist = haversine_miles(user_lat, user_lng, club.lat, club.lng)
                if dist <= radius:
                    filtered.append(r)
            elif club and not (club.lat and club.lng):
                # Club has no geocoded location — include it rather than hiding
                filtered.append(r)
        rides = filtered

    weather = get_weather_for_rides(rides)
    ride_types = ['road', 'gravel', 'social', 'training', 'event', 'night', 'virtual']
    return render_template(
        'discover.html',
        rides=rides,
        weather=weather,
        active_pace=pace,
        active_type=ride_type,
        active_range=date_range,
        source=source,
        zip_q=zip_q,
        lat_arg=lat_arg,
        lng_arg=lng_arg,
        radius=radius,
        location_label=location_label,
        geo_error=geo_error,
        ride_types=ride_types,
        today=today,
    )
