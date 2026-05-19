"""
Tests for club calendar views: list, week, and month.
All views are now club-scoped at /clubs/<slug>/rides/.
Calendar views require authentication (v0.121).
"""
from datetime import date, timedelta
import pytest
from tests.conftest import login


BASE = '/clubs/test-club/rides/'


# ── List view ─────────────────────────────────────────────────────────────────

class TestListView:
    @pytest.fixture(autouse=True)
    def _auto_login(self, client, regular_user):
        login(client)

    def test_returns_200(self, client, sample_club, mock_weather):
        resp = client.get(BASE)
        assert resp.status_code == 200

    def test_view_switcher_present(self, client, sample_club, mock_weather):
        html = client.get(BASE).data.decode()
        assert 'cal-toolbar' in html
        assert '>List<' in html
        assert '>Week<' in html
        assert '>Month<' in html

    def test_shows_upcoming_rides(self, client, sample_club, sample_rides, mock_weather):
        html = client.get(BASE).data.decode()
        assert 'Tuesday A Ride' in html
        assert 'Wednesday B Ride' in html

    def test_cancelled_badge_shown(self, client, sample_club, sample_rides, mock_weather):
        html = client.get(BASE).data.decode()
        assert 'Thursday C Ride' in html
        assert 'Cancelled' in html

    def test_pace_filter_a(self, client, sample_club, sample_rides, mock_weather):
        html = client.get(BASE + '?pace=A').data.decode()
        assert 'Tuesday A Ride' in html
        assert 'Wednesday B Ride' not in html

    def test_pace_filter_b(self, client, sample_club, sample_rides, mock_weather):
        html = client.get(BASE + '?pace=B').data.decode()
        assert 'Wednesday B Ride' in html
        assert 'Tuesday A Ride' not in html

    def test_pace_filter_invalid_ignored(self, client, sample_club, sample_rides, mock_weather):
        resp = client.get(BASE + '?pace=Z')
        assert resp.status_code == 200
        assert 'Tuesday A Ride' in resp.data.decode()

    def test_weather_shown_in_row(self, client, sample_club, sample_rides, mock_weather):
        html = client.get(BASE).data.decode()
        assert 'list-weather' in html
        assert '68' in html
        assert 'AQI 42' in html

    def test_empty_state_no_rides(self, client, sample_club, mock_weather):
        resp = client.get(BASE)
        assert resp.status_code == 200
        assert b'No upcoming rides' in resp.data

    def test_month_heading_groups_rides(self, client, sample_club, sample_rides, mock_weather):
        html = client.get(BASE).data.decode()
        assert 'month-heading' in html


# ── Week view ─────────────────────────────────────────────────────────────────

class TestWeekView:
    @pytest.fixture(autouse=True)
    def _auto_login(self, client, regular_user):
        login(client)

    def test_returns_200(self, client, sample_club, mock_weather):
        resp = client.get(BASE + '?view=week')
        assert resp.status_code == 200

    def test_renders_week_grid(self, client, sample_club, mock_weather):
        html = client.get(BASE + '?view=week').data.decode()
        assert 'week-grid' in html

    def test_seven_columns(self, client, sample_club, mock_weather):
        html = client.get(BASE + '?view=week').data.decode()
        assert html.count('week-col') >= 7

    def test_shows_rides_this_week(self, client, sample_club, sample_rides, mock_weather):
        today = date.today()
        next_monday = today + timedelta(days=7 - today.weekday())
        html = client.get(f'{BASE}?view=week&start={next_monday.isoformat()}').data.decode()
        assert 'Tuesday A Ride' in html
        assert 'Wednesday B Ride' in html

    def test_prev_next_navigation_links(self, client, sample_club, mock_weather):
        html = client.get(BASE + '?view=week').data.decode()
        assert 'Prev' in html
        assert 'Next' in html
        assert 'view=week' in html

    def test_invalid_start_date_falls_back(self, client, sample_club, mock_weather):
        resp = client.get(BASE + '?view=week&start=not-a-date')
        assert resp.status_code == 200
        assert b'week-grid' in resp.data

    def test_today_column_highlighted(self, client, sample_club, mock_weather):
        html = client.get(BASE + '?view=week').data.decode()
        assert 'week-col-today' in html

    def test_weather_legend_present(self, client, sample_club, mock_weather):
        assert b'weather-legend' in client.get(BASE + '?view=week').data


# ── Month view ────────────────────────────────────────────────────────────────

class TestMonthView:
    @pytest.fixture(autouse=True)
    def _auto_login(self, client, regular_user):
        login(client)

    def test_returns_200(self, client, sample_club, mock_weather):
        assert client.get(BASE + '?view=month').status_code == 200

    def test_renders_month_grid(self, client, sample_club, mock_weather):
        assert 'month-grid' in client.get(BASE + '?view=month').data.decode()

    def test_day_of_week_headers(self, client, sample_club, mock_weather):
        html = client.get(BASE + '?view=month').data.decode()
        for dow in ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']:
            assert dow in html

    def test_shows_current_month_name(self, client, sample_club, mock_weather):
        import calendar
        today = date.today()
        month_name = calendar.month_name[today.month]
        assert month_name.encode() in client.get(BASE + '?view=month').data

    def test_explicit_year_month(self, client, sample_club, mock_weather):
        resp = client.get(BASE + '?view=month&y=2026&m=5')
        assert resp.status_code == 200
        assert b'May 2026' in resp.data

    def test_rides_appear_in_correct_cell(self, client, sample_club, sample_rides, mock_weather):
        today = date.today()
        next_monday = today + timedelta(days=7 - today.weekday())
        ride_date = next_monday + timedelta(days=1)  # next Tuesday
        html = client.get(f'{BASE}?view=month&y={ride_date.year}&m={ride_date.month}').data.decode()
        assert 'cell-ride' in html

    def test_prev_next_navigation_links(self, client, sample_club, mock_weather):
        html = client.get(BASE + '?view=month').data.decode()
        assert 'Prev' in html and 'Next' in html and 'view=month' in html

    def test_today_cell_highlighted(self, client, sample_club, mock_weather):
        assert b'is-today' in client.get(BASE + '?view=month').data

    def test_invalid_month_clamped(self, client, sample_club, mock_weather):
        assert client.get(BASE + '?view=month&y=2026&m=99').status_code == 200

    def test_other_month_days_marked(self, client, sample_club, mock_weather):
        assert b'other-month' in client.get(BASE + '?view=month').data

    def test_weather_legend_present(self, client, sample_club, mock_weather):
        assert b'weather-legend' in client.get(BASE + '?view=month').data

    def test_cancelled_ride_marked(self, client, sample_club, sample_rides, mock_weather):
        today = date.today()
        next_monday = today + timedelta(days=7 - today.weekday())
        ride_date = next_monday + timedelta(days=3)  # next Thursday (cancelled ride)
        html = client.get(f'{BASE}?view=month&y={ride_date.year}&m={ride_date.month}').data.decode()
        assert 'cell-cancelled' in html
