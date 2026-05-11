import hashlib
import hmac
import json
import time

from app.models import ClubMembership, ClubMembershipPayment
from tests.conftest import login


def _settings_payload(club, **overrides):
    data = {
        'name': club.name,
        'description': '',
        'city': '',
        'state': '',
        'zip_code': '',
        'address': '',
        'website': '',
        'contact_email': '',
        'logo_url': '',
        'theme_primary': '',
        'theme_accent': '',
        'banner_url': '',
        'strava_club_id': '',
        'require_membership': 'y',
        'join_approval': 'auto',
        'membership_dues_required': 'y',
        'membership_dues_mode': 'stripe_connect',
        'membership_dues_amount': '45.00',
        'membership_duration_months': '12',
        'cancel_rain_prob': '80',
        'cancel_wind_mph': '35',
        'cancel_temp_min_f': '28',
        'cancel_temp_max_f': '100',
    }
    data.update(overrides)
    return data


def _stripe_signature(payload, secret):
    timestamp = str(int(time.time()))
    digest = hmac.new(secret.encode(), f'{timestamp}.'.encode() + payload, hashlib.sha256).hexdigest()
    return f't={timestamp},v1={digest}'


def test_settings_saves_stripe_connect_dues_configuration(client, db, sample_club, club_admin_user):
    login(client, email='clubadmin@test.com')
    response = client.post(
        f'/admin/clubs/{sample_club.slug}/settings',
        data=_settings_payload(sample_club),
        follow_redirects=True,
    )

    assert response.status_code == 200
    db.session.refresh(sample_club)
    assert sample_club.membership_dues_mode == 'stripe_connect'
    assert sample_club.membership_dues_amount_cents == 4500
    assert sample_club.membership_dues_currency == 'usd'


def test_connect_start_redirects_to_stripe_with_state(client, app, sample_club, club_admin_user):
    app.config['STRIPE_SECRET_KEY'] = 'sk_test_fake'
    app.config['STRIPE_CONNECT_CLIENT_ID'] = 'ca_test_fake'
    login(client, email='clubadmin@test.com')

    response = client.get(f'/stripe/clubs/{sample_club.slug}/connect')

    assert response.status_code == 302
    assert response.headers['Location'].startswith('https://connect.stripe.com/oauth/authorize?')
    assert 'redirect_uri=http%3A%2F%2Flocalhost%2Fstripe%2Fconnect%2Fcallback' in response.headers['Location']
    with client.session_transaction() as sess:
        assert sess['stripe_connect_oauth']['club_id'] == sample_club.id
        assert sess['stripe_connect_oauth']['state']


def test_connect_callback_stores_connected_account(client, app, db, sample_club, club_admin_user, monkeypatch):
    app.config['STRIPE_SECRET_KEY'] = 'sk_test_fake'
    app.config['STRIPE_CONNECT_CLIENT_ID'] = 'ca_test_fake'
    login(client, email='clubadmin@test.com')
    with client.session_transaction() as sess:
        sess['stripe_connect_oauth'] = {'state': 'state123', 'club_id': sample_club.id}

    monkeypatch.setattr(
        'app.routes.stripe_connect.exchange_authorization_code',
        lambda code: {'stripe_user_id': 'acct_123'},
    )

    response = client.get(
        '/stripe/connect/callback?code=authcode&state=state123',
        follow_redirects=True,
    )

    assert response.status_code == 200
    db.session.refresh(sample_club)
    assert sample_club.stripe_account_id == 'acct_123'
    assert sample_club.stripe_account_connected_at is not None


def test_stripe_checkout_creates_payment_and_redirects(client, app, db, sample_club, regular_user, monkeypatch):
    app.config['STRIPE_SECRET_KEY'] = 'sk_test_fake'
    sample_club.membership_dues_required = True
    sample_club.membership_dues_mode = 'stripe_connect'
    sample_club.membership_dues_amount_cents = 4500
    sample_club.stripe_account_id = 'acct_123'
    db.session.commit()
    login(client)

    def fake_checkout(**kwargs):
        assert kwargs['club'].id == sample_club.id
        assert kwargs['payment'].amount_cents == 4500
        return {'id': 'cs_test_123', 'url': 'https://checkout.stripe.com/c/pay'}

    monkeypatch.setattr('app.routes.stripe_connect.create_checkout_session', fake_checkout)

    response = client.post(f'/stripe/clubs/{sample_club.slug}/checkout')

    assert response.status_code == 302
    assert response.headers['Location'] == 'https://checkout.stripe.com/c/pay'
    membership = ClubMembership.query.filter_by(user_id=regular_user.id, club_id=sample_club.id).first()
    payment = ClubMembershipPayment.query.filter_by(provider_session_id='cs_test_123').first()
    assert membership.status == 'pending_payment'
    assert payment is not None
    assert payment.membership_id == membership.id


def test_stripe_webhook_activates_membership(client, app, db, sample_club, regular_user):
    app.config['STRIPE_WEBHOOK_SECRET'] = 'whsec_test'
    sample_club.membership_dues_required = True
    sample_club.membership_dues_mode = 'stripe_connect'
    sample_club.membership_dues_amount_cents = 4500
    membership = ClubMembership(user_id=regular_user.id, club_id=sample_club.id, status='pending_payment')
    db.session.add(membership)
    db.session.flush()
    payment = ClubMembershipPayment(
        club_id=sample_club.id,
        user_id=regular_user.id,
        membership_id=membership.id,
        provider_session_id='cs_test_123',
        amount_cents=4500,
    )
    db.session.add(payment)
    db.session.commit()

    payload = json.dumps({
        'type': 'checkout.session.completed',
        'data': {'object': {'id': 'cs_test_123', 'payment_intent': 'pi_123'}},
    }).encode()
    response = client.post(
        '/stripe/webhook',
        data=payload,
        headers={'Stripe-Signature': _stripe_signature(payload, 'whsec_test')},
        content_type='application/json',
    )

    assert response.status_code == 200
    db.session.refresh(membership)
    db.session.refresh(payment)
    assert membership.status == 'active'
    assert membership.dues_paid_until is not None
    assert membership.dues_confirmed_by_id is None
    assert payment.status == 'paid'
    assert payment.provider_payment_intent_id == 'pi_123'
