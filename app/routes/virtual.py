"""Virtual rides discovery — /virtual/

Lists all public upcoming virtual rides across clubs and user-owned rides.
Excluded from geographic maps; discoverable here as a one-off search.
"""
from datetime import date, timedelta
from flask import Blueprint, render_template, request
from ..models import Ride

virtual_bp = Blueprint('virtual', __name__)

PLATFORM_LABELS = {
    'zwift':       'Zwift',
    'rouvy':       'Rouvy',
    'wahoo':       'Wahoo SYSTM',
    'trainerroad': 'TrainerRoad',
    'fulgaz':      'FulGaz',
    'bkool':       'BKOOL',
    'other':       'Other',
}


@virtual_bp.route('/')
def index():
    today = date.today()
    platform = request.args.get('platform', '').strip().lower()
    pace     = request.args.get('pace', '').strip().upper()
    days     = request.args.get('days', '30')
    try:
        days = int(days)
        if days not in (7, 14, 30, 60, 90):
            days = 30
    except ValueError:
        days = 30

    cutoff = today + timedelta(days=days)

    query = (Ride.query
             .filter(Ride.is_virtual == True)           # noqa: E712
             .filter(Ride.is_cancelled == False)        # noqa: E712
             .filter(Ride.date >= today)
             .filter(Ride.date <= cutoff))

    # Exclude private user-owned rides; club virtual rides are always visible
    query = query.filter(
        (Ride.owner_id == None) |                      # noqa: E711 club ride
        (Ride.is_private == False)                     # noqa: E712 public user ride
    )

    if platform:
        query = query.filter(Ride.virtual_platform == platform)
    if pace in ('A', 'B', 'C', 'D'):
        query = query.filter(Ride.includes_pace(pace))

    rides = query.order_by(Ride.date.asc(), Ride.time.asc()).all()

    return render_template(
        'virtual/index.html',
        rides=rides,
        today=today,
        platform=platform,
        pace=pace,
        days=days,
        platform_labels=PLATFORM_LABELS,
    )
