"""
Tests for model properties: RideWithGPS URL parsing, embed URLs, pace labels,
signup counts, Club helpers, User.is_club_admin, User.has_signed_waiver.
"""
import pytest
from datetime import date, time, timedelta
from app.models import Ride, RideSignup, User, Club, ClubAdmin, ClubWaiver, WaiverSignature
from app.extensions import bcrypt


def make_ride(db, club, **kwargs):
    defaults = dict(
        club_id=club.id,
        title='Test Ride',
        date=date.today() + timedelta(days=1),
        time=time(17, 0),
        meeting_location='Somewhere',
        distance_miles=20.0,
        pace_category='B',
    )
    defaults.update(kwargs)
    ride = Ride(**defaults)
    db.session.add(ride)
    db.session.commit()
    return ride


# ── RideWithGPS ───────────────────────────────────────────────────────────────

class TestRideWithGPS:
    def test_route_id_extracted(self, app, db, sample_club):
        ride = make_ride(db, sample_club, route_url='https://ridewithgps.com/routes/12345678')
        assert ride.ridewithgps_route_id == '12345678'

    def test_route_id_none_if_no_url(self, app, db, sample_club):
        ride = make_ride(db, sample_club)
        assert ride.ridewithgps_route_id is None

    def test_route_id_none_for_non_rwgps_url(self, app, db, sample_club):
        ride = make_ride(db, sample_club, route_url='https://strava.com/routes/99')
        assert ride.ridewithgps_route_id is None

    def test_embed_url_format(self, app, db, sample_club):
        ride = make_ride(db, sample_club, route_url='https://ridewithgps.com/routes/99887766')
        assert ride.ridewithgps_embed_url == (
            'https://ridewithgps.com/embeds?type=route&id=99887766'
            '&sampleGraph=true&distanceMarkers=true'
        )

    def test_embed_url_none_if_no_route(self, app, db, sample_club):
        ride = make_ride(db, sample_club)
        assert ride.ridewithgps_embed_url is None

    def test_map_image_url(self, app, db, sample_club):
        ride = make_ride(db, sample_club, route_url='https://ridewithgps.com/routes/111')
        assert ride.ridewithgps_map_image_url == 'https://ridewithgps.com/routes/111/hover_preview.png'

    def test_map_image_url_none_if_no_route(self, app, db, sample_club):
        ride = make_ride(db, sample_club)
        assert ride.ridewithgps_map_image_url is None


# ── Video embed URL ───────────────────────────────────────────────────────────

class TestEmbedUrl:
    def test_youtube_watch_url(self, app, db, sample_club):
        ride = make_ride(db, sample_club, video_url='https://www.youtube.com/watch?v=dQw4w9WgXcQ')
        assert ride.embed_url == 'https://www.youtube.com/embed/dQw4w9WgXcQ'

    def test_youtu_be_short_url(self, app, db, sample_club):
        ride = make_ride(db, sample_club, video_url='https://youtu.be/dQw4w9WgXcQ')
        assert ride.embed_url == 'https://www.youtube.com/embed/dQw4w9WgXcQ'

    def test_vimeo_url(self, app, db, sample_club):
        ride = make_ride(db, sample_club, video_url='https://vimeo.com/123456789')
        assert ride.embed_url == 'https://player.vimeo.com/video/123456789'

    def test_no_video_url_returns_none(self, app, db, sample_club):
        ride = make_ride(db, sample_club)
        assert ride.embed_url is None


# ── Pace labels ───────────────────────────────────────────────────────────────

class TestPaceLabel:
    @pytest.mark.parametrize('pace,expected', [
        ('A', 'A — Fast (22+ mph)'),
        ('B', 'B — Moderate (18–22 mph)'),
        ('C', 'C — Casual (14–18 mph)'),
        ('D', 'D — Beginner (<14 mph)'),
        ('X', 'X'),
    ])
    def test_pace_labels(self, app, db, sample_club, pace, expected):
        ride = make_ride(db, sample_club, pace_category=pace)
        assert ride.pace_label == expected

    def test_multi_pace_summary_and_labels(self, app, db, sample_club):
        ride = make_ride(
            db,
            sample_club,
            pace_category='A',
            is_multi_pace=True,
            pace_categories=['A', 'B', 'C'],
        )
        assert ride.display_pace_categories == ['A', 'B', 'C']
        assert ride.pace_summary == 'A / B / C'
        assert ride.pace_label == 'A / B / C — Multiple paces'
        assert ride.pace_detail_labels == [
            'A — Fast (22+ mph)',
            'B — Moderate (18–22 mph)',
            'C — Casual (14–18 mph)',
        ]


# ── Signup count ──────────────────────────────────────────────────────────────

class TestSignupCount:
    def test_zero_by_default(self, app, db, sample_club):
        ride = make_ride(db, sample_club)
        assert ride.signup_count == 0

    def test_increments_with_signups(self, app, db, sample_club, regular_user, second_user):
        ride = make_ride(db, sample_club)
        db.session.add(RideSignup(ride_id=ride.id, user_id=regular_user.id))
        db.session.add(RideSignup(ride_id=ride.id, user_id=second_user.id))
        db.session.commit()
        assert ride.signup_count == 2


# ── Club model ────────────────────────────────────────────────────────────────

class TestClubModel:
    def test_member_count(self, app, db, sample_club, regular_user):
        from app.models import ClubMembership
        assert sample_club.member_count == 0
        db.session.add(ClubMembership(user_id=regular_user.id, club_id=sample_club.id))
        db.session.commit()
        assert sample_club.member_count == 1

    def test_current_waiver_none_if_none_exists(self, app, db, sample_club):
        assert sample_club.current_waiver is None

    def test_current_waiver_returns_latest(self, app, db, sample_club, club_waiver):
        assert sample_club.current_waiver == club_waiver


# ── User.is_club_admin ────────────────────────────────────────────────────────

class TestIsClubAdmin:
    def test_club_admin_user_returns_true(self, app, db, sample_club, club_admin_user):
        assert club_admin_user.is_club_admin(sample_club) is True

    def test_regular_user_returns_false(self, app, db, sample_club, regular_user):
        assert regular_user.is_club_admin(sample_club) is False

    def test_superadmin_returns_true_for_any_club(self, app, db, sample_club, admin_user):
        assert admin_user.is_club_admin(sample_club) is True

    def test_admin_of_one_club_not_another(self, app, db, sample_club, second_club, club_admin_user):
        assert club_admin_user.is_club_admin(sample_club) is True
        assert club_admin_user.is_club_admin(second_club) is False


# ── User.has_signed_waiver ────────────────────────────────────────────────────

class TestHasSignedWaiver:
    def test_false_if_not_signed(self, app, db, sample_club, regular_user, club_waiver):
        assert regular_user.has_signed_waiver(sample_club) is False

    def test_true_after_signing(self, app, db, sample_club, regular_user, club_waiver):
        yr = date.today().year
        db.session.add(WaiverSignature(
            user_id=regular_user.id, club_id=sample_club.id,
            waiver_id=club_waiver.id, year=yr,
        ))
        db.session.commit()
        assert regular_user.has_signed_waiver(sample_club) is True

    def test_false_after_waiver_updated(self, app, db, sample_club, regular_user, club_waiver):
        # User signed the old waiver; club then publishes a new waiver version
        yr = date.today().year
        db.session.add(WaiverSignature(
            user_id=regular_user.id, club_id=sample_club.id,
            waiver_id=club_waiver.id, year=yr,
        ))
        db.session.commit()
        # Simulate admin publishing an updated waiver (new DB row = new id)
        new_waiver = ClubWaiver(
            club_id=sample_club.id, year=yr,
            title='Updated Waiver', body='Updated terms.',
        )
        db.session.add(new_waiver)
        db.session.commit()
        # current_waiver is the newest one; user has not signed it yet
        assert regular_user.has_signed_waiver(sample_club) is False
