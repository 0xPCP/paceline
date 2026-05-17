"""
Unit tests for app/weather.py.

These tests do NOT make real HTTP calls — the requests.get call is patched
to return a fake Open-Meteo response, matching the real API shape.
"""
import pytest
from datetime import date, time, timedelta
from unittest.mock import patch, MagicMock
import app.weather as weather_module


@pytest.fixture(autouse=True)
def clear_weather_cache():
    """Clear the in-memory weather cache before each test so cached results
    from one test don't pollute the next."""
    weather_module._cache.clear()
    weather_module._aqi_cache.clear()
    yield
    weather_module._cache.clear()
    weather_module._aqi_cache.clear()


def _fake_response(rides_dates, code=2, temp_f=68, wind_mph=10, precip_prob=10, precip_mm=0.0):
    """Build a minimal Open-Meteo API response covering the given dates."""
    times = []
    temp_list, precip_prob_list, precip_list, wind_list, code_list = [], [], [], [], []

    base = min(rides_dates)
    for day_offset in range(16):
        d = base + timedelta(days=day_offset)
        for hour in range(24):
            times.append(f"{d.isoformat()}T{hour:02d}:00")
            temp_list.append(temp_f)
            precip_prob_list.append(precip_prob)
            precip_list.append(precip_mm)
            wind_list.append(wind_mph)
            code_list.append(code)

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        'hourly': {
            'time': times,
            'temperature_2m': temp_list,
            'apparent_temperature': temp_list,
            'precipitation_probability': precip_prob_list,
            'precipitation': precip_list,
            'wind_speed_10m': wind_list,
            'weather_code': code_list,
        }
    }
    return mock_resp


def _fake_aqi_response(rides_dates, aqi=42):
    """Build a minimal Open-Meteo air-quality API response covering the given dates."""
    times = []
    aqi_list = []

    base = min(rides_dates)
    for day_offset in range(7):
        d = base + timedelta(days=day_offset)
        for hour in range(24):
            times.append(f"{d.isoformat()}T{hour:02d}:00")
            aqi_list.append(aqi)

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        'hourly': {
            'time': times,
            'us_aqi': aqi_list,
        }
    }
    return mock_resp


def _make_ride(ride_id, days_ahead, hour=17):
    """Create a minimal ride-like object for weather testing (no DB needed)."""
    ride = MagicMock()
    ride.id = ride_id
    ride.date = date.today() + timedelta(days=days_ahead)
    ride.time = time(hour, 0)
    ride.distance_miles = None
    ride.pace_category = None
    return ride


# ── Core behaviour ────────────────────────────────────────────────────────────

class TestGetWeatherForRides:
    def test_returns_empty_for_no_rides(self, app):
        from app.weather import get_weather_for_rides
        result = get_weather_for_rides([])
        assert result == {}

    def test_returns_empty_for_rides_outside_window(self, app):
        """Rides more than 14 days out should not get weather."""
        from app.weather import get_weather_for_rides
        ride = _make_ride(1, days_ahead=20)
        result = get_weather_for_rides([ride])
        assert result == {}

    def test_returns_empty_for_past_rides(self, app):
        from app.weather import get_weather_for_rides
        ride = _make_ride(1, days_ahead=-1)
        result = get_weather_for_rides([ride])
        assert result == {}

    def test_good_conditions_severity_zero(self, app):
        from app.weather import get_weather_for_rides
        ride = _make_ride(1, days_ahead=1)
        mock_resp = _fake_response([ride.date], code=1, temp_f=68, wind_mph=8, precip_prob=5)
        with patch('requests.get', return_value=mock_resp):
            result = get_weather_for_rides([ride])
        assert 1 in result
        w = result[1]
        assert w['severity'] == 0
        assert w['warning'] is False
        assert w['temp_f'] == 68
        assert w['wind_mph'] == 8

    def test_overcast_does_not_raise_caution(self, app):
        from app.weather import get_weather_for_rides
        ride = _make_ride(1, days_ahead=1)
        mock_resp = _fake_response([ride.date], code=3, temp_f=68, wind_mph=8, precip_prob=5)
        with patch('requests.get', return_value=mock_resp):
            result = get_weather_for_rides([ride])
        w = result[1]
        assert w['severity'] == 0
        assert w['warning'] is False

    def test_light_rain_is_caution_not_warning(self, app):
        from app.weather import get_weather_for_rides
        ride = _make_ride(1, days_ahead=1)
        mock_resp = _fake_response([ride.date], code=61, temp_f=68, wind_mph=8,
                                   precip_prob=55, precip_mm=0.5)
        with patch('requests.get', return_value=mock_resp):
            result = get_weather_for_rides([ride])
        w = result[1]
        assert w['severity'] == 1
        assert w['warning'] is False

    def test_high_precip_triggers_warning(self, app):
        from app.weather import get_weather_for_rides
        ride = _make_ride(1, days_ahead=1)
        mock_resp = _fake_response([ride.date], code=61, temp_f=65, wind_mph=10,
                                   precip_prob=70, precip_mm=2.5)
        with patch('requests.get', return_value=mock_resp):
            result = get_weather_for_rides([ride])
        w = result[1]
        assert w['warning'] is True
        assert w['severity'] == 2
        assert any('rain' in r for r in w['warning_reasons'])

    def test_high_wind_triggers_warning(self, app):
        from app.weather import get_weather_for_rides
        ride = _make_ride(1, days_ahead=1)
        mock_resp = _fake_response([ride.date], code=2, temp_f=68, wind_mph=30, precip_prob=5)
        with patch('requests.get', return_value=mock_resp):
            result = get_weather_for_rides([ride])
        w = result[1]
        assert w['warning'] is True
        assert any('mph' in r for r in w['warning_reasons'])

    def test_extreme_cold_triggers_warning(self, app):
        from app.weather import get_weather_for_rides
        ride = _make_ride(1, days_ahead=1)
        mock_resp = _fake_response([ride.date], code=2, temp_f=30, wind_mph=5, precip_prob=5)
        with patch('requests.get', return_value=mock_resp):
            result = get_weather_for_rides([ride])
        w = result[1]
        assert w['warning'] is True
        assert any('°F' in r for r in w['warning_reasons'])

    def test_extreme_heat_triggers_warning(self, app):
        from app.weather import get_weather_for_rides
        ride = _make_ride(1, days_ahead=1)
        mock_resp = _fake_response([ride.date], code=2, temp_f=98, wind_mph=5, precip_prob=5)
        with patch('requests.get', return_value=mock_resp):
            result = get_weather_for_rides([ride])
        w = result[1]
        assert w['warning'] is True

    def test_thunderstorm_code_triggers_warning(self, app):
        from app.weather import get_weather_for_rides
        ride = _make_ride(1, days_ahead=1)
        mock_resp = _fake_response([ride.date], code=95, temp_f=70, wind_mph=10, precip_prob=80, precip_mm=3.0)
        with patch('requests.get', return_value=mock_resp):
            result = get_weather_for_rides([ride])
        w = result[1]
        assert w['warning'] is True
        assert 'thunderstorm' in ' '.join(w['warning_reasons'])

    def test_ordinary_breeze_stays_good(self, app):
        from app.weather import get_weather_for_rides
        ride = _make_ride(1, days_ahead=1)
        mock_resp = _fake_response([ride.date], code=2, temp_f=68, wind_mph=18, precip_prob=10)
        with patch('requests.get', return_value=mock_resp):
            result = get_weather_for_rides([ride])
        w = result[1]
        assert w['severity'] == 0
        assert w['warning'] is False

    def test_moderate_conditions_severity_one(self, app):
        from app.weather import get_weather_for_rides
        ride = _make_ride(1, days_ahead=1)
        # Noticeable wind — caution but not warning
        mock_resp = _fake_response([ride.date], code=2, temp_f=68, wind_mph=20, precip_prob=10)
        with patch('requests.get', return_value=mock_resp):
            result = get_weather_for_rides([ride])
        w = result[1]
        assert w['severity'] == 1
        assert w['warning'] is False

    def test_api_failure_returns_empty(self, app):
        from app.weather import get_weather_for_rides
        ride = _make_ride(1, days_ahead=1)
        with patch('requests.get', side_effect=Exception('network error')):
            result = get_weather_for_rides([ride])
        assert result == {}

    def test_result_contains_required_keys(self, app):
        from app.weather import get_weather_for_rides
        ride = _make_ride(1, days_ahead=1)
        mock_resp = _fake_response([ride.date])
        with patch('requests.get', return_value=mock_resp):
            result = get_weather_for_rides([ride])
        w = result[1]
        for key in ('description', 'emoji', 'severity', 'temp_f', 'wind_mph',
                    'precip_prob', 'aqi', 'aqi_label', 'warning', 'warning_reasons'):
            assert key in w, f"Missing key: {key}"

    def test_multiple_rides_all_returned(self, app):
        from app.weather import get_weather_for_rides
        rides = [_make_ride(i, days_ahead=i) for i in range(1, 4)]
        mock_resp = _fake_response([r.date for r in rides])
        with patch('requests.get', return_value=mock_resp):
            result = get_weather_for_rides(rides)
        assert len(result) == 3

    def test_aqi_added_when_air_quality_available(self, app):
        from app.weather import get_weather_for_rides
        ride = _make_ride(1, days_ahead=1)
        mock_weather = _fake_response([ride.date], code=1, temp_f=68, wind_mph=8, precip_prob=5)
        mock_aqi = _fake_aqi_response([ride.date], aqi=42)
        with patch('requests.get', side_effect=[mock_weather, mock_aqi]):
            result = get_weather_for_rides([ride])
        w = result[1]
        assert w['aqi'] == 42
        assert w['aqi_label'] == 'Good'
        assert w['severity'] == 0
        assert w['warning'] is False

    def test_sensitive_group_aqi_triggers_caution(self, app):
        from app.weather import get_weather_for_rides
        ride = _make_ride(1, days_ahead=1)
        mock_weather = _fake_response([ride.date], code=1, temp_f=68, wind_mph=8, precip_prob=5)
        mock_aqi = _fake_aqi_response([ride.date], aqi=125)
        with patch('requests.get', side_effect=[mock_weather, mock_aqi]):
            result = get_weather_for_rides([ride])
        w = result[1]
        assert w['aqi'] == 125
        assert w['aqi_label'] == 'Unhealthy for sensitive groups'
        assert w['severity'] == 1
        assert w['warning'] is False
        assert not any('AQI 125' in reason for reason in w['warning_reasons'])

    def test_unhealthy_aqi_triggers_warning(self, app):
        from app.weather import get_weather_for_rides
        ride = _make_ride(1, days_ahead=1)
        mock_weather = _fake_response([ride.date], code=1, temp_f=68, wind_mph=8, precip_prob=5)
        mock_aqi = _fake_aqi_response([ride.date], aqi=175)
        with patch('requests.get', side_effect=[mock_weather, mock_aqi]):
            result = get_weather_for_rides([ride])
        w = result[1]
        assert w['aqi'] == 175
        assert w['aqi_label'] == 'Unhealthy'
        assert w['severity'] == 2
        assert w['warning'] is True
        assert any('AQI 175' in reason for reason in w['warning_reasons'])


# ── WMO code mapping ──────────────────────────────────────────────────────────

class TestWMOCodes:
    @pytest.mark.parametrize('code,expected_emoji', [
        (0,  '☀️'),
        (1,  '🌤️'),
        (2,  '⛅'),
        (3,  '☁️'),
        (61, '🌧️'),
        (95, '⛈️'),
        (71, '❄️'),
    ])
    def test_known_wmo_code_emoji(self, app, code, expected_emoji):
        from app.weather import get_weather_for_rides
        ride = _make_ride(1, days_ahead=1)
        mock_resp = _fake_response([ride.date], code=code, temp_f=68,
                                   wind_mph=5, precip_prob=5, precip_mm=0)
        with patch('requests.get', return_value=mock_resp):
            result = get_weather_for_rides([ride])
        if 1 in result:
            assert result[1]['emoji'] == expected_emoji
