"""
Weather for RBC rides using the Open-Meteo API (free, no API key required).
Makes one bulk API call per page view covering all rides in the displayed range.
Results cached for 30 minutes.
"""
import time
import requests
from datetime import date, datetime, timezone

# All RBC rides are within a ~5-mile radius — one forecast point covers everything.
# Reston, VA centroid.
_LAT = 38.9586
_LNG = -77.3570

# WMO weather interpretation codes → (label, emoji, base_severity)
# severity: 0 = good, 1 = caution, 2 = warning
_WMO = {
    0:  ('Clear',           '☀️',  0),
    1:  ('Mainly clear',    '🌤️', 0),
    2:  ('Partly cloudy',   '⛅',  0),
    3:  ('Overcast',        '☁️',  0),
    45: ('Fog',             '🌫️', 0),
    48: ('Freezing fog',    '🌫️', 1),
    51: ('Light drizzle',   '🌦️', 0),
    53: ('Drizzle',         '🌦️', 0),
    55: ('Heavy drizzle',   '🌧️', 1),
    61: ('Light rain',      '🌧️', 1),
    63: ('Rain',            '🌧️', 1),
    65: ('Heavy rain',      '🌧️', 2),
    71: ('Light snow',      '❄️',  1),
    73: ('Snow',            '❄️',  2),
    75: ('Heavy snow',      '❄️',  2),
    77: ('Snow grains',     '❄️',  2),
    80: ('Rain showers',    '🌧️', 1),
    81: ('Rain showers',    '🌧️', 1),
    82: ('Heavy showers',   '🌧️', 2),
    85: ('Snow showers',    '❄️',  2),
    86: ('Heavy snow',      '❄️',  2),
    95: ('Thunderstorm',    '⛈️',  2),
    96: ('Thunderstorm',    '⛈️',  2),
    99: ('Thunderstorm',    '⛈️',  2),
}

# Cache: key → {hourly: {...}, _ts: float}
_cache = {}
_aqi_cache = {}


def _fetch_hourly(lat, lng, forecast_days):
    """Fetch and cache hourly forecast data for a lat/lng. Returns hourly dict or {}."""
    cache_key = (round(lat, 3), round(lng, 3), forecast_days)
    now = time.time()
    if cache_key in _cache and now - _cache[cache_key]['_ts'] < 1800:
        return _cache[cache_key]['hourly']
    try:
        resp = requests.get(
            'https://api.open-meteo.com/v1/forecast',
            params={
                'latitude':        lat,
                'longitude':       lng,
                'hourly':          'temperature_2m,precipitation_probability,precipitation,wind_speed_10m,weather_code',
                'temperature_unit':'fahrenheit',
                'wind_speed_unit': 'mph',
                'forecast_days':   forecast_days,
                'timezone':        'auto',
            },
            timeout=10,
        )
        data = resp.json()
    except Exception:
        return {}
    hourly = {}
    for i, t in enumerate(data['hourly']['time']):
        temp   = data['hourly']['temperature_2m'][i]
        wind   = data['hourly']['wind_speed_10m'][i]
        if temp is None or wind is None:
            continue
        hourly[t] = {
            'temp_f':      round(temp),
            'precip_prob': data['hourly']['precipitation_probability'][i] or 0,
            'precip_mm':   data['hourly']['precipitation'][i] or 0,
            'wind_mph':    round(wind),
            'code':        data['hourly']['weather_code'][i],
        }
    _cache[cache_key] = {'hourly': hourly, '_ts': now}
    return hourly


def _fetch_hourly_aqi(lat, lng, forecast_days):
    """Fetch and cache hourly U.S. AQI forecast data for a lat/lng."""
    # Open-Meteo's air-quality forecast is shorter than weather forecast.
    forecast_days = min(forecast_days, 7)
    cache_key = (round(lat, 3), round(lng, 3), forecast_days)
    now = time.time()
    if cache_key in _aqi_cache and now - _aqi_cache[cache_key]['_ts'] < 1800:
        return _aqi_cache[cache_key]['hourly']
    try:
        resp = requests.get(
            'https://air-quality-api.open-meteo.com/v1/air-quality',
            params={
                'latitude':      lat,
                'longitude':     lng,
                'hourly':        'us_aqi',
                'forecast_days': forecast_days,
                'timezone':      'auto',
            },
            timeout=10,
        )
        hourly_data = resp.json().get('hourly', {})
        times = hourly_data.get('time', [])
        values = hourly_data.get('us_aqi', [])
    except Exception:
        return {}

    hourly = {}
    for i, t in enumerate(times):
        if i >= len(values) or values[i] is None:
            continue
        hourly[t] = round(values[i])
    _aqi_cache[cache_key] = {'hourly': hourly, '_ts': now}
    return hourly


def _aqi_category(aqi):
    if aqi is None:
        return None, 0
    if aqi <= 50:
        return 'Good', 0
    if aqi <= 100:
        return 'Moderate', 0
    if aqi <= 150:
        return 'Unhealthy for sensitive groups', 1
    if aqi <= 200:
        return 'Unhealthy', 2
    if aqi <= 300:
        return 'Very unhealthy', 2
    return 'Hazardous', 2


def get_weather_for_rides(rides, lat=None, lng=None):
    """
    Return {ride.id: weather_dict} for rides within the next 14 days.
    Uses lat/lng if provided, otherwise falls back to module-level defaults.
    """
    lat = lat if lat is not None else _LAT
    lng = lng if lng is not None else _LNG

    today = date.today()
    in_window = [r for r in rides if 0 <= (r.date - today).days <= 14]
    if not in_window:
        return {}

    dates = sorted({r.date for r in in_window})
    forecast_days = min((dates[-1] - today).days + 2, 16)

    hourly = _fetch_hourly(lat, lng, forecast_days)
    if not hourly:
        return {}
    hourly_aqi = _fetch_hourly_aqi(lat, lng, forecast_days)

    result = {}
    for ride in in_window:
        key = f"{ride.date.isoformat()}T{ride.time.hour:02d}:00"
        h = hourly.get(key)
        if not h:
            continue

        desc, emoji, code_sev = _WMO.get(h['code'], ('Unknown', '❓', 1))

        warnings = []
        if h['precip_prob'] >= 70 and h['precip_mm'] >= 1:
            warnings.append(f"{h['precip_prob']}% chance of rain")
        if h['wind_mph'] >= 30:
            warnings.append(f"{h['wind_mph']} mph winds")
        if h['temp_f'] <= 32:
            warnings.append(f"{h['temp_f']}°F — dress in layers")
        if h['temp_f'] >= 98:
            warnings.append(f"{h['temp_f']}°F — extreme heat")
        if h['code'] >= 95:
            warnings.append('thunderstorm possible')

        aqi = hourly_aqi.get(key)
        aqi_label, aqi_sev = _aqi_category(aqi)
        if aqi is not None and aqi_sev >= 2:
            warnings.append(f"AQI {aqi} ({aqi_label})")

        if warnings:
            sev = max(code_sev, aqi_sev, 2)
        elif h['precip_prob'] >= 50 or h['wind_mph'] >= 20 or h['temp_f'] <= 38 or h['temp_f'] >= 92:
            sev = max(code_sev, aqi_sev, 1)
        else:
            sev = max(code_sev, aqi_sev)

        result[ride.id] = {
            'description':    desc,
            'emoji':          emoji,
            'severity':       sev,
            'temp_f':         h['temp_f'],
            'wind_mph':       h['wind_mph'],
            'precip_prob':    h['precip_prob'],
            'aqi':            aqi,
            'aqi_label':      aqi_label,
            'warning':        bool(warnings),
            'warning_reasons': warnings,
        }

    return result


# Cache for current-conditions widget: key=(lat_r, lng_r) → {data, _ts}
_widget_cache = {}


def get_current_weather(lat: float, lng: float) -> dict | None:
    """
    Fetch current-hour weather for an arbitrary lat/lng.
    Returns a dict with temp_f, feels_like_f, wind_mph, precip_prob,
    weather_code, description, emoji, severity — or None on failure.
    Cached 15 minutes per location (rounded to 2 decimal places).
    """
    key = (round(lat, 2), round(lng, 2))
    now = time.time()
    if key in _widget_cache and now - _widget_cache[key]['_ts'] < 900:
        return _widget_cache[key]['data']

    try:
        resp = requests.get(
            'https://api.open-meteo.com/v1/forecast',
            params={
                'latitude':         lat,
                'longitude':        lng,
                'current':          'temperature_2m,apparent_temperature,precipitation_probability,wind_speed_10m,weather_code',
                'temperature_unit': 'fahrenheit',
                'wind_speed_unit':  'mph',
                'timezone':         'auto',
            },
            timeout=8,
        )
        c = resp.json().get('current', {})
    except Exception:
        return None

    code = c.get('weather_code', 0)
    desc, emoji, sev = _WMO.get(code, ('Unknown', '❓', 1))

    data = {
        'temp_f':       round(c.get('temperature_2m', 0)),
        'feels_like_f': round(c.get('apparent_temperature', 0)),
        'wind_mph':     round(c.get('wind_speed_10m', 0)),
        'precip_prob':  c.get('precipitation_probability') or 0,
        'weather_code': code,
        'description':  desc,
        'emoji':        emoji,
        'severity':     sev,
    }
    _widget_cache[key] = {'data': data, '_ts': now}
    return data
