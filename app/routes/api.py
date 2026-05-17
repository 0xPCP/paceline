"""
JSON API endpoints — used by client-side JS.
"""
from datetime import date
from flask import Blueprint, jsonify, request
from flask_login import current_user
from ..models import Club, Ride, RideSignup
from ..weather import get_current_weather
from ..gear import cycling_gear, VERDICT_LABEL, ITEM_ICONS
from ..geocoding import geocode_zip

api_bp = Blueprint('api', __name__)


@api_bp.route('/clubs/map-data')
def clubs_map_data():
    """
    GET /api/clubs/map-data
    Returns all geocoded active clubs as GeoJSON-style JSON for the Leaflet map.
    """
    today = date.today()
    clubs = Club.query.filter_by(is_active=True, is_hidden=False).order_by(Club.name.asc()).all()
    features = []
    for club in clubs:
        if club.lat is None or club.lng is None:
            continue
        upcoming_count = (Ride.query
                          .filter_by(club_id=club.id, is_cancelled=False)
                          .filter(Ride.date >= today).count())
        is_member = (current_user.is_authenticated and
                     current_user.is_member_of(club))
        features.append({
            'id':       club.id,
            'name':     club.name,
            'slug':     club.slug,
            'lat':      club.lat,
            'lng':      club.lng,
            'city':     club.city or '',
            'state':    club.state or '',
            'members':  club.member_count,
            'upcoming': upcoming_count,
            'is_member': is_member,
            'url':      f'/clubs/{club.slug}/',
        })
    return jsonify(features)


@api_bp.route('/weather/widget')
def weather_widget():
    """
    GET /api/weather/widget?lat=X&lng=Y[&pace=B&duration=2.5]
    GET /api/weather/widget?zip=XXXXX[&pace=B&duration=2.5]

    Returns current conditions + cycling gear recommendations as JSON.
    Gear is filtered to items the logged-in user owns (if inventory is set).
    Optional pace (A/B/C/D) and duration (hours) adjust recommendations for
    the intensity and length of the specific ride being planned.
    """
    lat      = request.args.get('lat', type=float)
    lng      = request.args.get('lng', type=float)
    zip_code = request.args.get('zip', '').strip()
    pace     = request.args.get('pace', '').upper().strip() or None
    duration = request.args.get('duration', type=float)

    if lat is None or lng is None:
        if zip_code:
            coords = geocode_zip(zip_code)
            if coords is None:
                return jsonify({'error': 'Could not locate zip code.'}), 400
            lat, lng = coords
        else:
            return jsonify({'error': 'Provide lat/lng or zip.'}), 400

    weather = get_current_weather(lat, lng)
    if weather is None:
        return jsonify({'error': 'Weather service unavailable.'}), 503

    owned_ids = None
    if current_user.is_authenticated and current_user.gear_inventory:
        owned_ids = current_user.gear_inventory

    gear = cycling_gear(
        temp_f=weather['temp_f'],
        feels_like_f=weather['feels_like_f'],
        wind_mph=weather['wind_mph'],
        precip_prob=weather['precip_prob'],
        weather_code=weather['weather_code'],
        owned_ids=owned_ids,
        pace_category=pace,
        duration_hours=duration,
    )

    verdict_text, verdict_class = VERDICT_LABEL[gear['verdict']]

    gear_items = []
    for key, icon in [
        ('bottoms',    '🩳'),
        ('jersey',     '👕'),
        ('base_layer', '🧥'),
        ('outer',      '🧥'),
        ('gloves',     '🧤'),
        ('head',       '🧢'),
        ('feet',       '👟'),
        ('eyewear',    '🕶️'),
    ]:
        val = gear.get(key)
        if val:
            gear_items.append({'icon': icon, 'label': val})
    for warmer in gear.get('warmers', []):
        gear_items.append({'icon': '💪', 'label': warmer})
    if gear.get('sun_sleeves'):
        gear_items.append({'icon': '☀️', 'label': gear['sun_sleeves']})

    return jsonify({
        'temp_f':        weather['temp_f'],
        'feels_like_f':  weather['feels_like_f'],
        'wind_mph':      weather['wind_mph'],
        'precip_prob':   weather['precip_prob'],
        'description':   weather['description'],
        'emoji':         weather['emoji'],
        'severity':      weather['severity'],
        'verdict':       gear['verdict'],
        'verdict_text':  verdict_text,
        'verdict_class': verdict_class,
        'gear':          gear_items,
        'notes':         gear.get('notes', []),
        'location_used': f'{round(lat, 3)}, {round(lng, 3)}',
    })
