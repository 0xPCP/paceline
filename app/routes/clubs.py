import re
import calendar as cal_module
from datetime import date, datetime, timedelta, timezone
from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, Response
from flask_login import login_required, current_user, fresh_login_required
from sqlalchemy.exc import IntegrityError
import requests as http_requests
from ..extensions import db
from ..models import Club, ClubAdmin, ClubMembership, Ride, RideComment, ClubInvite, RideSignup, ClubSponsor, ClubPost, ClubShopItem
from ..weather import get_weather_for_rides
from ..geocoding import clubs_near_zip
from .strava import get_club_activities
from ..forms import ClubContactForm, ClubCreateForm, RideCommentForm
from ..geocoding import geocode_zip
from ..utils import is_safe_url
from ..storage import get_storage

clubs_bp = Blueprint('clubs', __name__)

THEME_PRESETS = [
    {'id': 'forest',  'label': 'Forest',  'primary': '#2d6a4f', 'accent': '#e76f51'},
    {'id': 'ocean',   'label': 'Ocean',   'primary': '#1a5276', 'accent': '#f39c12'},
    {'id': 'slate',   'label': 'Slate',   'primary': '#2c3e50', 'accent': '#27ae60'},
    {'id': 'sunset',  'label': 'Sunset',  'primary': '#7d3c98', 'accent': '#e74c3c'},
    {'id': 'crimson', 'label': 'Crimson', 'primary': '#922b21', 'accent': '#3498db'},
    {'id': 'desert',  'label': 'Desert',  'primary': '#b7522a', 'accent': '#f1c40f'},
]

_PRESET_MAP = {p['id']: p for p in THEME_PRESETS}


def _get_club_or_404(slug):
    return Club.query.filter_by(slug=slug, is_active=True, is_hidden=False).first_or_404()


def _notify_friends_of_signup(signer, ride, club):
    """Send friend-ride-signup notifications in the background (fire-and-forget)."""
    from ..email import send_friend_ride_notification
    from ..models import User, ClubMembership
    try:
        signer_id = signer.id
        friend_ids = signer.accepted_friend_ids()
        if not friend_ids:
            return
        # Reload signer as a plain model instance (signer may be a proxy)
        signer_user = db.session.get(User, signer_id)
        if not signer_user:
            return
        friends = User.query.filter(User.id.in_(friend_ids), User.is_active == True).all()  # noqa: E712
        member_ids = set()
        if club.is_private:
            member_ids = {
                m.user_id for m in
                ClubMembership.query.filter_by(club_id=club.id, status='active').all()
            }
        from ..models import UserFriend
        for friend in friends:
            # Check if this friend can see the ride
            if club.is_private and friend.id not in member_ids:
                continue
            # Respect the per-friend follow_rides toggle
            row = UserFriend.query.filter(
                db.or_(
                    db.and_(UserFriend.requester_id == signer_id, UserFriend.addressee_id == friend.id),
                    db.and_(UserFriend.requester_id == friend.id, UserFriend.addressee_id == signer_id),
                )
            ).first()
            if row and not row.follow_rides:
                continue
            send_friend_ride_notification(friend, signer_user, ride)
    except Exception:
        import logging
        logging.getLogger(__name__).exception('Error notifying friends for ride %d', ride.id)


# ── Club directory ────────────────────────────────────────────────────────────

@clubs_bp.route('/')
def index():
    q        = request.args.get('q', '').strip()
    zip_q    = request.args.get('zip', '').strip()
    radius   = request.args.get('radius', '25')
    try:
        radius = int(radius)
        if radius not in (10, 25, 50, 100):
            radius = 25
    except ValueError:
        radius = 25

    all_clubs = Club.query.filter_by(is_active=True, is_hidden=False).order_by(Club.name.asc()).all()

    # Zip-based proximity search takes priority over text search
    zip_results = None
    geo_error   = None
    if zip_q:
        zip_results, geo_error = clubs_near_zip(zip_q, all_clubs, radius_miles=radius)
        clubs = [c for c, _ in zip_results]
        distances = {c.id: d for c, d in zip_results}
    else:
        distances = {}
        if q:
            clubs = [c for c in all_clubs if
                     q.lower() in c.name.lower() or
                     q.lower() in (c.city or '').lower() or
                     q.lower() in (c.state or '').lower() or
                     q.lower() in (c.zip_code or '').lower()]
        else:
            clubs = all_clubs

    return render_template('clubs/index.html', clubs=clubs, q=q,
                           zip_q=zip_q, radius=radius, distances=distances,
                           geo_error=geo_error)


@clubs_bp.route('/map/')
def club_map():
    today = date.today()
    week_end = today + timedelta(days=7)

    clubs_qs = Club.query.filter_by(is_active=True, is_hidden=False).order_by(Club.name.asc()).all()

    # Build club feature list and an id→geo lookup for ride anchoring
    geocoded = {}
    club_features = []
    for club in clubs_qs:
        if club.lat is None or club.lng is None:
            continue
        upcoming_count = (Ride.query
                          .filter_by(club_id=club.id, is_cancelled=False)
                          .filter(Ride.date >= today).count())
        is_member = (current_user.is_authenticated and
                     current_user.is_member_of(club))
        club_features.append({
            'id':        club.id,
            'name':      club.name,
            'slug':      club.slug,
            'lat':       club.lat,
            'lng':       club.lng,
            'city':      club.city or '',
            'state':     club.state or '',
            'members':   club.member_count,
            'upcoming':  upcoming_count,
            'is_member': is_member,
            'url':       f'/clubs/{club.slug}/',
        })
        geocoded[club.id] = {'lat': club.lat, 'lng': club.lng,
                              'name': club.name, 'slug': club.slug}

    # Rides layer — only for authenticated users; anchored at club location (no address)
    ride_features = []
    if current_user.is_authenticated:
        rides_qs = (Ride.query
                    .filter(
                        Ride.club_id.isnot(None),
                        Ride.owner_id.is_(None),
                        Ride.is_cancelled == False,
                        Ride.date >= today,
                        Ride.date <= week_end,
                    )
                    .order_by(Ride.date.asc(), Ride.time.asc())
                    .all())
        for ride in rides_qs:
            geo = geocoded.get(ride.club_id)
            if not geo:
                continue
            ride_features.append({
                'id':         ride.id,
                'title':      ride.title,
                'date':       ride.date.isoformat(),
                'time':       ride.time.strftime('%H:%M') if ride.time else None,
                'pace':       ride.pace_category,
                'ride_type':  ride.ride_type or 'road',
                'distance':   ride.distance_miles,
                'club_name':  geo['name'],
                'club_slug':  geo['slug'],
                'lat':        geo['lat'],
                'lng':        geo['lng'],
                'url':        f'/clubs/{geo["slug"]}/rides/{ride.id}',
            })

    return render_template('clubs/map.html',
                           clubs=club_features,
                           rides=ride_features,
                           user_authenticated=current_user.is_authenticated)


# ── Club creation wizard ──────────────────────────────────────────────────────

_RESERVED_SLUGS = frozenset({
    'create', 'map', 'admin', 'auth', 'api', 'static', 'media',
    'my-rides', 'discover', 'about', 'help', 'invites', 'set-language',
})


def _generate_slug(name):
    """Turn a club name into a URL-safe slug, disambiguating if taken or reserved."""
    base = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')[:70]
    slug = base
    n = 2
    while Club.query.filter_by(slug=slug).first() or slug in _RESERVED_SLUGS:
        slug = f'{base}-{n}'
        n += 1
    return slug


@clubs_bp.route('/create', methods=['GET', 'POST'])
@fresh_login_required
def create():
    form = ClubCreateForm()
    if form.validate_on_submit():
        slug = _generate_slug(form.name.data)
        preset_id = (form.theme_preset.data or '').strip().lower()
        preset = _PRESET_MAP.get(preset_id)

        if preset and preset_id != 'custom':
            primary = preset['primary']
            accent  = preset['accent']
        else:
            primary = (form.theme_primary.data or '').strip().lower() or None
            accent  = (form.theme_accent.data or '').strip().lower() or None
            if primary or accent:
                preset_id = 'custom'
            else:
                preset_id = 'forest'
                primary   = '#2d6a4f'
                accent    = '#e76f51'

        raw_mode = request.form.get('hosting_mode', 'full').strip().lower()
        hosting_mode = raw_mode if raw_mode in ('full', 'rides_only') else 'full'

        club = Club(
            slug          = slug,
            name          = form.name.data.strip(),
            city          = form.city.data.strip() or None,
            state         = form.state.data.strip() or None,
            zip_code      = form.zip_code.data.strip() or None,
            is_private    = request.form.get('is_private') == '1',
            hosting_mode  = hosting_mode,
            theme_preset  = preset_id,
            theme_primary = primary,
            theme_accent  = accent,
            description   = form.description.data or None,
            contact_email = form.contact_email.data or None,
            logo_url      = form.logo_url.data or None,
            banner_url    = form.banner_url.data or None,
            owner_id      = current_user.id,
        )
        if club.zip_code:
            coords = geocode_zip(club.zip_code)
            if coords:
                club.lat, club.lng = coords

        db.session.add(club)
        db.session.flush()  # get club.id before adding relations

        # Creator becomes admin + member
        db.session.add(ClubAdmin(user_id=current_user.id, club_id=club.id, role='admin'))
        db.session.add(ClubMembership(user_id=current_user.id, club_id=club.id))
        db.session.commit()

        flash(f'"{club.name}" has been created! Finish setting up your club, then unhide it when you\'re ready to go public.', 'success')
        return redirect(url_for('admin.club_dashboard', slug=club.slug))

    return render_template('clubs/create.html', form=form, presets=THEME_PRESETS)


# ── Club home ─────────────────────────────────────────────────────────────────

@clubs_bp.route('/<slug>/')
def home(slug):
    club = _get_club_or_404(slug)
    contact_form = ClubContactForm()
    today = date.today()
    upcoming = (Ride.query
                .filter_by(club_id=club.id, is_cancelled=False)
                .filter(Ride.date >= today)
                .order_by(Ride.date.asc(), Ride.time.asc())
                .limit(8).all())
    weather = get_weather_for_rides(upcoming)

    from ..models import RidePoll
    open_polls = (RidePoll.query
                  .filter_by(club_id=club.id)
                  .filter(RidePoll.status.in_(['open', 'closed']), RidePoll.ride_date >= today)
                  .order_by(RidePoll.ride_date.asc())
                  .all())
    is_member  = current_user.is_authenticated and current_user.is_active_member_of(club)
    is_pending = current_user.is_authenticated and current_user.is_pending_member_of(club)
    is_pending_payment = current_user.is_authenticated and current_user.is_pending_payment_member_of(club)
    user_membership = (
        ClubMembership.query.filter_by(user_id=current_user.id, club_id=club.id).first()
        if current_user.is_authenticated else None
    )
    strava_activities = get_club_activities(club.strava_club_id)

    from ..extensions import db as _db
    from sqlalchemy import func
    total_rides = Ride.query.filter_by(club_id=club.id).count()
    total_miles = (_db.session.query(func.sum(Ride.distance_miles))
                   .filter(Ride.club_id == club.id, Ride.is_cancelled == False)
                   .scalar() or 0)
    club_stats = {
        'founded':     club.created_at.year if club.created_at else None,
        'members':     club.member_count,
        'total_rides': total_rides,
        'total_miles': round(total_miles),
    }
    has_shop_items = (
        club.stripe_connect_ready
        and ClubShopItem.query.filter_by(club_id=club.id, is_active=True).first() is not None
    )

    # Board preview: 15 most recent posts + subscription status (members only)
    board_posts = []
    board_is_subscribed = False
    board_is_admin = False
    board_has_more = False
    if is_member:
        from ..models import ClubBoardPost, ClubBoardSubscription
        from datetime import timedelta, timezone as _tz
        cutoff = datetime.now(_tz.utc).replace(tzinfo=None) - timedelta(days=365)
        _bposts = (ClubBoardPost.query
                   .filter_by(club_id=club.id)
                   .filter(ClubBoardPost.created_at >= cutoff)
                   .order_by(ClubBoardPost.is_pinned.desc(),
                              ClubBoardPost.created_at.desc())
                   .limit(16).all())
        board_has_more = len(_bposts) > 15
        board_posts = _bposts[:15]
        board_is_subscribed = ClubBoardSubscription.query.filter_by(
            club_id=club.id, user_id=current_user.id).first() is not None
        board_is_admin = current_user.can_manage_content(club)

    return render_template('clubs/home.html', club=club, upcoming=upcoming,
                           open_polls=open_polls,
                           weather=weather, is_member=is_member, is_pending=is_pending,
                           is_pending_payment=is_pending_payment,
                           user_membership=user_membership,
                           today=today, strava_activities=strava_activities,
                           club_stats=club_stats,
                           contact_form=contact_form,
                           board_posts=board_posts,
                           board_is_subscribed=board_is_subscribed,
                           board_is_admin=board_is_admin,
                           board_has_more=board_has_more,
                           has_shop_items=has_shop_items)


@clubs_bp.route('/<slug>/leaders/')
def club_leaders_public(slug):
    club = _get_club_or_404(slug)
    return render_template('clubs/leaders.html', club=club, leaders=club.leaders)


@clubs_bp.route('/<slug>/shop/')
def club_shop(slug):
    club = _get_club_or_404(slug)
    if not club.stripe_connect_ready:
        abort(404)
    items = ClubShopItem.query.filter_by(club_id=club.id, is_active=True).order_by(
        ClubShopItem.display_order.asc(),
        ClubShopItem.name.asc(),
    ).all()
    return render_template('clubs/shop.html', club=club, items=items)


@clubs_bp.route('/<slug>/members/')
def club_members(slug):
    """Member roster for signed-in active members, ordered by role then attendance."""
    from ..models import User, ClubMembership, ClubAdmin, ClubLeader, RideSignup, Ride
    club = _get_club_or_404(slug)

    if not current_user.is_authenticated:
        return redirect(url_for('auth.login', next=request.url))
    if not current_user.is_active_member_of(club):
        abort(403)

    active_memberships = (
        ClubMembership.query
        .filter_by(club_id=club.id, status='active')
        .all()
    )
    member_ids = [m.user_id for m in active_memberships]
    if not member_ids:
        return render_template('clubs/members.html', club=club, sections=[])

    # Attendance count per member for this club's rides
    from sqlalchemy import func
    attendance = dict(
        db.session.query(RideSignup.user_id, func.count(RideSignup.id))
        .join(Ride, RideSignup.ride_id == Ride.id)
        .filter(Ride.club_id == club.id, RideSignup.user_id.in_(member_ids))
        .group_by(RideSignup.user_id)
        .all()
    )

    admin_rows = ClubAdmin.query.filter_by(club_id=club.id).all()
    admin_user_ids = {r.user_id: r.role for r in admin_rows}
    owner_id = club.owner_id
    ride_leader_ids = {
        r.user_id for r in admin_rows
        if r.role in ('admin', 'ride_manager')
    }
    ride_leader_ids.update(
        row.user_id
        for row in ClubLeader.query.filter_by(club_id=club.id).all()
        if row.user_id
    )

    users = {u.id: u for u in User.query.filter(User.id.in_(member_ids)).all()}

    owner = [users[owner_id]] if owner_id and owner_id in users else []
    leaders = [users[uid] for uid in ride_leader_ids if uid in users and uid != owner_id]
    leaders.sort(key=lambda u: attendance.get(u.id, 0), reverse=True)
    others = [
        users[uid] for uid in member_ids
        if uid != owner_id and uid not in ride_leader_ids and uid in users
    ]
    others.sort(key=lambda u: attendance.get(u.id, 0), reverse=True)

    sections = []
    if owner:
        sections.append(('Club Owner', owner))
    if leaders:
        sections.append(('Ride Leaders', leaders))
    if others:
        sections.append(('Members', others))

    return render_template('clubs/members.html', club=club, sections=sections,
                           attendance=attendance, admin_user_ids=admin_user_ids,
                           owner_id=owner_id)


@clubs_bp.route('/<slug>/contact', methods=['GET', 'POST'])
@login_required
def club_contact(slug):
    club = _get_club_or_404(slug)
    form = ClubContactForm()
    if request.method == 'GET':
        return render_template('clubs/contact.html', club=club, form=form)

    if not form.validate_on_submit():
        flash('Please add a subject and message before sending.', 'danger')
        return render_template('clubs/contact.html', club=club, form=form), 400

    from ..email import send_club_contact_message
    sent = send_club_contact_message(
        club,
        current_user,
        form.subject.data.strip(),
        form.message.data.strip(),
        form.recipient_group.data,
    )
    if sent:
        flash(f'Your message was sent to {club.name}.', 'success')
    else:
        flash('This club does not have a contact recipient configured yet.', 'warning')
    return redirect(url_for('clubs.home', slug=club.slug))


# ── Club calendar ─────────────────────────────────────────────────────────────

@clubs_bp.route('/<slug>/rides/')
def rides(slug):
    if not current_user.is_authenticated:
        return redirect(url_for('auth.login', next=request.url))
    club = _get_club_or_404(slug)
    view = request.args.get('view', 'list')
    if view == 'month':
        return _month_view(club)
    if view == 'week':
        return _week_view(club)
    return _list_view(club)


RIDE_TYPES = ['road', 'gravel', 'social', 'training', 'event', 'night']


def _list_view(club):
    today = date.today()
    pace = request.args.get('pace', '')
    ride_type = request.args.get('type', '')
    query = (Ride.query
             .filter_by(club_id=club.id)
             .filter(Ride.date >= today)
             .order_by(Ride.date.asc(), Ride.time.asc()))
    if pace in ('A', 'B', 'C', 'D'):
        query = query.filter(Ride.pace_category == pace)
    if ride_type in RIDE_TYPES:
        query = query.filter(Ride.ride_type == ride_type)
    rides = query.all()
    weather = get_weather_for_rides(rides)
    # Group by date so same-day rides render as a collapsible multi-group card
    from collections import OrderedDict
    ride_groups = OrderedDict()
    for r in rides:
        ride_groups.setdefault(r.date, []).append(r)
    friend_counts = {}
    if current_user.is_authenticated:
        friend_ids = current_user.accepted_friend_ids()
        if friend_ids and rides:
            rows = (RideSignup.query
                    .filter(RideSignup.user_id.in_(friend_ids),
                            RideSignup.ride_id.in_([r.id for r in rides]),
                            RideSignup.is_waitlist == False,   # noqa: E712
                            RideSignup.is_anonymous == False)  # noqa: E712
                    .all())
            for row in rows:
                friend_counts[row.ride_id] = friend_counts.get(row.ride_id, 0) + 1
    return render_template('clubs/calendar_list.html', club=club, rides=rides,
                           ride_groups=ride_groups,
                           active_pace=pace, active_type=ride_type,
                           ride_types=RIDE_TYPES, weather=weather, today=today, view='list',
                           friend_counts=friend_counts)


def _month_view(club):
    today = date.today()
    try:
        year  = int(request.args.get('y', today.year))
        month = int(request.args.get('m', today.month))
        year  = max(2020, min(year, 2035))
        month = max(1, min(month, 12))
    except (ValueError, TypeError):
        year, month = today.year, today.month

    pm = month - 1 or 12
    py = year - (1 if month == 1 else 0)
    nm = month % 12 + 1
    ny = year + (1 if month == 12 else 0)

    c = cal_module.Calendar(firstweekday=0)
    month_dates = c.monthdatescalendar(year, month)
    range_start = month_dates[0][0]
    range_end   = month_dates[-1][-1]

    rides_in_range = (Ride.query
                      .filter_by(club_id=club.id)
                      .filter(Ride.date >= range_start, Ride.date <= range_end)
                      .order_by(Ride.time.asc()).all())
    rides_by_date = {}
    for r in rides_in_range:
        rides_by_date.setdefault(r.date, []).append(r)

    weeks = []
    for week in month_dates:
        days = []
        for d in week:
            days.append({'date': d, 'other_month': d.month != month,
                         'is_today': d == today, 'rides': rides_by_date.get(d, [])})
        weeks.append(days)

    weather = get_weather_for_rides(rides_in_range)
    return render_template('clubs/calendar_month.html', club=club,
                           year=year, month=month,
                           month_name=cal_module.month_name[month],
                           weeks=weeks, today=today,
                           prev={'y': py, 'm': pm}, next={'y': ny, 'm': nm},
                           weather=weather, view='month')


def _week_view(club):
    today = date.today()
    default_start = today - timedelta(days=today.weekday())
    try:
        raw = request.args.get('start', default_start.isoformat())
        week_start = date.fromisoformat(raw)
        week_start = week_start - timedelta(days=week_start.weekday())
    except (ValueError, TypeError):
        week_start = default_start

    week_end   = week_start + timedelta(days=6)
    prev_start = week_start - timedelta(weeks=1)
    next_start = week_start + timedelta(weeks=1)

    rides_in_range = (Ride.query
                      .filter_by(club_id=club.id)
                      .filter(Ride.date >= week_start, Ride.date <= week_end)
                      .order_by(Ride.date.asc(), Ride.time.asc()).all())
    rides_by_date = {}
    for r in rides_in_range:
        rides_by_date.setdefault(r.date, []).append(r)

    days = []
    for i in range(7):
        d = week_start + timedelta(days=i)
        days.append({'date': d, 'is_today': d == today, 'rides': rides_by_date.get(d, [])})

    weather = get_weather_for_rides(rides_in_range)
    return render_template('clubs/calendar_week.html', club=club,
                           week_start=week_start, week_end=week_end,
                           days=days, today=today,
                           prev_start=prev_start, next_start=next_start,
                           weather=weather, view='week')


# ── Embeddable ride widget ────────────────────────────────────────────────────

@clubs_bp.route('/<slug>/embed')
def embed(slug):
    """Public embeddable ride widget — designed to be iframed on external sites."""
    club = _get_club_or_404(slug)
    today = date.today()
    end_date = today + timedelta(days=30)
    rides = (Ride.query
             .filter_by(club_id=club.id, is_cancelled=False)
             .filter(Ride.date >= today, Ride.date <= end_date)
             .order_by(Ride.date.asc(), Ride.time.asc())
             .limit(50).all())

    return render_template('clubs/embed.html', club=club, rides=rides, today=today)


# ── Ride detail & signups ─────────────────────────────────────────────────────

@clubs_bp.route('/<slug>/rides/<int:ride_id>')
def ride_detail(slug, ride_id):
    club = _get_club_or_404(slug)
    ride = Ride.query.filter_by(id=ride_id, club_id=club.id).first_or_404()

    user_signed_up = False
    user_waitlisted = False
    my_signup = None
    waiver_required = False
    membership_required = False
    show_route = True
    if current_user.is_authenticated:
        my_signup = RideSignup.query.filter_by(
            ride_id=ride_id, user_id=current_user.id
        ).first()
        if my_signup:
            if my_signup.is_waitlist:
                user_waitlisted = True
            else:
                user_signed_up = True
        if club.current_waiver and not current_user.has_signed_waiver(club):
            waiver_required = True
        if club.require_membership and not current_user.is_active_member_of(club):
            membership_required = True
        if club.is_private and not current_user.is_active_member_of(club):
            show_route = False
    else:
        if club.require_membership:
            membership_required = True
        if club.is_private:
            show_route = False

    weather = get_weather_for_rides([ride])
    ride_weather = weather.get(ride.id)

    ride_gear = None
    if ride_weather:
        from ..gear import cycling_gear, VERDICT_LABEL, estimate_duration
        duration = estimate_duration(ride.distance_miles, ride.pace_category)
        owned = (current_user.gear_inventory
                 if current_user.is_authenticated and current_user.gear_inventory
                 else None)
        g = cycling_gear(
            temp_f=ride_weather['temp_f'],
            feels_like_f=ride_weather['feels_like_f'],
            wind_mph=ride_weather['wind_mph'],
            precip_prob=ride_weather['precip_prob'],
            weather_code=ride_weather['weather_code'],
            owned_ids=owned,
            pace_category=ride.pace_category,
            duration_hours=duration,
            end_temp_f=ride_weather.get('end_temp_f'),
        )
        verdict_text, verdict_class = VERDICT_LABEL[g['verdict']]
        gear_items = []
        for slot, icon in [
            ('bottoms',    '🩳'), ('jersey',     '👕'), ('base_layer', '🧥'),
            ('outer',      '🧥'), ('gloves',     '🧤'), ('head',       '🧢'),
            ('feet',       '👟'), ('eyewear',    '🕶️'),
        ]:
            val = g.get(slot)
            if val:
                gear_items.append({'icon': icon, 'label': val})
        for warmer in g.get('warmers', []):
            gear_items.append({'icon': '💪', 'label': warmer})
        if g.get('sun_sleeves'):
            gear_items.append({'icon': '☀️', 'label': g['sun_sleeves']})
        ride_gear = {
            'verdict':       g['verdict'],
            'verdict_text':  verdict_text,
            'verdict_class': verdict_class,
            'gear_list':     gear_items,
            'notes':         g.get('notes', []),
            'duration_hours': duration,
            'end_temp_f':    ride_weather.get('end_temp_f'),
        }

    comment_form = RideCommentForm() if current_user.is_authenticated else None

    # Build Open Graph metadata for share previews
    _og_parts = []
    if ride.ride_type:
        _og_parts.append(ride.ride_type.capitalize() + ' ride')
    if ride.distance_miles:
        _og_parts.append(f"{ride.distance_miles:.0f} mi")
    if ride.pace_category:
        _og_parts.append(f"{ride.pace_category} pace")
    _og_parts.append(
        ride.date.strftime('%-d %b') + ' at ' + ride.time.strftime('%-I:%M %p').lstrip('0')
    )
    if ride.meeting_location:
        _og_parts.append(ride.meeting_location)
    og_title = f"{ride.title} — {club.name}"
    og_description = club.name + ' · ' + ' · '.join(_og_parts)
    can_manage_groupride_code = False
    can_add_groupride_code = False
    if current_user.is_authenticated:
        can_manage_groupride_code = (
            current_user.can_manage_rides(club)
            or (ride.leader_id and ride.leader_id == current_user.id)
        )
        can_add_groupride_code = can_manage_groupride_code or (
            not ride.garmin_groupride_code and my_signup is not None and not my_signup.is_waitlist
        )
    from flask import current_app
    return render_template('clubs/ride_detail.html', club=club, ride=ride,
                           user_signed_up=user_signed_up,
                           user_waitlisted=user_waitlisted,
                           waiver_required=waiver_required,
                           membership_required=membership_required,
                           show_route=show_route,
                           ride_weather=ride_weather,
                           ride_gear=ride_gear,
                           comment_form=comment_form,
                           can_manage_groupride_code=can_manage_groupride_code,
                           can_add_groupride_code=can_add_groupride_code,
                           og_title=og_title,
                           og_description=og_description,
                           media_expiry_days=current_app.config.get('MEDIA_EXPIRY_DAYS', 90),
                           media_max_per_user=current_app.config.get('MEDIA_MAX_PHOTOS_PER_USER_RIDE', 5))


@clubs_bp.route('/<slug>/rides/<int:ride_id>/groupride-code', methods=['POST'])
@login_required
def ride_groupride_code(slug, ride_id):
    club = _get_club_or_404(slug)
    ride = Ride.query.filter_by(id=ride_id, club_id=club.id).first_or_404()
    if ride.is_virtual:
        abort(404)
    signup = RideSignup.query.filter_by(ride_id=ride.id, user_id=current_user.id).first()
    can_manage = (
        current_user.can_manage_rides(club)
        or (ride.leader_id and ride.leader_id == current_user.id)
    )
    can_add_when_blank = (
        not ride.garmin_groupride_code
        and signup is not None
        and not signup.is_waitlist
    )
    if not can_manage and not can_add_when_blank:
        abort(403)

    code = (request.form.get('garmin_groupride_code') or '').strip()
    if code and not re.fullmatch(r'\d{6}', code):
        flash('Enter the 6-digit Garmin GroupRide code.', 'danger')
        return redirect(url_for('clubs.ride_detail', slug=slug, ride_id=ride.id) + '#groupride')
    if ride.garmin_groupride_code and not can_manage:
        abort(403)

    ride.garmin_groupride_code = code or None
    db.session.commit()
    flash('Garmin GroupRide code updated.', 'success')
    return redirect(url_for('clubs.ride_detail', slug=slug, ride_id=ride.id) + '#groupride')


@clubs_bp.route('/<slug>/rides/<int:ride_id>/ics')
def ride_ics(slug, ride_id):
    club = _get_club_or_404(slug)
    ride = Ride.query.filter_by(id=ride_id, club_id=club.id).first_or_404()

    def _ics_safe(value):
        """Strip CR/LF from a value so it can't inject extra iCalendar properties."""
        return re.sub(r'[\r\n]+', ' ', str(value or ''))

    dt_start = datetime.combine(ride.date, ride.time)
    dt_end   = dt_start + timedelta(hours=2)
    dt_stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')

    desc_parts = [f'Pace: {ride.pace_label}', f'Distance: {ride.distance_miles} mi']
    if ride.elevation_feet:
        desc_parts.append(f'Elevation: {ride.elevation_feet} ft')
    if ride.ride_leader:
        desc_parts.append(f'Leader: {_ics_safe(ride.ride_leader)}')
    if ride.description:
        desc_parts.append(_ics_safe(ride.description))
    description = '\\n'.join(desc_parts)

    ics = (
        'BEGIN:VCALENDAR\r\n'
        'VERSION:2.0\r\n'
        'PRODID:-//Paceline.club//paceline.club//EN\r\n'
        'CALSCALE:GREGORIAN\r\n'
        'METHOD:PUBLISH\r\n'
        'BEGIN:VEVENT\r\n'
        f'UID:ride-{ride.id}@paceline.club\r\n'
        f'DTSTAMP:{dt_stamp}\r\n'
        f'DTSTART:{dt_start.strftime("%Y%m%dT%H%M%S")}\r\n'
        f'DTEND:{dt_end.strftime("%Y%m%dT%H%M%S")}\r\n'
        f'SUMMARY:{_ics_safe(ride.title)} — {_ics_safe(club.name)}\r\n'
        f'DESCRIPTION:{description}\r\n'
        f'LOCATION:{_ics_safe(ride.meeting_location)}\r\n'
        'END:VEVENT\r\n'
        'END:VCALENDAR\r\n'
    )

    filename = f'ride-{ride.id}.ics'
    return Response(
        ics,
        mimetype='text/calendar',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


@clubs_bp.route('/<slug>/rides/<int:ride_id>/gpx')
def ride_gpx(slug, ride_id):
    club = _get_club_or_404(slug)
    ride = Ride.query.filter_by(id=ride_id, club_id=club.id).first_or_404()

    if not ride.ridewithgps_route_id:
        abort(404)

    # Private clubs hide route details from non-members
    if club.is_private and not (
        current_user.is_authenticated and current_user.is_active_member_of(club)
    ):
        abort(403)

    gpx_url = f'https://ridewithgps.com/routes/{ride.ridewithgps_route_id}.gpx'
    try:
        upstream = http_requests.get(gpx_url, timeout=15,
                                     headers={'User-Agent': 'Paceline/1.0 (paceline.club)'})
        if upstream.status_code != 200:
            abort(404)
    except http_requests.RequestException:
        abort(503)

    safe_title = ''.join(c if c.isalnum() or c in '-_ ' else '' for c in ride.title)
    filename = safe_title.strip().lower().replace(' ', '-') + '.gpx'
    return Response(
        upstream.content,
        mimetype='application/gpx+xml',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


@clubs_bp.route('/<slug>/rides/<int:ride_id>/signup', methods=['POST'])
@login_required
def ride_signup(slug, ride_id):
    club = _get_club_or_404(slug)
    ride = Ride.query.filter_by(id=ride_id, club_id=club.id).first_or_404()

    if ride.is_cancelled:
        flash('This ride has been cancelled.', 'warning')
        return redirect(url_for('clubs.ride_detail', slug=slug, ride_id=ride_id))

    if club.require_membership and not current_user.is_active_member_of(club):
        flash('You must be an active member of this club to sign up for rides.', 'warning')
        return redirect(url_for('clubs.home', slug=slug))

    if club.current_waiver and not current_user.has_signed_waiver(club):
        flash('Please accept the club waiver before signing up for rides.', 'warning')
        return redirect(url_for('clubs.waiver', slug=slug, next=request.url))

    from ..models import RideSignup
    from sqlalchemy.exc import IntegrityError
    already = RideSignup.query.filter_by(ride_id=ride_id, user_id=current_user.id).first()
    if already:
        flash('You are already signed up for this ride.', 'info')
        return redirect(url_for('clubs.ride_detail', slug=slug, ride_id=ride_id))
    on_waitlist = ride.is_full
    is_anon = request.form.get('is_anonymous') == '1'
    db.session.add(RideSignup(ride_id=ride_id, user_id=current_user.id,
                              is_waitlist=on_waitlist, is_anonymous=is_anon))
    try:
        db.session.commit()
        if on_waitlist:
            flash(f"The ride is full — you've been added to the waitlist (#{ride.waitlist_count}).", 'info')
        else:
            flash("You're signed up! See you on the road.", 'success')
            if not is_anon:
                _notify_friends_of_signup(current_user, ride, club)
    except IntegrityError:
        db.session.rollback()
        flash('You are already signed up for this ride.', 'info')
    return redirect(url_for('clubs.ride_detail', slug=slug, ride_id=ride_id))


@clubs_bp.route('/<slug>/rides/<int:ride_id>/unsignup', methods=['POST'])
@login_required
def ride_unsignup(slug, ride_id):
    from ..models import RideSignup
    from ..email import send_waitlist_promoted
    club = _get_club_or_404(slug)
    ride = Ride.query.filter_by(id=ride_id, club_id=club.id).first_or_404()
    s = RideSignup.query.filter_by(ride_id=ride_id, user_id=current_user.id).first()
    if s:
        was_active = not s.is_waitlist
        db.session.delete(s)
        db.session.flush()
        if was_active:
            next_up = (RideSignup.query
                       .filter_by(ride_id=ride_id, is_waitlist=True)
                       .order_by(RideSignup.created_at.asc())
                       .first())
            if next_up:
                next_up.is_waitlist = False
                db.session.commit()
                send_waitlist_promoted(next_up)
                flash("You've been removed. The next person on the waitlist has been notified.", 'info')
            else:
                db.session.commit()
                flash("You've been removed from this ride.", 'info')
        else:
            db.session.commit()
            flash("You've been removed from the waitlist.", 'info')
    return redirect(url_for('clubs.ride_detail', slug=slug, ride_id=ride_id))


# ── Club membership ───────────────────────────────────────────────────────────

@clubs_bp.route('/<slug>/join', methods=['GET', 'POST'])
@login_required
def join(slug):
    club = _get_club_or_404(slug)
    if request.method == 'GET':
        return redirect(url_for('clubs.home', slug=slug))

    existing = ClubMembership.query.filter_by(user_id=current_user.id, club_id=club.id).first()
    if existing:
        return redirect(url_for('clubs.home', slug=slug))

    if club.membership_dues_required and not club.stripe_dues_ready:
        flash('Paid membership is not available for this club until Stripe Connect is set up.', 'warning')
        return redirect(url_for('clubs.home', slug=slug))

    if club.membership_dues_required:
        status = 'pending_payment'
    else:
        status = 'pending' if club.join_approval == 'manual' else 'active'
    db.session.add(ClubMembership(user_id=current_user.id, club_id=club.id, status=status))
    try:
        db.session.commit()
        if status == 'pending_payment':
            flash(f"Your request to join {club.name} is waiting for dues payment. Use the club dues button to pay through Stripe and activate automatically.", 'info')
        elif status == 'pending':
            flash(f"Your request to join {club.name} has been submitted. An admin will review it shortly.", 'info')
        else:
            flash(f"You've joined {club.name}!", 'success')
    except IntegrityError:
        db.session.rollback()
    return redirect(url_for('clubs.home', slug=slug))


@clubs_bp.route('/<slug>/leave', methods=['POST'])
@login_required
def leave(slug):
    club = _get_club_or_404(slug)
    m = ClubMembership.query.filter_by(user_id=current_user.id, club_id=club.id).first()
    if m:
        db.session.delete(m)
        db.session.commit()
        flash(f"You've left {club.name}.", 'info')
    return redirect(url_for('clubs.home', slug=slug))


# ── Waiver ────────────────────────────────────────────────────────────────────

@clubs_bp.route('/<slug>/waiver', methods=['GET', 'POST'])
@login_required
def waiver(slug):
    club = _get_club_or_404(slug)
    waiver_obj = club.current_waiver
    if not waiver_obj:
        flash('This club has no waiver on file.', 'info')
        return redirect(url_for('clubs.home', slug=slug))

    next_raw = request.args.get('next', '')
    next_url = next_raw if (next_raw and is_safe_url(next_raw)) else url_for('clubs.rides', slug=slug)

    if request.method == 'POST':
        if request.form.get('agree') == '1':
            from ..models import WaiverSignature
            from datetime import datetime, timezone
            year = datetime.now(timezone.utc).year
            if not current_user.has_signed_waiver(club, year):
                db.session.add(WaiverSignature(
                    user_id=current_user.id, club_id=club.id,
                    waiver_id=waiver_obj.id, year=year
                ))
                db.session.commit()
            flash('Waiver accepted. Welcome!', 'success')
            return redirect(next_url)
        flash('You must check the box to accept the waiver.', 'danger')

    already_signed = current_user.has_signed_waiver(club)
    return render_template('clubs/waiver.html', club=club, waiver=waiver_obj,
                           already_signed=already_signed, next_url=next_url)


# ── Ride comments ─────────────────────────────────────────────────────────────

@clubs_bp.route('/<slug>/rides/<int:ride_id>/comments', methods=['POST'])
@login_required
def ride_comment_post(slug, ride_id):
    club = _get_club_or_404(slug)
    ride = Ride.query.filter_by(id=ride_id, club_id=club.id).first_or_404()
    if club.is_private and not current_user.is_active_member_of(club):
        abort(403)
    form = RideCommentForm()
    if form.validate_on_submit():
        comment = RideComment(
            ride_id=ride.id,
            user_id=current_user.id,
            body=form.body.data.strip(),
        )
        db.session.add(comment)
        db.session.commit()
        flash('Comment posted.', 'success')
    return redirect(url_for('clubs.ride_detail', slug=slug, ride_id=ride_id) + '#comments')


@clubs_bp.route('/<slug>/rides/<int:ride_id>/comments/<int:comment_id>/delete', methods=['POST'])
@login_required
def ride_comment_delete(slug, ride_id, comment_id):
    club = _get_club_or_404(slug)
    ride = Ride.query.filter_by(id=ride_id, club_id=club.id).first_or_404()
    comment = RideComment.query.filter_by(id=comment_id, ride_id=ride.id).first_or_404()
    if comment.user_id != current_user.id and not current_user.can_manage_rides(club):
        abort(403)
    db.session.delete(comment)
    db.session.commit()
    flash('Comment deleted.', 'info')
    return redirect(url_for('clubs.ride_detail', slug=slug, ride_id=ride_id) + '#comments')


# ── Invite claim ──────────────────────────────────────────────────────────────

@clubs_bp.route('/invites/<token>')
def invite_claim(token):
    from ..models import ClubMembership
    invite = ClubInvite.query.filter_by(token=token).first_or_404()
    if invite.used_at:
        flash('This invite link has already been used.', 'warning')
        return redirect(url_for('clubs.home', slug=invite.club.slug))
    if invite.expires_at.replace(tzinfo=None) < datetime.now(timezone.utc).replace(tzinfo=None):
        flash('This invite link has expired.', 'warning')
        return redirect(url_for('clubs.home', slug=invite.club.slug))

    # Bulk-import new-user tokens require password setup before login
    if invite.is_new_user:
        return redirect(url_for('auth.setup_account', token=token))

    if not current_user.is_authenticated:
        return redirect(url_for('auth.login', next=url_for('clubs.invite_claim', token=token)))

    club = invite.club
    existing = ClubMembership.query.filter_by(user_id=current_user.id, club_id=club.id).first()
    if existing:
        if existing.status != 'active':
            existing.status = 'active'
        if invite.membership_expires_on:
            existing.dues_paid_until = invite.membership_expires_on
        db.session.commit()
        flash(f"You're now an active member of {club.name}!", 'success')
    else:
        db.session.add(ClubMembership(
            user_id=current_user.id,
            club_id=club.id,
            status='active',
            dues_paid_until=invite.membership_expires_on,
        ))
        invite.used_at = datetime.now(timezone.utc)
        invite.used_by_user_id = current_user.id
        db.session.commit()
        flash(f"Welcome to {club.name}! Your membership is active.", 'success')

    return redirect(url_for('clubs.home', slug=club.slug))


@clubs_bp.route('/<slug>/logo')
def serve_club_logo(slug):
    """Serve an uploaded club logo (always public)."""
    from flask import current_app
    club = _get_club_or_404(slug)
    if not club.logo_key:
        abort(404)
    return get_storage().serve(club.logo_key, is_private=False,
                               upload_folder=current_app.config['UPLOAD_FOLDER'])


@clubs_bp.route('/<slug>/sponsors/<int:sponsor_id>/logo')
def serve_sponsor_logo(slug, sponsor_id):
    """Serve an uploaded sponsor logo (always public)."""
    from flask import current_app
    club = _get_club_or_404(slug)
    sponsor = ClubSponsor.query.filter_by(id=sponsor_id, club_id=club.id).first_or_404()
    if not sponsor.logo_key:
        abort(404)
    return get_storage().serve(sponsor.logo_key, is_private=False,
                               upload_folder=current_app.config['UPLOAD_FOLDER'])


@clubs_bp.route('/<slug>/posts/<int:post_id>/image')
def serve_post_image(slug, post_id):
    """Serve a news post header image (always public)."""
    from flask import current_app
    club = _get_club_or_404(slug)
    post = ClubPost.query.filter_by(id=post_id, club_id=club.id).first_or_404()
    if not post.image_key:
        abort(404)
    return get_storage().serve(post.image_key, is_private=False,
                               upload_folder=current_app.config['UPLOAD_FOLDER'])
