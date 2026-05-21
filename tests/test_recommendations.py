from datetime import date, time, timedelta

from app.models import Club, ClubMembership, Ride, RideSignup, UserRecommendationHidden
from app.recommendations import (
    allowed_ride_types_for_user,
    recommend_clubs_for_user,
    recommend_rides_for_user,
)
from tests.conftest import login


def _ride(db, club, *, title, days=3, ride_type='road', pace='B', virtual=False):
    ride = Ride(
        club_id=club.id,
        title=title,
        date=date.today() + timedelta(days=days),
        time=time(8, 0),
        distance_miles=35,
        elevation_feet=1000,
        pace_category=pace,
        ride_type=ride_type,
        is_virtual=virtual,
    )
    db.session.add(ride)
    db.session.commit()
    return ride


def test_recommendations_exclude_rides_on_days_user_is_already_riding(db, sample_club, regular_user):
    joined_ride = _ride(db, sample_club, title='Already Going', days=4, ride_type='road')
    same_day = _ride(db, sample_club, title='Same Day Candidate', days=4, ride_type='road')
    other_day = _ride(db, sample_club, title='Other Day Candidate', days=5, ride_type='road')
    db.session.add(RideSignup(user_id=regular_user.id, ride_id=joined_ride.id))
    db.session.commit()

    recs = recommend_rides_for_user(regular_user, today=date.today(), limit=10)
    rec_ids = {rec.ride.id for rec in recs}

    assert same_day.id not in rec_ids
    assert other_day.id in rec_ids


def test_explicit_ride_type_preferences_are_hard_filter(db, sample_club, regular_user):
    regular_user.recommendation_ride_types = ['road']
    road = _ride(db, sample_club, title='Road Candidate', ride_type='road')
    gravel = _ride(db, sample_club, title='Gravel Candidate', ride_type='gravel')
    virtual = _ride(db, sample_club, title='Virtual Candidate', ride_type='training', virtual=True)
    db.session.commit()

    recs = recommend_rides_for_user(regular_user, today=date.today(), limit=10)
    rec_ids = {rec.ride.id for rec in recs}

    assert road.id in rec_ids
    assert gravel.id not in rec_ids
    assert virtual.id not in rec_ids


def test_virtual_is_only_inferred_after_virtual_history(db, sample_club, regular_user):
    assert 'virtual' not in allowed_ride_types_for_user(regular_user, today=date.today())

    past_virtual = Ride(
        club_id=sample_club.id,
        title='Past Virtual',
        date=date.today() - timedelta(days=10),
        time=time(18, 0),
        distance_miles=20,
        pace_category='C',
        ride_type='training',
        is_virtual=True,
    )
    db.session.add(past_virtual)
    db.session.flush()
    db.session.add(RideSignup(user_id=regular_user.id, ride_id=past_virtual.id))
    db.session.commit()

    assert 'virtual' in allowed_ride_types_for_user(regular_user, today=date.today())


def test_hidden_recommendation_is_excluded(db, sample_club, regular_user):
    ride = _ride(db, sample_club, title='Hide Me', ride_type='road')
    db.session.add(UserRecommendationHidden(
        user_id=regular_user.id,
        target_type='ride',
        target_id=ride.id,
    ))
    db.session.commit()

    recs = recommend_rides_for_user(regular_user, today=date.today(), limit=10)

    assert ride.id not in {rec.ride.id for rec in recs}


def test_club_recommendations_skip_joined_clubs_and_match_type(db, sample_club, second_club, regular_user):
    sample_club.is_verified = True
    second_club.is_hidden = False
    second_club.is_verified = True
    regular_user.recommendation_ride_types = ['gravel']
    db.session.add(ClubMembership(user_id=regular_user.id, club_id=sample_club.id, status='active'))
    _ride(db, sample_club, title='Joined Club Gravel', ride_type='gravel')
    _ride(db, second_club, title='Other Club Gravel', ride_type='gravel')
    db.session.commit()

    recs = recommend_clubs_for_user(regular_user, today=date.today(), limit=10)
    rec_ids = {rec.club.id for rec in recs}

    assert sample_club.id not in rec_ids
    assert second_club.id in rec_ids


def test_dashboard_shows_recommendations_and_hide_controls(client, db, sample_club, regular_user, mock_weather):
    _ride(db, sample_club, title='Recommended Road Ride', ride_type='road')
    login(client, regular_user.email)

    response = client.get('/')

    assert response.status_code == 200
    assert b'Recommended for You' in response.data
    assert b'Recommended Road Ride' in response.data
    assert b'Not for me' in response.data


def test_profile_saves_recommendation_preferences(client, db, regular_user):
    login(client, regular_user.email)
    response = client.post(
        '/auth/profile',
        data={
            'username': regular_user.username,
            'email': regular_user.email,
            'zip_code': regular_user.zip_code or '',
            'gender': '',
            'bio': '',
            'strava_profile_url': '',
            'language': '',
            'emergency_contact_name': '',
            'emergency_contact_phone': '',
            'recommendations_enabled': 'y',
            'recommendation_location_enabled': 'y',
            'recommendation_history_enabled': 'y',
            'recommendation_ride_types': ['road', 'gravel'],
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    db.session.refresh(regular_user)
    assert regular_user.recommendations_enabled is True
    assert regular_user.recommendation_friend_activity_enabled is False
    assert regular_user.recommendation_ride_types == ['road', 'gravel']
