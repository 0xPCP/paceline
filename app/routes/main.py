from datetime import date, timedelta
from urllib.parse import urlparse
from flask import Blueprint, render_template, request, redirect, url_for, current_app, flash
from flask_login import current_user, login_required
from sqlalchemy import or_, and_
from ..forms import FeedbackForm
from ..models import Club, Ride, RideSignup, ClubMembership, SiteFeedback, User
from ..extensions import db
from ..email import send_feedback_notification
from ..weather import get_weather_for_rides
from ..geocoding import geocode_zip, haversine_miles

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    today = date.today()

    if current_user.is_authenticated:
        return _user_dashboard(today)

    # Landing page for logged-out visitors: show club directory teaser
    clubs = Club.query.filter_by(is_active=True, is_hidden=False).order_by(Club.name.asc()).all()
    return render_template('index.html', clubs=clubs, today=today)


def _user_dashboard(today):
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

    all_display_rides = list({r.id: r for r in my_rides + upcoming_club_rides}.values())
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

    return render_template('dashboard.html',
                           my_rides=my_rides,
                           upcoming_club_rides=upcoming_club_rides,
                           weather=weather,
                           today=today,
                           my_clubs=my_clubs,
                           suggested_clubs=suggested_clubs,
                           signed_up_ride_ids=signed_up_ride_ids,
                           signup_eligible=signup_eligible)


@main_bp.route('/set-language/<lang>')
def set_language(lang):
    flash('Language can be changed from your profile. Signed-out visitors use their browser language preference.', 'info')
    target = url_for('auth.profile') if current_user.is_authenticated else url_for('main.index')
    return redirect(target)


@main_bp.route('/about')
def about():
    return render_template('about.html')


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
                      .limit(20)
                      .all())
    return render_template('public_profile.html',
                           profile_user=profile_user,
                           public_signups=public_signups)


@main_bp.route('/discover/')
def discover():
    today = date.today()

    pace      = request.args.get('pace', '')
    ride_type = request.args.get('type', '')
    date_range = request.args.get('range', 'week')
    zip_q     = request.args.get('zip', '').strip()
    radius    = 50

    # Date window
    if date_range == 'weekend':
        days_until_sat = (5 - today.weekday()) % 7
        if days_until_sat == 0 and today.weekday() == 5:
            days_until_sat = 0
        sat = today + timedelta(days=days_until_sat if days_until_sat else 0)
        if today.weekday() > 5:
            sat = today + timedelta(days=(5 - today.weekday()) % 7)
        sat = today + timedelta(days=(5 - today.weekday()) % 7 or 7)
        end_date = sat + timedelta(days=1)  # Sat + Sun
        start_date = sat
    elif date_range == 'two-weeks':
        start_date = today
        end_date = today + timedelta(days=14)
    else:  # 'week' default
        start_date = today
        end_date = today + timedelta(days=7)

    # Limit to active clubs
    active_club_ids = [c.id for c in Club.query.filter_by(is_active=True, is_hidden=False).with_entities(Club.id).all()]

    query = (Ride.query
             .filter(
                 or_(
                     Ride.club_id.in_(active_club_ids),
                     and_(Ride.owner_id.isnot(None), Ride.is_private == False),
                 ),
                 Ride.is_cancelled == False,
                 Ride.date >= start_date,
                 Ride.date <= end_date,
             )
             .order_by(Ride.date.asc(), Ride.time.asc()))

    if pace in ('A', 'B', 'C', 'D'):
        query = query.filter(Ride.pace_category == pace)
    if ride_type in ('road', 'gravel', 'social', 'training', 'event', 'night'):
        query = query.filter(Ride.ride_type == ride_type)

    rides = query.limit(100).all()

    # Optionally filter by zip proximity
    geo_error = None
    if zip_q:
        coords = geocode_zip(zip_q)
        if coords:
            user_lat, user_lng = coords
            club_cache = {}
            filtered = []
            for r in rides:
                if r.owner_id and not r.club_id:
                    # User-owned rides have no location anchor — include without filtering
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
            rides = filtered
        else:
            geo_error = 'Could not locate that zip code.'

    weather = get_weather_for_rides(rides)
    ride_types = ['road', 'gravel', 'social', 'training', 'event', 'night']
    return render_template('discover.html', rides=rides, weather=weather,
                           active_pace=pace, active_type=ride_type,
                           active_range=date_range, zip_q=zip_q,
                           geo_error=geo_error, ride_types=ride_types, today=today)
