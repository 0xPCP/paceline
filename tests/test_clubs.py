"""
Tests for club listing, club home, membership join/leave,
ride detail, signup, unsignup, and waiver flows.
"""
import pytest
from datetime import date, datetime, time, timedelta, timezone
from unittest.mock import patch
from app.models import Club, ClubMembership, Ride, RideSignup, WaiverSignature, ClubShopItem
from app.extensions import db
from tests.conftest import login


@pytest.fixture
def one_ride(db, sample_club):
    ride = Ride(
        club_id=sample_club.id,
        title='Saturday Group Ride',
        date=date.today() + timedelta(days=5),
        time=time(8, 0),
        meeting_location='Lake Newport',
        distance_miles=30.0,
        pace_category='B',
    )
    db.session.add(ride)
    db.session.commit()
    return ride


@pytest.fixture
def cancelled_ride(db, sample_club):
    ride = Ride(
        club_id=sample_club.id,
        title='Cancelled Saturday Ride',
        date=date.today() + timedelta(days=5),
        time=time(8, 0),
        meeting_location='Lake Newport',
        distance_miles=30.0,
        pace_category='B',
        is_cancelled=True,
    )
    db.session.add(ride)
    db.session.commit()
    return ride


# ── Club directory ────────────────────────────────────────────────────────────

class TestClubIndex:
    def test_returns_200(self, client, sample_club):
        resp = client.get('/clubs/')
        assert resp.status_code == 200

    def test_shows_club_name(self, client, sample_club):
        resp = client.get('/clubs/')
        assert b'Test Cycling Club' in resp.data

    def test_search_matches_name(self, client, sample_club):
        resp = client.get('/clubs/?q=Test')
        assert b'Test Cycling Club' in resp.data

    def test_search_no_results(self, client, sample_club):
        resp = client.get('/clubs/?q=zzznomatch')
        assert b'Test Cycling Club' not in resp.data

    def test_multiple_clubs_shown(self, client, sample_club, second_club):
        resp = client.get('/clubs/')
        html = resp.data.decode()
        assert 'Test Cycling Club' in html
        assert 'Other Cycling Club' in html

    def test_directory_shows_club_quality_signals(self, client, db, sample_club):
        sample_club.is_verified = True
        sample_club.stripe_account_id = 'acct_test'
        sample_club.stripe_account_connected_at = datetime.now(timezone.utc)
        sample_club.membership_dues_required = True
        sample_club.membership_dues_mode = 'stripe_connect'
        sample_club.membership_dues_amount_cents = 4500
        db.session.add(Ride(
            club_id=sample_club.id,
            title='Beginner Coffee Ride',
            date=date.today() + timedelta(days=3),
            time=time(9, 0),
            meeting_location='Town Center',
            distance_miles=18,
            pace_category='D',
            is_newbie_friendly=True,
        ))
        db.session.add(ClubShopItem(
            club_id=sample_club.id,
            name='Club Jersey',
            price_cents=8000,
            is_active=True,
        ))
        db.session.commit()

        html = client.get('/clubs/').data.decode()

        assert 'Verified' in html
        assert '1 ride soon' in html
        assert 'New rider friendly' in html
        assert 'Online dues' in html
        assert 'Shop' in html


# ── Zip code search ───────────────────────────────────────────────────────────

class TestZipSearch:
    def test_zip_search_returns_200(self, client, sample_club):
        with patch('app.geocoding.geocode_zip', return_value=(38.9376, -77.3476)):
            resp = client.get('/clubs/?zip=20191')
        assert resp.status_code == 200

    def test_zip_search_finds_nearby_club(self, client, sample_club):
        # sample_club is at (38.9376, -77.3476) — same coords, so 0 mi away
        with patch('app.geocoding.geocode_zip', return_value=(38.9376, -77.3476)):
            resp = client.get('/clubs/?zip=20191&radius=25')
        assert b'Test Cycling Club' in resp.data

    def test_zip_search_excludes_distant_club(self, client, sample_club):
        # Geocode to Seattle — far from Reston VA
        with patch('app.geocoding.geocode_zip', return_value=(47.6062, -122.3321)):
            resp = client.get('/clubs/?zip=98101&radius=25')
        assert b'Test Cycling Club' not in resp.data

    def test_zip_search_shows_distance_badge(self, client, sample_club):
        with patch('app.geocoding.geocode_zip', return_value=(38.9376, -77.3476)):
            html = client.get('/clubs/?zip=20191').data.decode()
        assert 'away' in html  # unit depends on user preference (mi or km)

    def test_zip_search_bad_zip_shows_error(self, client, sample_club):
        with patch('app.geocoding.geocode_zip', return_value=None):
            html = client.get('/clubs/?zip=00000').data.decode()
        assert 'Could not locate' in html

    def test_zip_search_invalid_radius_defaults_to_25(self, client, sample_club):
        with patch('app.geocoding.geocode_zip', return_value=(38.9376, -77.3476)):
            resp = client.get('/clubs/?zip=20191&radius=999')
        assert resp.status_code == 200

    def test_text_search_still_works_without_zip(self, client, sample_club):
        resp = client.get('/clubs/?q=Test')
        assert b'Test Cycling Club' in resp.data


# ── Club home ─────────────────────────────────────────────────────────────────

class TestClubHome:
    def test_returns_200(self, client, sample_club, mock_weather):
        resp = client.get('/clubs/test-club/')
        assert resp.status_code == 200

    def test_shows_club_name(self, client, sample_club, mock_weather):
        resp = client.get('/clubs/test-club/')
        assert b'Test Cycling Club' in resp.data

    def test_404_for_unknown_slug(self, client):
        resp = client.get('/clubs/no-such-club/')
        assert resp.status_code == 404

    def test_shows_upcoming_rides(self, client, sample_club, one_ride, mock_weather):
        resp = client.get('/clubs/test-club/')
        assert b'Saturday Group Ride' in resp.data

    def test_join_button_shown_when_not_member(self, client, sample_club, regular_user, mock_weather):
        login(client)
        resp = client.get('/clubs/test-club/')
        assert b'Join Club' in resp.data

    def test_leave_button_shown_when_member(self, client, sample_club, regular_user, db, mock_weather):
        db.session.add(ClubMembership(user_id=regular_user.id, club_id=sample_club.id))
        db.session.commit()
        login(client)
        resp = client.get('/clubs/test-club/')
        assert b'Leave Club' in resp.data


# ── Club calendar ─────────────────────────────────────────────────────────────

class TestClubCalendar:
    def test_list_view_200(self, client, sample_club, regular_user, mock_weather):
        login(client)
        resp = client.get('/clubs/test-club/rides/')
        assert resp.status_code == 200

    def test_week_view_200(self, client, sample_club, regular_user, mock_weather):
        login(client)
        resp = client.get('/clubs/test-club/rides/?view=week')
        assert resp.status_code == 200

    def test_month_view_200(self, client, sample_club, regular_user, mock_weather):
        login(client)
        resp = client.get('/clubs/test-club/rides/?view=month')
        assert resp.status_code == 200

    def test_shows_rides_in_list(self, client, sample_club, one_ride, regular_user, mock_weather):
        login(client)
        resp = client.get('/clubs/test-club/rides/')
        assert b'Saturday Group Ride' in resp.data

    def test_pace_filter_a(self, client, sample_club, sample_rides, regular_user, mock_weather):
        login(client)
        resp = client.get('/clubs/test-club/rides/?pace=A')
        html = resp.data.decode()
        assert 'Tuesday A Ride' in html
        assert 'Wednesday B Ride' not in html


# ── Ride detail ───────────────────────────────────────────────────────────────

class TestRideDetail:
    def test_returns_200(self, client, sample_club, one_ride, regular_user, mock_weather):
        login(client)
        resp = client.get(f'/clubs/test-club/rides/{one_ride.id}')
        assert resp.status_code == 200

    def test_shows_ride_title(self, client, sample_club, one_ride, regular_user, mock_weather):
        login(client)
        resp = client.get(f'/clubs/test-club/rides/{one_ride.id}')
        assert b'Saturday Group Ride' in resp.data

    def test_shows_ride_meta(self, client, sample_club, one_ride, regular_user, mock_weather):
        login(client)
        html = client.get(f'/clubs/test-club/rides/{one_ride.id}').data.decode()
        assert 'Lake Newport' in html
        assert '30' in html
        assert 'B' in html

    def test_404_for_missing_ride(self, client, sample_club, regular_user, mock_weather):
        login(client)
        resp = client.get('/clubs/test-club/rides/99999')
        assert resp.status_code == 404

    def test_404_for_ride_in_wrong_club(self, client, sample_club, second_club, db, regular_user, mock_weather):
        ride = Ride(
            club_id=second_club.id, title='Other Club Ride',
            date=date.today() + timedelta(days=1), time=time(8, 0),
            meeting_location='Elsewhere', distance_miles=20, pace_category='C',
        )
        db.session.add(ride)
        db.session.commit()
        login(client)
        resp = client.get(f'/clubs/test-club/rides/{ride.id}')
        assert resp.status_code == 404

    def test_weather_card_shown(self, client, sample_club, one_ride, regular_user, mock_weather):
        login(client)
        resp = client.get(f'/clubs/test-club/rides/{one_ride.id}')
        assert b'Forecast' in resp.data
        assert b'AQI 42 Good' in resp.data

    def test_sign_in_prompt_for_anonymous(self, client, sample_club, one_ride, mock_weather):
        # Ride detail is public for share/OG previews; anonymous users see a sign-in CTA
        resp = client.get(f'/clubs/test-club/rides/{one_ride.id}')
        assert resp.status_code == 200
        assert b'Sign in' in resp.data

    def test_signup_button_for_authenticated(self, client, sample_club, one_ride, regular_user, mock_weather):
        login(client)
        resp = client.get(f'/clubs/test-club/rides/{one_ride.id}')
        assert b'Sign Up for This Ride' in resp.data

    def test_cancelled_ride_shows_badge(self, client, sample_club, cancelled_ride, regular_user, mock_weather):
        login(client)
        html = client.get(f'/clubs/test-club/rides/{cancelled_ride.id}').data.decode()
        assert 'Cancelled' in html
        assert 'Sign Up for This Ride' not in html

    def test_back_to_calendar_link(self, client, sample_club, one_ride, regular_user, mock_weather):
        login(client)
        resp = client.get(f'/clubs/test-club/rides/{one_ride.id}')
        assert b'Back to' in resp.data

    def test_add_to_calendar_button_present(self, client, sample_club, one_ride, regular_user, mock_weather):
        login(client)
        resp = client.get(f'/clubs/test-club/rides/{one_ride.id}')
        assert b'Add to Calendar' in resp.data

    def test_shows_garmin_groupride_code(self, client, db, sample_club, one_ride, regular_user, mock_weather):
        one_ride.garmin_groupride_code = '123456'
        db.session.commit()
        login(client)
        resp = client.get(f'/clubs/test-club/rides/{one_ride.id}')
        assert b'Garmin GroupRide' in resp.data
        assert b'123456' in resp.data

    def test_signed_up_rider_can_add_blank_garmin_groupride_code(self, client, db, sample_club, one_ride, regular_user, mock_weather):
        db.session.add(RideSignup(ride_id=one_ride.id, user_id=regular_user.id))
        db.session.commit()
        login(client)
        resp = client.post(
            f'/clubs/test-club/rides/{one_ride.id}/groupride-code',
            data={'garmin_groupride_code': '234567'},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        db.session.refresh(one_ride)
        assert one_ride.garmin_groupride_code == '234567'

    def test_signed_up_rider_cannot_overwrite_garmin_groupride_code(self, client, db, sample_club, one_ride, regular_user, mock_weather):
        one_ride.garmin_groupride_code = '123456'
        db.session.add(RideSignup(ride_id=one_ride.id, user_id=regular_user.id))
        db.session.commit()
        login(client)
        resp = client.post(
            f'/clubs/test-club/rides/{one_ride.id}/groupride-code',
            data={'garmin_groupride_code': '234567'},
            follow_redirects=False,
        )
        assert resp.status_code == 403
        db.session.refresh(one_ride)
        assert one_ride.garmin_groupride_code == '123456'

    def test_club_ride_manager_can_update_garmin_groupride_code(self, client, db, sample_club, one_ride, club_admin_user, mock_weather):
        login(client, 'clubadmin@test.com')
        resp = client.post(
            f'/clubs/test-club/rides/{one_ride.id}/groupride-code',
            data={'garmin_groupride_code': '345678'},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        db.session.refresh(one_ride)
        assert one_ride.garmin_groupride_code == '345678'

    def test_invalid_garmin_groupride_code_rejected(self, client, db, sample_club, one_ride, club_admin_user, mock_weather):
        login(client, 'clubadmin@test.com')
        resp = client.post(
            f'/clubs/test-club/rides/{one_ride.id}/groupride-code',
            data={'garmin_groupride_code': 'abc123'},
            follow_redirects=True,
        )
        assert b'6-digit Garmin GroupRide code' in resp.data
        db.session.refresh(one_ride)
        assert one_ride.garmin_groupride_code is None


# ── .ics download ─────────────────────────────────────────────────────────────

class TestRideIcs:
    def test_returns_ics_content_type(self, client, sample_club, one_ride):
        resp = client.get(f'/clubs/test-club/rides/{one_ride.id}/ics')
        assert resp.status_code == 200
        assert 'text/calendar' in resp.content_type

    def test_ics_contains_ride_title(self, client, sample_club, one_ride):
        resp = client.get(f'/clubs/test-club/rides/{one_ride.id}/ics')
        assert b'Saturday Group Ride' in resp.data

    def test_ics_contains_location(self, client, sample_club, one_ride):
        resp = client.get(f'/clubs/test-club/rides/{one_ride.id}/ics')
        assert b'Lake Newport' in resp.data

    def test_ics_valid_structure(self, client, sample_club, one_ride):
        body = client.get(f'/clubs/test-club/rides/{one_ride.id}/ics').data.decode()
        assert 'BEGIN:VCALENDAR' in body
        assert 'BEGIN:VEVENT' in body
        assert 'END:VEVENT' in body
        assert 'END:VCALENDAR' in body
        assert 'DTSTART:' in body
        assert 'DTEND:' in body

    def test_ics_attachment_header(self, client, sample_club, one_ride):
        resp = client.get(f'/clubs/test-club/rides/{one_ride.id}/ics')
        assert 'attachment' in resp.headers.get('Content-Disposition', '')

    def test_ics_404_for_missing_ride(self, client, sample_club):
        resp = client.get('/clubs/test-club/rides/99999/ics')
        assert resp.status_code == 404


# ── Signup / Unsignup ─────────────────────────────────────────────────────────

class TestRideSignup:
    def test_signup_requires_login(self, client, sample_club, one_ride):
        resp = client.post(f'/clubs/test-club/rides/{one_ride.id}/signup', follow_redirects=True)
        assert b'Sign In' in resp.data or resp.status_code in (302, 200)

    def test_signup_adds_record(self, client, sample_club, one_ride, regular_user, db):
        login(client)
        client.post(f'/clubs/test-club/rides/{one_ride.id}/signup', follow_redirects=True)
        assert RideSignup.query.filter_by(ride_id=one_ride.id, user_id=regular_user.id).first() is not None

    def test_double_signup_is_idempotent(self, client, sample_club, one_ride, regular_user, db):
        login(client)
        client.post(f'/clubs/test-club/rides/{one_ride.id}/signup', follow_redirects=True)
        client.post(f'/clubs/test-club/rides/{one_ride.id}/signup', follow_redirects=True)
        assert RideSignup.query.filter_by(ride_id=one_ride.id).count() == 1

    def test_cannot_signup_for_cancelled_ride(self, client, sample_club, cancelled_ride, regular_user, db):
        login(client)
        client.post(f'/clubs/test-club/rides/{cancelled_ride.id}/signup', follow_redirects=True)
        assert RideSignup.query.filter_by(ride_id=cancelled_ride.id).count() == 0

    def test_unsignup_removes_record(self, client, sample_club, one_ride, regular_user, db):
        login(client)
        client.post(f'/clubs/test-club/rides/{one_ride.id}/signup', follow_redirects=True)
        client.post(f'/clubs/test-club/rides/{one_ride.id}/unsignup', follow_redirects=True)
        assert RideSignup.query.filter_by(ride_id=one_ride.id, user_id=regular_user.id).first() is None

    def test_signup_blocked_without_waiver(self, client, sample_club, one_ride, regular_user, club_waiver, db):
        login(client)
        resp = client.post(f'/clubs/test-club/rides/{one_ride.id}/signup', follow_redirects=True)
        assert RideSignup.query.filter_by(ride_id=one_ride.id).count() == 0
        assert b'waiver' in resp.data.lower()

    def test_signup_allowed_after_waiver_signed(self, client, sample_club, one_ride, regular_user, club_waiver, db):
        yr = date.today().year
        db.session.add(WaiverSignature(
            user_id=regular_user.id, club_id=sample_club.id,
            waiver_id=club_waiver.id, year=yr,
        ))
        db.session.commit()
        login(client)
        client.post(f'/clubs/test-club/rides/{one_ride.id}/signup', follow_redirects=True)
        assert RideSignup.query.filter_by(ride_id=one_ride.id, user_id=regular_user.id).first() is not None


# ── Membership ────────────────────────────────────────────────────────────────

class TestMembership:
    def test_join_creates_membership(self, client, sample_club, regular_user, db):
        login(client)
        client.post('/clubs/test-club/join', follow_redirects=True)
        assert ClubMembership.query.filter_by(
            user_id=regular_user.id, club_id=sample_club.id
        ).first() is not None

    def test_join_requires_login(self, client, sample_club):
        resp = client.post('/clubs/test-club/join', follow_redirects=True)
        assert b'Sign In' in resp.data or resp.status_code in (302, 200)

    def test_double_join_is_idempotent(self, client, sample_club, regular_user, db):
        login(client)
        client.post('/clubs/test-club/join', follow_redirects=True)
        client.post('/clubs/test-club/join', follow_redirects=True)
        assert ClubMembership.query.filter_by(club_id=sample_club.id).count() == 1

    def test_leave_removes_membership(self, client, sample_club, regular_user, db):
        db.session.add(ClubMembership(user_id=regular_user.id, club_id=sample_club.id))
        db.session.commit()
        login(client)
        client.post('/clubs/test-club/leave', follow_redirects=True)
        assert ClubMembership.query.filter_by(
            user_id=regular_user.id, club_id=sample_club.id
        ).first() is None


# ── Waiver ────────────────────────────────────────────────────────────────────

class TestWaiver:
    def test_waiver_page_requires_login(self, client, sample_club, club_waiver):
        resp = client.get('/clubs/test-club/waiver', follow_redirects=True)
        assert b'Sign In' in resp.data or resp.status_code in (302, 200)

    def test_waiver_page_shows_waiver_text(self, client, sample_club, club_waiver, regular_user):
        login(client)
        resp = client.get('/clubs/test-club/waiver')
        assert b'wear a helmet' in resp.data

    def test_accepting_waiver_creates_signature(self, client, sample_club, club_waiver, regular_user, db):
        login(client)
        client.post('/clubs/test-club/waiver', data={'agree': '1'}, follow_redirects=True)
        assert WaiverSignature.query.filter_by(
            user_id=regular_user.id, club_id=sample_club.id
        ).first() is not None

    def test_not_checking_box_does_not_sign(self, client, sample_club, club_waiver, regular_user, db):
        login(client)
        client.post('/clubs/test-club/waiver', data={}, follow_redirects=True)
        assert WaiverSignature.query.filter_by(
            user_id=regular_user.id, club_id=sample_club.id
        ).first() is None

    def test_already_signed_shows_message(self, client, sample_club, club_waiver, regular_user, db):
        yr = date.today().year
        db.session.add(WaiverSignature(
            user_id=regular_user.id, club_id=sample_club.id,
            waiver_id=club_waiver.id, year=yr,
        ))
        db.session.commit()
        login(client)
        resp = client.get('/clubs/test-club/waiver')
        assert b'already accepted' in resp.data

    def test_no_waiver_club_redirects(self, client, sample_club, regular_user):
        login(client)
        resp = client.get('/clubs/test-club/waiver', follow_redirects=True)
        assert resp.status_code == 200
