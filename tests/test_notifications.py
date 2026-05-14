from datetime import date, datetime, time, timezone

from app.email import (
    daily_email_cap,
    send_club_news_notification,
    send_new_ride_notification,
    set_site_setting,
)
from app.models import (
    BoardDigestItem,
    ClubBoardPost,
    ClubBoardSubscription,
    ClubMembership,
    ClubPost,
    Ride,
    SiteSetting,
    UserEmailLog,
)
from app.scheduler import send_board_activity_digests
from tests.conftest import login


def test_profile_saves_email_notification_preferences(client, db, regular_user):
    login(client)

    response = client.post('/auth/profile', data={
        'username': regular_user.username,
        'email': regular_user.email,
        'zip_code': regular_user.zip_code or '',
        'gender': '',
        'bio': '',
        'strava_profile_url': '',
        'language': '',
        'emergency_contact_name': '',
        'emergency_contact_phone': '',
        'notify_ride_cancellations': 'y',
        'notify_ride_reminders': 'y',
        'notify_ride_waitlist': 'y',
        'notify_ride_updates': 'y',
        'notify_membership_updates': 'y',
        'notify_club_new_rides': 'y',
        'notify_weekly_digest': 'y',
    }, follow_redirects=True)

    assert response.status_code == 200
    db.session.refresh(regular_user)
    assert regular_user.email_preferences['club_news'] is False
    assert regular_user.email_preferences['board_digest'] is False
    assert regular_user.email_preferences['club_new_rides'] is True


def test_new_ride_notification_respects_user_preference_and_daily_cap(app, db, sample_club, regular_user, second_user, monkeypatch):
    regular_user.email_preferences = {'club_new_rides': False}
    db.session.add(ClubMembership(user_id=regular_user.id, club_id=sample_club.id, status='active'))
    db.session.add(ClubMembership(user_id=second_user.id, club_id=sample_club.id, status='active'))
    ride = Ride(
        club_id=sample_club.id,
        title='Instant Club Ride',
        date=date.today(),
        time=time(9, 0),
        meeting_location='Town Center',
        distance_miles=20,
        pace_category='C',
    )
    db.session.add(ride)
    db.session.commit()

    sent = []
    def fake_send(subject, recipients, html, text=None):
        sent.extend(recipients)
        return True
    monkeypatch.setattr('app.email._send', fake_send)

    send_new_ride_notification(ride)

    assert regular_user.email not in sent
    assert second_user.email in sent
    assert UserEmailLog.query.filter_by(user_id=second_user.id, notification_key='club_new_rides', status='sent').count() == 1

    set_site_setting('email_daily_cap', 1)
    db.session.commit()
    send_new_ride_notification(ride)

    assert sent.count(second_user.email) == 1
    assert UserEmailLog.query.filter_by(user_id=second_user.id, notification_key='club_new_rides', status='capped').count() == 1


def test_club_news_notification_is_instant_and_respects_preferences(app, db, sample_club, regular_user, second_user, monkeypatch):
    regular_user.email_preferences = {'club_news': False}
    db.session.add(ClubMembership(user_id=regular_user.id, club_id=sample_club.id, status='active'))
    db.session.add(ClubMembership(user_id=second_user.id, club_id=sample_club.id, status='active'))
    post = ClubPost(
        club_id=sample_club.id,
        author_id=regular_user.id,
        title='Route updates',
        body='The Saturday route has changed.',
    )
    db.session.add(post)
    db.session.commit()

    sent = []
    def fake_send(subject, recipients, html, text=None):
        sent.extend(recipients)
        return True
    monkeypatch.setattr('app.email._send', fake_send)

    send_club_news_notification(post)

    assert regular_user.email not in sent
    assert second_user.email in sent
    assert UserEmailLog.query.filter_by(user_id=second_user.id, notification_key='club_news', status='sent').count() == 1


def test_superadmin_can_update_daily_email_cap(client, db, admin_user):
    login(client, email='admin@test.com')

    response = client.post('/admin/', data={
        'action': 'email_settings',
        'email_daily_cap': '22',
    }, follow_redirects=True)

    assert response.status_code == 200
    assert daily_email_cap() == 22
    assert db.session.get(SiteSetting, 'email_daily_cap').value == '22'


def test_board_activity_is_queued_and_sent_as_digest(app, db, sample_club, regular_user, second_user, monkeypatch):
    db.session.add(ClubMembership(user_id=regular_user.id, club_id=sample_club.id, status='active'))
    db.session.add(ClubMembership(user_id=second_user.id, club_id=sample_club.id, status='active'))
    db.session.add(ClubBoardSubscription(user_id=second_user.id, club_id=sample_club.id))
    post = ClubBoardPost(
        club_id=sample_club.id,
        author_id=regular_user.id,
        body='Anyone riding tonight?',
        created_at=datetime.now(timezone.utc),
    )
    db.session.add(post)
    db.session.flush()
    db.session.add(BoardDigestItem(
        user_id=second_user.id,
        club_id=sample_club.id,
        post_id=post.id,
        actor_id=regular_user.id,
        event_type='new_post',
        body_preview=post.body,
    ))
    db.session.commit()

    sent = []
    def fake_send(subject, recipients, html, text=None):
        sent.extend(recipients)
        return True
    monkeypatch.setattr('app.email._send', fake_send)
    # url_for(_external=True) in the email template needs a SERVER_NAME when
    # there is no active request context (scheduler runs outside HTTP requests).
    app.config['SERVER_NAME'] = 'localhost'
    app.config['PREFERRED_URL_SCHEME'] = 'http'
    send_board_activity_digests(app)
    app.config.pop('SERVER_NAME', None)
    app.config.pop('PREFERRED_URL_SCHEME', None)

    assert sent == [second_user.email]
    item = BoardDigestItem.query.first()
    assert item.sent_at is not None
    assert UserEmailLog.query.filter_by(user_id=second_user.id, notification_key='board_digest', status='sent').count() == 1
