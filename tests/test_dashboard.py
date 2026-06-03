"""
Tests for dashboard signup button visibility based on dues and waiver status.
"""
import pytest
from datetime import date, time, timedelta

from app.models import ClubMembership, ClubWaiver, WaiverSignature, Ride, RideSignup
from .conftest import login


def make_future_ride(db, club):
    ride = Ride(
        club_id=club.id,
        title='Club Ride',
        date=date.today() + timedelta(days=3),
        time=time(8, 0),
        meeting_location='Test Location',
        distance_miles=25.0,
        pace_category='B',
        ride_type='road',
    )
    db.session.add(ride)
    db.session.commit()
    return ride


def join_club(db, user, club, status='active'):
    db.session.add(ClubMembership(user_id=user.id, club_id=club.id, status=status))
    db.session.commit()


def sign_waiver(db, user, club, waiver):
    db.session.add(WaiverSignature(
        user_id=user.id, club_id=club.id,
        waiver_id=waiver.id, year=date.today().year,
    ))
    db.session.commit()


class TestDashboardSignupButton:
    def test_new_user_dashboard_shows_onboarding_checklist(
            self, client, regular_user, mock_weather):
        login(client)
        r = client.get('/', follow_redirects=True)
        assert r.status_code == 200
        assert b'data-testid="dashboard-onboarding-checklist"' in r.data
        assert b'Add your location' in r.data
        assert b'Join your first club' in r.data

    def test_completed_user_dashboard_hides_onboarding_checklist(
            self, client, db, sample_club, regular_user, mock_weather):
        regular_user.zip_code = '20191'
        regular_user.profile_photo_key = 'avatars/test.jpg'
        regular_user.recommendation_ride_types = ['road']
        join_club(db, regular_user, sample_club)
        ride = make_future_ride(db, sample_club)
        db.session.add(RideSignup(ride_id=ride.id, user_id=regular_user.id))
        db.session.commit()

        login(client)
        r = client.get('/', follow_redirects=True)
        assert r.status_code == 200
        assert b'data-testid="dashboard-onboarding-checklist"' not in r.data

    def test_dashboard_shows_weekly_tss_goal_progress(
            self, client, db, sample_club, regular_user, mock_weather):
        regular_user.training_goal_mode = 'weekly_tss'
        regular_user.training_goal_value = 100
        ride = Ride(
            club_id=sample_club.id,
            title='Completed Training Ride',
            date=date.today(),
            time=time(8, 0),
            meeting_location='Test Location',
            distance_miles=20.0,
            elevation_feet=0,
            pace_category='B',
            ride_type='training',
        )
        db.session.add(ride)
        db.session.flush()
        db.session.add(RideSignup(ride_id=ride.id, user_id=regular_user.id, attended=True))
        db.session.commit()

        login(client)
        r = client.get('/', follow_redirects=True)
        assert r.status_code == 200
        assert b'Weekly TSS Goal' in r.data
        assert b'50% of 100 weekly TSS' in r.data
        assert b'50 TSS remaining' in r.data
        assert b'Last week' in r.data
        assert b'Under goal' in r.data
        assert b'100 TSS short' in r.data

    def test_dashboard_converts_ctl_goal_to_weekly_tss(
            self, client, db, regular_user, mock_weather):
        regular_user.training_goal_mode = 'ctl'
        regular_user.training_goal_value = 10
        db.session.commit()

        login(client)
        r = client.get('/', follow_redirects=True)
        assert r.status_code == 200
        assert b'0% of 70 weekly TSS' in r.data
        assert b'Goal CTL 10 converts to 70 TSS/week.' in r.data

    def test_dashboard_highlights_last_week_over_goal(
            self, client, db, sample_club, regular_user, mock_weather):
        regular_user.training_goal_mode = 'weekly_tss'
        regular_user.training_goal_value = 100
        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        ride = Ride(
            club_id=sample_club.id,
            title='Last Week Big Ride',
            date=week_start - timedelta(days=1),
            time=time(8, 0),
            meeting_location='Test Location',
            distance_miles=50.0,
            elevation_feet=0,
            pace_category='B',
            ride_type='training',
        )
        db.session.add(ride)
        db.session.flush()
        db.session.add(RideSignup(ride_id=ride.id, user_id=regular_user.id))
        db.session.commit()

        login(client)
        r = client.get('/', follow_redirects=True)
        assert r.status_code == 200
        assert b'Last week' in r.data
        assert b'Hit goal' in r.data
        assert b'25 TSS over' in r.data

    def test_signup_button_shown_active_member_no_waiver(
            self, client, db, app, sample_club, regular_user, mock_weather):
        """Active member, club has no waiver → Sign Up button shown."""
        join_club(db, regular_user, sample_club)
        make_future_ride(db, sample_club)
        login(client)
        r = client.get('/', follow_redirects=True)
        assert b'Sign Up' in r.data

    def test_signup_button_shown_active_member_waiver_signed(
            self, client, db, app, sample_club, regular_user, club_waiver, mock_weather):
        """Active member who has signed current waiver → Sign Up button shown."""
        join_club(db, regular_user, sample_club)
        make_future_ride(db, sample_club)
        sign_waiver(db, regular_user, sample_club, club_waiver)
        login(client)
        r = client.get('/', follow_redirects=True)
        assert b'Sign Up' in r.data

    def test_waiver_prompt_when_not_signed(
            self, client, db, app, sample_club, regular_user, club_waiver, mock_weather):
        """Active member who has NOT signed waiver → waiver prompt, no Sign Up."""
        join_club(db, regular_user, sample_club)
        make_future_ride(db, sample_club)
        login(client)
        r = client.get('/', follow_redirects=True)
        assert b'Sign Waiver First' in r.data
        assert b'Sign Up' not in r.data

    def test_dues_badge_shown_when_pending(
            self, client, db, app, sample_club, regular_user, mock_weather):
        """Pending (not active) member → dues expired badge shown."""
        join_club(db, regular_user, sample_club, status='pending')
        make_future_ride(db, sample_club)
        login(client)
        r = client.get('/', follow_redirects=True)
        assert b'Dues expired' in r.data
        assert b'Sign Up' not in r.data

    def test_waiver_prompt_after_waiver_updated(
            self, client, db, app, sample_club, regular_user, club_waiver, mock_weather):
        """User signed old waiver; club updated it → waiver prompt shown again."""
        join_club(db, regular_user, sample_club)
        make_future_ride(db, sample_club)
        sign_waiver(db, regular_user, sample_club, club_waiver)
        # Club publishes a new waiver version
        new_waiver = ClubWaiver(
            club_id=sample_club.id, year=date.today().year,
            title='Updated Waiver', body='New terms.',
        )
        db.session.add(new_waiver)
        db.session.commit()
        login(client)
        r = client.get('/', follow_redirects=True)
        assert b'Sign Waiver First' in r.data
        assert b'Sign Up' not in r.data

    def test_no_signup_button_for_personal_rides(
            self, client, db, app, sample_club, regular_user, second_user, mock_weather):
        """Rides owned by a user (owner_id set) have no signup button on dashboard."""
        join_club(db, regular_user, sample_club)
        ride = Ride(
            owner_id=second_user.id,
            title='Personal Ride',
            date=date.today() + timedelta(days=3),
            time=time(8, 0),
            meeting_location='Test Location',
            distance_miles=20.0,
            pace_category='B',
            ride_type='road',
        )
        db.session.add(ride)
        # Sign up regular_user for the personal ride so it appears in my_rides
        db.session.commit()
        signup = RideSignup(ride_id=ride.id, user_id=regular_user.id)
        db.session.add(signup)
        db.session.commit()
        login(client)
        r = client.get('/', follow_redirects=True)
        assert b'Sign Up' not in r.data
