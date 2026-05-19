"""
Tests for:
- Attendance recording on the ride roster (RideSignup.attended)
- Multi-group ride card on the calendar list view
"""
import pytest
from datetime import date, time, timedelta
from unittest.mock import patch

from app.models import Ride, RideSignup, ClubMembership


# ── Helpers ───────────────────────────────────────────────────────────────────

def _login(client, email, password='password123'):
    return client.post('/auth/login', data={'email': email, 'password': password},
                       follow_redirects=True)


def _past_ride(db, sample_club, days_ago=3):
    """Create a ride in the past."""
    ride = Ride(
        club_id=sample_club.id,
        title='Past Ride',
        date=date.today() - timedelta(days=days_ago),
        time=time(17, 0),
        meeting_location='HQ',
        distance_miles=30.0,
        pace_category='B',
    )
    db.session.add(ride)
    db.session.commit()
    return ride


def _signup(db, ride, user, waitlist=False):
    s = RideSignup(ride_id=ride.id, user_id=user.id, is_waitlist=waitlist)
    db.session.add(s)
    db.session.commit()
    return s


FAKE_WEATHER = {'description': 'Clear', 'emoji': '☀️', 'severity': 0,
                'temp_f': 70, 'wind_mph': 8, 'precip_prob': 0,
                'warning': False, 'warning_reasons': []}


# ── Attendance tests ──────────────────────────────────────────────────────────

class TestAttendance:

    def test_roster_shows_checkboxes_for_past_ride(self, client, db, sample_club,
                                                    club_admin_user, regular_user):
        """Past ride roster shows attendance checkboxes."""
        ride = _past_ride(db, sample_club)
        _signup(db, ride, regular_user)
        _login(client, club_admin_user.email)
        rv = client.get(f'/admin/clubs/{sample_club.slug}/rides/{ride.id}/roster')
        assert rv.status_code == 200
        assert b'Save Attendance' in rv.data
        assert b'type="checkbox"' in rv.data

    def test_roster_no_checkboxes_for_future_ride(self, client, db, sample_club,
                                                   club_admin_user, regular_user,
                                                   sample_rides):
        """Future ride roster does not show attendance checkboxes."""
        ride = sample_rides[0]
        _signup(db, ride, regular_user)
        _login(client, club_admin_user.email)
        rv = client.get(f'/admin/clubs/{sample_club.slug}/rides/{ride.id}/roster')
        assert rv.status_code == 200
        assert b'Save Attendance' not in rv.data

    def test_record_attendance_marks_attended(self, client, db, sample_club,
                                              club_admin_user, regular_user,
                                              second_user):
        """POST to /attendance sets attended=True for checked signups."""
        ride = _past_ride(db, sample_club)
        s1 = _signup(db, ride, regular_user)
        s2 = _signup(db, ride, second_user)
        _login(client, club_admin_user.email)
        rv = client.post(
            f'/admin/clubs/{sample_club.slug}/rides/{ride.id}/attendance',
            data={'attended': [s1.id]},   # s2 not checked
            follow_redirects=True,
        )
        assert rv.status_code == 200
        db.session.refresh(s1)
        db.session.refresh(s2)
        assert s1.attended is True
        assert s2.attended is False

    def test_record_attendance_no_attended(self, client, db, sample_club,
                                           club_admin_user, regular_user):
        """Submitting with no checkboxes marks all as False."""
        ride = _past_ride(db, sample_club)
        s = _signup(db, ride, regular_user)
        _login(client, club_admin_user.email)
        client.post(
            f'/admin/clubs/{sample_club.slug}/rides/{ride.id}/attendance',
            data={},
            follow_redirects=True,
        )
        db.session.refresh(s)
        assert s.attended is False

    def test_attendance_blocked_for_future_ride(self, client, db, sample_club,
                                                club_admin_user, sample_rides):
        """Cannot POST attendance for a future ride."""
        ride = sample_rides[0]
        _login(client, club_admin_user.email)
        rv = client.post(
            f'/admin/clubs/{sample_club.slug}/rides/{ride.id}/attendance',
            data={},
            follow_redirects=True,
        )
        assert rv.status_code == 200
        assert b'Attendance can only be recorded' in rv.data

    def test_attendance_requires_admin(self, client, db, sample_club, regular_user):
        """Non-admin cannot record attendance."""
        ride = _past_ride(db, sample_club)
        _login(client, regular_user.email)
        rv = client.post(
            f'/admin/clubs/{sample_club.slug}/rides/{ride.id}/attendance',
            data={},
            follow_redirects=True,
        )
        assert rv.status_code == 403

    def test_roster_attended_badge_count(self, client, db, sample_club,
                                          club_admin_user, regular_user, second_user):
        """Roster shows count of attended riders."""
        ride = _past_ride(db, sample_club)
        s1 = _signup(db, ride, regular_user)
        s1.attended = True
        _signup(db, ride, second_user)
        db.session.commit()
        _login(client, club_admin_user.email)
        rv = client.get(f'/admin/clubs/{sample_club.slug}/rides/{ride.id}/roster')
        assert b'1 attended' in rv.data

    def test_attendance_initial_state_is_none(self, db, sample_club, regular_user):
        """New signup has attended=None (not recorded)."""
        ride = _past_ride(db, sample_club)
        s = _signup(db, ride, regular_user)
        assert s.attended is None

    def test_waitlist_excluded_from_attendance(self, client, db, sample_club,
                                               club_admin_user, regular_user):
        """Waitlist signups are not shown in the attendance form."""
        ride = _past_ride(db, sample_club)
        s = _signup(db, ride, regular_user, waitlist=True)
        _login(client, club_admin_user.email)
        rv = client.post(
            f'/admin/clubs/{sample_club.slug}/rides/{ride.id}/attendance',
            data={'attended': [s.id]},
            follow_redirects=True,
        )
        # Waitlist signup attended should remain None
        db.session.refresh(s)
        assert s.attended is None


# ── Multi-group ride card tests ───────────────────────────────────────────────

class TestMultiGroupCard:

    def _make_future_rides_same_day(self, db, sample_club):
        """Create two rides on the same future date."""
        future = date.today() + timedelta(days=7)
        r1 = Ride(club_id=sample_club.id, title='A Group', date=future,
                  time=time(7, 0), meeting_location='HQ',
                  distance_miles=40, pace_category='A')
        r2 = Ride(club_id=sample_club.id, title='B Group', date=future,
                  time=time(7, 0), meeting_location='HQ',
                  distance_miles=30, pace_category='B')
        db.session.add_all([r1, r2])
        db.session.commit()
        return r1, r2

    @patch('app.routes.clubs.get_weather_for_rides', return_value={})
    def test_single_ride_renders_as_ride_row(self, mock_w, client, db,
                                              sample_club, sample_rides, regular_user):
        """When each day has one ride, ride-row class is used (no group card)."""
        _login(client, regular_user.email)
        rv = client.get(f'/clubs/{sample_club.slug}/rides/')
        assert rv.status_code == 200
        assert b'ride-row' in rv.data
        assert b'ride-group-card' not in rv.data

    @patch('app.routes.clubs.get_weather_for_rides', return_value={})
    def test_same_day_rides_render_as_group_card(self, mock_w, client, db,
                                                  sample_club, regular_user):
        """Two rides on the same day render as a collapsible group card."""
        _login(client, regular_user.email)
        self._make_future_rides_same_day(db, sample_club)
        rv = client.get(f'/clubs/{sample_club.slug}/rides/')
        assert rv.status_code == 200
        assert b'ride-group-card' in rv.data
        assert b'2 group rides' in rv.data

    @patch('app.routes.clubs.get_weather_for_rides', return_value={})
    def test_group_card_contains_both_rides(self, mock_w, client, db, sample_club, regular_user):
        """Both rides appear inside the collapsed section."""
        _login(client, regular_user.email)
        self._make_future_rides_same_day(db, sample_club)
        rv = client.get(f'/clubs/{sample_club.slug}/rides/')
        assert b'A Group' in rv.data
        assert b'B Group' in rv.data

    @patch('app.routes.clubs.get_weather_for_rides', return_value={})
    def test_group_card_has_collapse_target(self, mock_w, client, db, sample_club, regular_user):
        """Group card header has a Bootstrap data-bs-toggle collapse attribute."""
        _login(client, regular_user.email)
        self._make_future_rides_same_day(db, sample_club)
        rv = client.get(f'/clubs/{sample_club.slug}/rides/')
        assert b'data-bs-toggle="collapse"' in rv.data

    @patch('app.routes.clubs.get_weather_for_rides', return_value={})
    def test_mixed_days_separate_groups(self, mock_w, client, db, sample_club, regular_user):
        """A day with 2 rides and a day with 1 render correctly: one group card, one ride-row."""
        _login(client, regular_user.email)
        future = date.today() + timedelta(days=5)
        single = Ride(club_id=sample_club.id, title='Solo Ride', date=future,
                      time=time(7, 0), meeting_location='HQ',
                      distance_miles=25, pace_category='C')
        db.session.add(single)
        db.session.commit()
        self._make_future_rides_same_day(db, sample_club)
        rv = client.get(f'/clubs/{sample_club.slug}/rides/')
        assert b'ride-group-card' in rv.data
        # Solo Ride day renders a normal ride-row (not inside a group card)
        assert b'Solo Ride' in rv.data

    @patch('app.routes.clubs.get_weather_for_rides', return_value={})
    def test_pace_filter_can_reduce_group_to_single(self, mock_w, client, db,
                                                     sample_club, regular_user):
        """Filtering by pace=A on a 2-ride same-day group returns just the A ride as ride-row."""
        _login(client, regular_user.email)
        self._make_future_rides_same_day(db, sample_club)
        rv = client.get(f'/clubs/{sample_club.slug}/rides/?pace=A')
        assert rv.status_code == 200
        assert b'ride-group-card' not in rv.data
        assert b'A Group' in rv.data
        assert b'B Group' not in rv.data
