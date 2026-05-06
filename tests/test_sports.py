from app.extensions import db
from app.models import Club
from app.sports import normalize_sport, normalize_sport_preferences
from tests.conftest import login


def test_sport_normalization_defaults_to_cycling():
    assert normalize_sport('cycling') == 'cycling'
    assert normalize_sport('running') == 'running'
    assert normalize_sport('') == 'cycling'
    assert normalize_sport('skiing') == 'cycling'


def test_sport_preferences_default_to_cycling(regular_user):
    assert regular_user.sport_preferences is None
    assert regular_user.preferred_sports == ['cycling']
    assert regular_user.prefers_sport('cycling') is True
    assert regular_user.prefers_sport('running') is False


def test_user_can_store_future_running_preference(regular_user):
    regular_user.set_sport_preferences(['running'])
    db.session.commit()

    assert regular_user.sport_preferences == ['running']
    assert regular_user.preferred_sports == ['running']
    assert regular_user.prefers_sport('running') is True
    assert regular_user.prefers_sport('cycling') is False


def test_clubs_default_to_cycling(sample_club):
    assert sample_club.sport_type == 'cycling'
    assert sample_club.normalized_sport_type == 'cycling'


def test_running_club_type_can_be_stored_for_future_support(db):
    club = Club(slug='future-running', name='Future Running Club', sport_type='running')
    db.session.add(club)
    db.session.commit()

    assert club.sport_type == 'running'
    assert club.normalized_sport_type == 'running'


def test_profile_does_not_show_dormant_sport_toggle(client, regular_user):
    login(client)
    resp = client.get('/auth/profile')
    body = resp.get_data(as_text=True).lower()

    assert resp.status_code == 200
    assert 'running club' not in body
    assert 'sport preference' not in body


def test_normalize_sport_preferences_deduplicates_and_defaults():
    assert normalize_sport_preferences(['cycling', 'running', 'cycling']) == ['cycling', 'running']
    assert normalize_sport_preferences([]) == ['cycling']
