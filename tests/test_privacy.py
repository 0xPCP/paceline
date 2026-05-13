from datetime import date, time, timedelta

from app.models import Club, Ride, RideSignup, User
from tests.conftest import login


def test_footer_links_privacy_and_data_use(client):
    resp = client.get('/')
    assert resp.status_code == 200
    assert b'/privacy' in resp.data
    assert b'/data-use' in resp.data


def test_privacy_policy_page(client):
    resp = client.get('/privacy')
    assert resp.status_code == 200
    assert b'Privacy Policy' in resp.data
    assert b'privacy@paceline.club' in resp.data
    assert b'does not currently sell identifiable personal data' in resp.data
    assert b'United States' in resp.data


def test_data_use_policy_page(client):
    resp = client.get('/data-use')
    assert resp.status_code == 200
    assert b'Data Use Policy' in resp.data
    assert b'aggregated or de-identified data' in resp.data
    assert b'privacy@paceline.club' in resp.data


def test_registration_onboarding_links_to_policy_statements(client):
    resp = client.get('/auth/register')
    assert resp.status_code == 200
    assert b'Privacy Policy' in resp.data
    assert b'Data Use Policy' in resp.data
    assert b'location data' in resp.data
    assert b'United States' in resp.data
    assert b'aggregated or de-identified data' in resp.data


def test_profile_shows_delete_account(client, regular_user):
    login(client, regular_user.email)
    resp = client.get('/auth/profile')
    assert resp.status_code == 200
    assert b'Delete My Account' in resp.data
    assert f'DELETE {regular_user.email}'.encode() in resp.data


def test_delete_account_requires_exact_confirmation(client, db, regular_user):
    login(client, regular_user.email)
    resp = client.post('/auth/profile/delete-account', data={
        'confirmation': 'DELETE',
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b'DELETE rider@test.com' in resp.data
    assert db.session.get(User, regular_user.id) is not None


def test_user_can_delete_own_account_and_personal_rides(client, db, regular_user):
    ride = Ride(
        owner_id=regular_user.id,
        title='Delete Me Ride',
        date=date.today() + timedelta(days=1),
        time=time(9, 0),
        meeting_location='Test lot',
        distance_miles=12,
        pace_category='B',
        ride_type='road',
    )
    db.session.add(ride)
    db.session.flush()
    db.session.add(RideSignup(ride_id=ride.id, user_id=regular_user.id))
    db.session.commit()
    ride_id = ride.id
    user_id = regular_user.id

    login(client, regular_user.email)
    resp = client.post('/auth/profile/delete-account', data={
        'confirmation': f'DELETE {regular_user.email}',
    }, follow_redirects=True)

    assert resp.status_code == 200
    assert b'Your account has been deleted' in resp.data
    assert db.session.get(User, user_id) is None
    assert db.session.get(Ride, ride_id) is None


def test_club_owner_must_transfer_or_delete_club_before_account_deletion(client, db, regular_user):
    club = Club(slug='owned-delete-block', name='Owned Delete Block', owner_id=regular_user.id)
    db.session.add(club)
    db.session.commit()

    login(client, regular_user.email)
    resp = client.post('/auth/profile/delete-account', data={
        'confirmation': f'DELETE {regular_user.email}',
    }, follow_redirects=True)

    assert b'Transfer or delete clubs you own' in resp.data
    assert db.session.get(User, regular_user.id) is not None
    assert db.session.get(Club, club.id) is not None
