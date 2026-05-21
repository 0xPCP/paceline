from dataclasses import dataclass
from datetime import date, timedelta

from .extensions import db
from .geocoding import haversine_miles
from .models import (
    Club,
    ClubMembership,
    Ride,
    RideSignup,
    UserFriend,
    UserRecommendationHidden,
)

DEFAULT_RIDE_TYPES = ['road', 'gravel']
RIDE_TYPE_LABELS = {
    'road': 'Road',
    'gravel': 'Gravel',
    'social': 'Social',
    'training': 'Training',
    'event': 'Event',
    'night': 'Night',
    'virtual': 'Virtual',
}


@dataclass
class RideRecommendation:
    ride: Ride
    score: int
    reason: str
    distance_miles: float | None = None


@dataclass
class ClubRecommendation:
    club: Club
    score: int
    reason: str
    distance_miles: float | None = None
    upcoming_count: int = 0


def _hidden_ids(user, target_type):
    rows = UserRecommendationHidden.query.filter_by(
        user_id=user.id,
        target_type=target_type,
    ).all()
    return {row.target_id for row in rows}


def _signed_up_ride_ids_and_dates(user, today):
    signups = (RideSignup.query
               .filter_by(user_id=user.id)
               .join(Ride, RideSignup.ride_id == Ride.id)
               .filter(Ride.date >= today, Ride.is_cancelled == False)  # noqa: E712
               .all())
    return {s.ride_id for s in signups}, {s.ride.date for s in signups}


def _active_club_ids(user):
    rows = ClubMembership.query.filter_by(user_id=user.id, status='active').all()
    return {row.club_id for row in rows}


def _friend_ids(user):
    return set(user.accepted_friend_ids())


def _friend_counts(ride_ids, friend_ids):
    if not ride_ids or not friend_ids:
        return {}
    rows = (RideSignup.query
            .filter(RideSignup.ride_id.in_(ride_ids),
                    RideSignup.user_id.in_(friend_ids),
                    RideSignup.is_waitlist == False,   # noqa: E712
                    RideSignup.is_anonymous == False)  # noqa: E712
            .all())
    counts = {}
    for row in rows:
        counts[row.ride_id] = counts.get(row.ride_id, 0) + 1
    return counts


def _history_traits(user, today):
    signups = (RideSignup.query
               .filter_by(user_id=user.id, is_waitlist=False)
               .join(Ride, RideSignup.ride_id == Ride.id)
               .filter(Ride.date < today, Ride.is_cancelled == False)  # noqa: E712
               .order_by(Ride.date.desc())
               .limit(50)
               .all())
    pace_counts = {}
    type_counts = {}
    for signup in signups:
        ride = signup.ride
        pace_counts[ride.pace_category] = pace_counts.get(ride.pace_category, 0) + 1
        ride_type = 'virtual' if ride.is_virtual else (ride.ride_type or 'road')
        type_counts[ride_type] = type_counts.get(ride_type, 0) + 1
    return pace_counts, type_counts


def allowed_ride_types_for_user(user, today=None):
    today = today or date.today()
    explicit = user.preferred_ride_types
    if explicit:
        return explicit
    if user.recommendation_history_enabled:
        _, type_counts = _history_traits(user, today)
        if type_counts:
            return sorted(type_counts, key=type_counts.get, reverse=True)
    return list(DEFAULT_RIDE_TYPES)


def _distance_to_club(user, club):
    if not user.recommendation_location_enabled:
        return None
    if user.lat is None or user.lng is None or club.lat is None or club.lng is None:
        return None
    return haversine_miles(user.lat, user.lng, club.lat, club.lng)


def _reason_for_ride(ride, *, distance, pace_match, type_match, friend_count, in_joined_club):
    if friend_count:
        return f'{friend_count} friend{"s" if friend_count != 1 else ""} going'
    if in_joined_club:
        return 'From one of your clubs'
    if pace_match and type_match:
        return f'{RIDE_TYPE_LABELS.get("virtual" if ride.is_virtual else (ride.ride_type or "road"), "Ride")} ride at a pace you ride'
    if distance is not None and distance <= 25:
        return f'Near your saved location'
    if pace_match:
        return 'Similar pace to rides you joined'
    return 'Upcoming ride that matches your preferences'


def recommend_rides_for_user(user, *, today=None, limit=5):
    today = today or date.today()
    if not user.recommendations_enabled:
        return []

    hidden = _hidden_ids(user, 'ride')
    signed_up_ids, signed_up_dates = _signed_up_ride_ids_and_dates(user, today)
    joined_club_ids = _active_club_ids(user)
    allowed_types = set(allowed_ride_types_for_user(user, today))
    pace_counts, type_counts = _history_traits(user, today) if user.recommendation_history_enabled else ({}, {})
    friend_ids = _friend_ids(user) if user.recommendation_friend_activity_enabled else set()

    horizon = today + timedelta(days=30)
    rides = (Ride.query
             .filter(Ride.date >= today,
                     Ride.date <= horizon,
                     Ride.is_cancelled == False)  # noqa: E712
             .order_by(Ride.date.asc(), Ride.time.asc())
             .limit(250)
             .all())
    friend_counts = _friend_counts([r.id for r in rides], friend_ids)

    recs = []
    for ride in rides:
        if ride.id in hidden or ride.id in signed_up_ids:
            continue
        if ride.date in signed_up_dates:
            continue
        if ride.is_full:
            continue

        ride_type = 'virtual' if ride.is_virtual else (ride.ride_type or 'road')
        if ride_type not in allowed_types:
            continue

        if ride.club_id:
            club = ride.club
            if not club or not club.is_active or club.is_hidden:
                continue
            if club.normalized_sport_type not in user.preferred_sports:
                continue
            if club.is_private and club.id not in joined_club_ids:
                continue
        elif ride.owner_id:
            if ride.is_private:
                continue
            club = None
        else:
            continue

        distance = _distance_to_club(user, club) if club else None
        score = 0
        if ride.club_id in joined_club_ids:
            score += 35
        if ride.pace_category in pace_counts:
            score += 20 + min(pace_counts[ride.pace_category], 5)
        if ride_type in type_counts:
            score += 18 + min(type_counts[ride_type], 5)
        if distance is not None:
            if distance <= 10:
                score += 20
            elif distance <= 25:
                score += 14
            elif distance <= 50:
                score += 7
        score += min(friend_counts.get(ride.id, 0) * 10, 30)
        if club and club.is_verified:
            score += 6
        days_out = (ride.date - today).days
        score += max(0, 14 - days_out)

        recs.append(RideRecommendation(
            ride=ride,
            score=score,
            reason=_reason_for_ride(
                ride,
                distance=distance,
                pace_match=ride.pace_category in pace_counts,
                type_match=ride_type in type_counts or ride_type in allowed_types,
                friend_count=friend_counts.get(ride.id, 0),
                in_joined_club=ride.club_id in joined_club_ids,
            ),
            distance_miles=distance,
        ))

    recs.sort(key=lambda rec: (-rec.score, rec.ride.date, rec.ride.time))
    return recs[:limit]


def recommend_clubs_for_user(user, *, today=None, limit=5):
    today = today or date.today()
    if not user.recommendations_enabled:
        return []

    hidden = _hidden_ids(user, 'club')
    joined_club_ids = _active_club_ids(user)
    allowed_types = set(allowed_ride_types_for_user(user, today))
    _, type_counts = _history_traits(user, today) if user.recommendation_history_enabled else ({}, {})
    horizon = today + timedelta(days=30)

    clubs = (Club.query
             .filter_by(is_active=True, is_hidden=False)
             .order_by(Club.name.asc())
             .limit(250)
             .all())
    recs = []
    for club in clubs:
        if club.id in hidden or club.id in joined_club_ids:
            continue
        if club.normalized_sport_type not in user.preferred_sports:
            continue
        if club.is_private:
            continue

        upcoming = (Ride.query
                    .filter(Ride.club_id == club.id,
                            Ride.date >= today,
                            Ride.date <= horizon,
                            Ride.is_cancelled == False)  # noqa: E712
                    .all())
        if not upcoming:
            continue
        matching = [
            r for r in upcoming
            if ('virtual' if r.is_virtual else (r.ride_type or 'road')) in allowed_types
        ]
        if not matching:
            continue

        distance = _distance_to_club(user, club)
        score = 0
        if distance is not None:
            if distance <= 10:
                score += 30
            elif distance <= 25:
                score += 22
            elif distance <= 50:
                score += 10
        if club.is_verified:
            score += 12
        score += min(len(matching) * 4, 24)
        for ride in matching:
            ride_type = 'virtual' if ride.is_virtual else (ride.ride_type or 'road')
            if ride_type in type_counts:
                score += 5

        if distance is not None and distance <= 25:
            reason = 'Active near your saved location'
        elif club.is_verified:
            reason = 'Verified club with rides that match you'
        else:
            common_type = 'virtual' if matching[0].is_virtual else (matching[0].ride_type or 'road')
            reason = f'Hosts {RIDE_TYPE_LABELS.get(common_type, common_type)} rides'

        recs.append(ClubRecommendation(
            club=club,
            score=score,
            reason=reason,
            distance_miles=distance,
            upcoming_count=len(upcoming),
        ))

    recs.sort(key=lambda rec: (-rec.score, rec.club.name))
    return recs[:limit]
