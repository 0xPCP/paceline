import calendar as cal_module
from datetime import date, timedelta
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError
from ..extensions import db
from ..models import Ride, RideSignup
from ..weather import get_weather_for_rides

rides_bp = Blueprint('rides', __name__)


# ── Calendar views ────────────────────────────────────────────────────────────

@rides_bp.route('/')
def calendar():
    view = request.args.get('view', 'list')
    if view == 'month':
        return _month_view()
    if view == 'week':
        return _week_view()
    return _list_view()


def _list_view():
    today = date.today()
    pace = request.args.get('pace', '')
    query = Ride.query.filter(Ride.date >= today).order_by(Ride.date.asc(), Ride.time.asc())
    if pace in ('A', 'B', 'C', 'D'):
        query = query.filter(Ride.includes_pace(pace))
    rides = query.all()
    weather = get_weather_for_rides(rides)
    return render_template('calendar_list.html', rides=rides, active_pace=pace,
                           weather=weather, today=today, view='list')


def _month_view():
    today = date.today()
    try:
        year  = int(request.args.get('y', today.year))
        month = int(request.args.get('m', today.month))
        year  = max(2020, min(year, 2035))
        month = max(1, min(month, 12))
    except (ValueError, TypeError):
        year, month = today.year, today.month

    # Prev / next month
    pm = month - 1 or 12
    py = year - (1 if month == 1 else 0)
    nm = month % 12 + 1
    ny = year + (1 if month == 12 else 0)

    # Build 6-week grid (Mon → Sun)
    c = cal_module.Calendar(firstweekday=0)
    month_dates = c.monthdatescalendar(year, month)  # list of 7-date lists

    # Fetch rides for the entire displayed range (includes days from adjacent months)
    range_start = month_dates[0][0]
    range_end   = month_dates[-1][-1]
    rides_in_range = (
        Ride.query
        .filter(Ride.date >= range_start, Ride.date <= range_end)
        .order_by(Ride.time.asc())
        .all()
    )
    rides_by_date = {}
    for r in rides_in_range:
        rides_by_date.setdefault(r.date, []).append(r)

    weeks = []
    for week in month_dates:
        days = []
        for d in week:
            days.append({
                'date':        d,
                'other_month': d.month != month,
                'is_today':    d == today,
                'rides':       rides_by_date.get(d, []),
            })
        weeks.append(days)

    weather = get_weather_for_rides(rides_in_range)

    return render_template('calendar_month.html',
                           year=year, month=month,
                           month_name=cal_module.month_name[month],
                           weeks=weeks, today=today,
                           prev={'y': py, 'm': pm},
                           next={'y': ny, 'm': nm},
                           weather=weather, view='month')


def _week_view():
    today = date.today()
    # Default to current week (Monday)
    default_start = today - timedelta(days=today.weekday())
    try:
        raw = request.args.get('start', default_start.isoformat())
        week_start = date.fromisoformat(raw)
        # Snap to Monday
        week_start = week_start - timedelta(days=week_start.weekday())
    except (ValueError, TypeError):
        week_start = default_start

    week_end   = week_start + timedelta(days=6)
    prev_start = week_start - timedelta(weeks=1)
    next_start = week_start + timedelta(weeks=1)

    rides_in_range = (
        Ride.query
        .filter(Ride.date >= week_start, Ride.date <= week_end)
        .order_by(Ride.date.asc(), Ride.time.asc())
        .all()
    )
    rides_by_date = {}
    for r in rides_in_range:
        rides_by_date.setdefault(r.date, []).append(r)

    days = []
    for i in range(7):
        d = week_start + timedelta(days=i)
        days.append({
            'date':     d,
            'is_today': d == today,
            'rides':    rides_by_date.get(d, []),
        })

    weather = get_weather_for_rides(rides_in_range)

    return render_template('calendar_week.html',
                           week_start=week_start, week_end=week_end,
                           days=days, today=today,
                           prev_start=prev_start, next_start=next_start,
                           weather=weather, view='week')


# ── Ride detail & signups ─────────────────────────────────────────────────────

@rides_bp.route('/<int:ride_id>')
def detail(ride_id):
    ride = Ride.query.get_or_404(ride_id)
    user_signed_up = False
    if current_user.is_authenticated:
        user_signed_up = RideSignup.query.filter_by(
            ride_id=ride_id, user_id=current_user.id
        ).first() is not None
    weather = get_weather_for_rides([ride])
    ride_weather = weather.get(ride.id)
    return render_template('ride_detail.html', ride=ride,
                           user_signed_up=user_signed_up,
                           ride_weather=ride_weather)


@rides_bp.route('/<int:ride_id>/signup', methods=['POST'])
@login_required
def signup(ride_id):
    ride = Ride.query.get_or_404(ride_id)
    if ride.is_cancelled:
        flash('This ride has been cancelled.', 'warning')
        return redirect(url_for('rides.detail', ride_id=ride_id))
    signup = RideSignup(ride_id=ride_id, user_id=current_user.id)
    db.session.add(signup)
    try:
        db.session.commit()
        flash("You're signed up! See you on the road.", 'success')
    except IntegrityError:
        db.session.rollback()
        flash('You are already signed up for this ride.', 'info')
    return redirect(url_for('rides.detail', ride_id=ride_id))


@rides_bp.route('/<int:ride_id>/unsignup', methods=['POST'])
@login_required
def unsignup(ride_id):
    signup = RideSignup.query.filter_by(ride_id=ride_id, user_id=current_user.id).first()
    if signup:
        db.session.delete(signup)
        db.session.commit()
        flash("You've been removed from this ride.", 'info')
    return redirect(url_for('rides.detail', ride_id=ride_id))
