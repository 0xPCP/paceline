import hashlib
import hmac
import json
import time
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.membership_dues import activate_membership_dues, add_months
from app.models import Club, ClubMembership, ClubMembershipPayment
from app.stripe_connect import StripeConnectError
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


def test_connect_start_creates_account_and_redirects_to_onboarding(client, app, db, sample_club, club_admin_user, monkeypatch):
    app.config['STRIPE_SECRET_KEY'] = 'sk_test_fake'
    login(client, email='clubadmin@test.com')

    def fake_account(**kwargs):
        assert kwargs['club'].id == sample_club.id
        assert kwargs['user'].email == club_admin_user.email
        return {'id': 'acct_123'}

    def fake_link(**kwargs):
        assert kwargs['account_id'] == 'acct_123'
        assert kwargs['refresh_url'] == f'http://localhost/stripe/clubs/{sample_club.slug}/connect'
        assert kwargs['return_url'] == f'http://localhost/stripe/clubs/{sample_club.slug}/connect/return'
        return {'url': 'https://connect.stripe.com/setup/test'}

    monkeypatch.setattr('app.routes.stripe_connect.create_connected_account', fake_account)
    monkeypatch.setattr('app.routes.stripe_connect.create_onboarding_link', fake_link)

    response = client.get(f'/stripe/clubs/{sample_club.slug}/connect')

    assert response.status_code == 302
    assert response.headers['Location'] == 'https://connect.stripe.com/setup/test'
    db.session.refresh(sample_club)
    assert sample_club.stripe_account_id == 'acct_123'


def test_connect_return_marks_account_connected_when_charges_enabled(client, app, db, sample_club, club_admin_user, monkeypatch):
    app.config['STRIPE_SECRET_KEY'] = 'sk_test_fake'
    sample_club.stripe_account_id = 'acct_123'
    db.session.commit()
    login(client, email='clubadmin@test.com')

    monkeypatch.setattr(
        'app.routes.stripe_connect.retrieve_connected_account',
        lambda account_id: {'id': account_id, 'details_submitted': True, 'charges_enabled': True},
    )

    response = client.get(
        f'/stripe/clubs/{sample_club.slug}/connect/return',
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
    sample_club.stripe_account_connected_at = datetime.now(timezone.utc)
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
    app.config['STRIPE_CONNECT_WEBHOOK_SECRET'] = 'whsec_test'
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


def test_stripe_connect_webhook_secret_takes_precedence(client, app, db, sample_club, regular_user):
    """Direct-charge webhooks must verify with the Connect endpoint secret when configured."""
    app.config['STRIPE_WEBHOOK_SECRET'] = 'whsec_platform'
    app.config['STRIPE_CONNECT_WEBHOOK_SECRET'] = 'whsec_connect'
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
        provider_session_id='cs_connect_secret',
        amount_cents=4500,
    )
    db.session.add(payment)
    db.session.commit()

    payload = json.dumps({
        'type': 'checkout.session.completed',
        'data': {'object': {'id': 'cs_connect_secret', 'payment_intent': 'pi_connect'}},
    }).encode()

    platform_response = client.post(
        '/stripe/webhook',
        data=payload,
        headers={'Stripe-Signature': _stripe_signature(payload, 'whsec_platform')},
        content_type='application/json',
    )
    assert platform_response.status_code == 400

    connect_response = client.post(
        '/stripe/webhook',
        data=payload,
        headers={'Stripe-Signature': _stripe_signature(payload, 'whsec_connect')},
        content_type='application/json',
    )

    assert connect_response.status_code == 200
    db.session.refresh(payment)
    assert payment.status == 'paid'


def test_create_checkout_session_direct_charge(app):
    """create_checkout_session must use direct charges:
    - Stripe-Account header routes the call to the connected account
    - application_fee_amount carries the platform fee
    - no transfer_data[destination] (that's destination charges, not direct)
    - only one line item visible to the customer
    """
    from app.stripe_connect import create_checkout_session

    club = MagicMock()
    club.stripe_account_id = 'acct_test_123'
    club.membership_dues_currency = 'usd'
    club.name = 'Test Club'
    club.membership_duration_months = 12

    user = MagicMock()
    user.email = 'rider@test.com'

    membership = MagicMock()
    membership.id = 1

    payment = MagicMock()
    payment.id = 1
    payment.amount_cents = 2000
    payment.club_id = 1
    payment.user_id = 1

    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {'id': 'cs_test_abc', 'url': 'https://checkout.stripe.com/c/pay'}

    with app.app_context():
        app.config['STRIPE_SECRET_KEY'] = 'sk_test_fake'
        app.config['STRIPE_PLATFORM_FEE_CENTS'] = 100
        with patch('app.stripe_connect.requests.post', return_value=fake_response) as mock_post:
            create_checkout_session(
                club=club, user=user, membership=membership, payment=payment,
                success_url='https://example.com/success',
                cancel_url='https://example.com/cancel',
            )

    posted_headers = mock_post.call_args.kwargs['headers']
    posted_data = mock_post.call_args.kwargs['data']

    assert posted_headers.get('Stripe-Account') == 'acct_test_123', (
        'Stripe-Account header missing — checkout must be created on the connected account (direct charge)'
    )
    assert posted_data['payment_intent_data[application_fee_amount]'] == '100', (
        'Platform $1 fee missing — application_fee_amount must be 100 cents'
    )
    assert 'payment_intent_data[transfer_data][destination]' not in posted_data, (
        'transfer_data[destination] must not be set for direct charges'
    )
    assert 'line_items[1][price_data][product_data][name]' not in posted_data, (
        'No second line item — platform fee is silent (application_fee_amount), not a visible line item'
    )


# ── Access control tests ───────────────────────────────────────────────────────

def _setup_stripe_club(db, club):
    """Configure club for Stripe Connect dues checkout."""
    club.membership_dues_required = True
    club.membership_dues_mode = 'stripe_connect'
    club.membership_dues_amount_cents = 4500
    club.stripe_account_id = 'acct_123'
    club.stripe_account_connected_at = datetime.now(timezone.utc)
    db.session.commit()


def test_active_member_far_from_expiry_is_blocked_from_checkout(client, app, db, sample_club, regular_user, monkeypatch):
    """Active member whose dues don't expire within 30 days cannot start a new checkout."""
    app.config['STRIPE_SECRET_KEY'] = 'sk_test_fake'
    _setup_stripe_club(db, sample_club)

    membership = ClubMembership(
        user_id=regular_user.id,
        club_id=sample_club.id,
        status='active',
        dues_paid_until=date.today() + timedelta(days=90),
    )
    db.session.add(membership)
    db.session.commit()

    login(client)
    response = client.post(f'/stripe/clubs/{sample_club.slug}/checkout', follow_redirects=True)

    assert response.status_code == 200
    assert b'already active' in response.data
    db.session.refresh(membership)
    assert membership.status == 'active', 'Membership status must not change'


def test_active_member_expiring_within_30_days_can_renew_early(client, app, db, sample_club, regular_user, monkeypatch):
    """Active member with dues expiring within 30 days is allowed to start early renewal checkout."""
    app.config['STRIPE_SECRET_KEY'] = 'sk_test_fake'
    _setup_stripe_club(db, sample_club)

    membership = ClubMembership(
        user_id=regular_user.id,
        club_id=sample_club.id,
        status='active',
        dues_paid_until=date.today() + timedelta(days=15),
    )
    db.session.add(membership)
    db.session.commit()

    def fake_checkout(**kwargs):
        return {'id': 'cs_early_renew', 'url': 'https://checkout.stripe.com/c/pay'}

    monkeypatch.setattr('app.routes.stripe_connect.create_checkout_session', fake_checkout)
    login(client)
    response = client.post(f'/stripe/clubs/{sample_club.slug}/checkout')

    assert response.status_code == 302
    assert 'checkout.stripe.com' in response.headers['Location']


def test_active_member_expiring_today_can_renew(client, app, db, sample_club, regular_user, monkeypatch):
    """Active member whose dues expire exactly today is within the 30-day window."""
    app.config['STRIPE_SECRET_KEY'] = 'sk_test_fake'
    _setup_stripe_club(db, sample_club)

    membership = ClubMembership(
        user_id=regular_user.id,
        club_id=sample_club.id,
        status='active',
        dues_paid_until=date.today(),
    )
    db.session.add(membership)
    db.session.commit()

    def fake_checkout(**kwargs):
        return {'id': 'cs_expire_today', 'url': 'https://checkout.stripe.com/c/pay'}

    monkeypatch.setattr('app.routes.stripe_connect.create_checkout_session', fake_checkout)
    login(client)
    response = client.post(f'/stripe/clubs/{sample_club.slug}/checkout')

    assert response.status_code == 302
    assert 'checkout.stripe.com' in response.headers['Location']


def test_stripe_error_during_checkout_rolls_back_payment_record(client, app, db, sample_club, regular_user, monkeypatch):
    """StripeConnectError during checkout creation must rollback — no orphan payment rows."""
    app.config['STRIPE_SECRET_KEY'] = 'sk_test_fake'
    _setup_stripe_club(db, sample_club)

    login(client)

    def boom(**kwargs):
        raise StripeConnectError('Stripe is down')

    monkeypatch.setattr('app.routes.stripe_connect.create_checkout_session', boom)
    response = client.post(f'/stripe/clubs/{sample_club.slug}/checkout', follow_redirects=True)

    assert response.status_code == 200
    assert b'temporarily unavailable' in response.data
    orphan_payments = ClubMembershipPayment.query.filter_by(
        user_id=regular_user.id, club_id=sample_club.id
    ).all()
    assert orphan_payments == [], 'No payment row should be persisted after rollback'


# ── Webhook idempotency and edge-case tests ───────────────────────────────────

def test_webhook_duplicate_session_is_idempotent(client, app, db, sample_club, regular_user):
    """Sending the same checkout.session.completed twice must not double-activate membership."""
    app.config['STRIPE_WEBHOOK_SECRET'] = 'whsec_test'
    sample_club.membership_dues_required = True
    membership = ClubMembership(user_id=regular_user.id, club_id=sample_club.id, status='pending_payment')
    db.session.add(membership)
    db.session.flush()
    payment = ClubMembershipPayment(
        club_id=sample_club.id, user_id=regular_user.id,
        membership_id=membership.id, provider_session_id='cs_dup_test', amount_cents=4500,
    )
    db.session.add(payment)
    db.session.commit()

    payload = json.dumps({
        'type': 'checkout.session.completed',
        'data': {'object': {'id': 'cs_dup_test', 'payment_intent': 'pi_dup'}},
    }).encode()
    sig = _stripe_signature(payload, 'whsec_test')
    headers = {'Stripe-Signature': sig}

    r1 = client.post('/stripe/webhook', data=payload, headers=headers, content_type='application/json')
    assert r1.status_code == 200
    assert r1.get_json()['status'] == 'processed'

    first_expiry = ClubMembership.query.get(membership.id).dues_paid_until

    # Send the same payload a second time (re-sign with fresh timestamp)
    sig2 = _stripe_signature(payload, 'whsec_test')
    r2 = client.post('/stripe/webhook', data=payload, headers={'Stripe-Signature': sig2}, content_type='application/json')
    assert r2.status_code == 200
    assert r2.get_json()['status'] == 'already processed'

    db.session.expire_all()
    assert ClubMembership.query.get(membership.id).dues_paid_until == first_expiry, (
        'dues_paid_until must not change on duplicate webhook'
    )


def test_webhook_unknown_session_id_returns_200(client, app, db):
    """Webhook for an unrecognised session should return 200 (not 4xx) for Stripe retry safety."""
    app.config['STRIPE_WEBHOOK_SECRET'] = 'whsec_test'
    payload = json.dumps({
        'type': 'checkout.session.completed',
        'data': {'object': {'id': 'cs_ghost_session', 'payment_intent': 'pi_ghost'}},
    }).encode()
    sig = _stripe_signature(payload, 'whsec_test')

    response = client.post(
        '/stripe/webhook', data=payload,
        headers={'Stripe-Signature': sig}, content_type='application/json',
    )

    assert response.status_code == 200
    assert response.get_json()['status'] == 'unknown session'


def test_webhook_non_checkout_event_is_ignored(client, app, db):
    """Unrecognised event types must be silently ignored with 200."""
    app.config['STRIPE_WEBHOOK_SECRET'] = 'whsec_test'
    payload = json.dumps({
        'type': 'customer.subscription.created',
        'data': {'object': {'id': 'sub_irrelevant'}},
    }).encode()
    sig = _stripe_signature(payload, 'whsec_test')

    response = client.post(
        '/stripe/webhook', data=payload,
        headers={'Stripe-Signature': sig}, content_type='application/json',
    )

    assert response.status_code == 200
    assert response.get_json()['status'] == 'ignored'


def test_webhook_payment_failed_logs_error_and_returns_200(client, app, db, monkeypatch):
    """payment_intent.payment_failed must log to AppErrorLog, alert admin, and return 200."""
    from app.models import AppErrorLog
    app.config['STRIPE_WEBHOOK_SECRET'] = 'whsec_test'

    # Stub out the email send so the test doesn't require a real mail server
    sent = []
    monkeypatch.setattr(
        'app.email.send_stripe_error_alert',
        lambda **kwargs: sent.append(kwargs),
    )

    payload = json.dumps({
        'type': 'payment_intent.payment_failed',
        'data': {'object': {
            'id': 'pi_failed_test',
            'last_payment_error': {'message': 'Your card was declined.'},
        }},
    }).encode()
    sig = _stripe_signature(payload, 'whsec_test')

    response = client.post(
        '/stripe/webhook', data=payload,
        headers={'Stripe-Signature': sig}, content_type='application/json',
    )

    assert response.status_code == 200
    assert response.get_json()['status'] == 'failure_logged'
    assert len(sent) == 1, 'send_stripe_error_alert should be called once'
    assert sent[0]['payment_intent_id'] == 'pi_failed_test'
    error_log = AppErrorLog.query.filter_by(error_type='stripe_payment_failed').first()
    assert error_log is not None
    assert 'pi_failed_test' in error_log.error_message


def test_webhook_bad_signature_returns_400(client, app, db):
    """Webhook with a tampered signature must be rejected with 400."""
    app.config['STRIPE_WEBHOOK_SECRET'] = 'whsec_test'
    payload = json.dumps({
        'type': 'checkout.session.completed',
        'data': {'object': {'id': 'cs_test', 'payment_intent': 'pi_test'}},
    }).encode()

    response = client.post(
        '/stripe/webhook', data=payload,
        headers={'Stripe-Signature': 't=111,v1=badhash'},
        content_type='application/json',
    )

    assert response.status_code == 400


# ── activate_membership_dues unit tests ───────────────────────────────────────

def test_activate_membership_dues_stacks_from_future_expiry(db, sample_club, regular_user):
    """Early renewal must extend from the existing future expiry, not from today."""
    future_expiry = date.today() + timedelta(days=180)
    sample_club.membership_duration_months = 12
    db.session.commit()

    membership = ClubMembership(
        user_id=regular_user.id, club_id=sample_club.id,
        status='active', dues_paid_until=future_expiry,
    )
    db.session.add(membership)
    db.session.commit()

    activate_membership_dues(membership)

    expected = add_months(future_expiry, 12)
    assert membership.dues_paid_until == expected, (
        f'Expected dues stacked to {expected}, got {membership.dues_paid_until}'
    )


def test_activate_membership_dues_starts_from_today_when_expired(db, sample_club, regular_user):
    """Activation for an already-expired membership starts the new period from today."""
    past_expiry = date.today() - timedelta(days=30)
    sample_club.membership_duration_months = 12
    db.session.commit()

    membership = ClubMembership(
        user_id=regular_user.id, club_id=sample_club.id,
        status='pending_payment', dues_paid_until=past_expiry,
    )
    db.session.add(membership)
    db.session.commit()

    activate_membership_dues(membership)

    expected = add_months(date.today(), 12)
    assert membership.dues_paid_until == expected, (
        f'Expected dues from today ({expected}), got {membership.dues_paid_until}'
    )


def test_activate_membership_dues_resets_reminder_sent(db, sample_club, regular_user):
    """Activating dues must clear dues_reminder_sent so reminders fire again next cycle."""
    sample_club.membership_duration_months = 12
    db.session.commit()

    membership = ClubMembership(
        user_id=regular_user.id, club_id=sample_club.id,
        status='pending_payment', dues_reminder_sent={'30': '2026-01-01', '7': '2026-01-24'},
    )
    db.session.add(membership)
    db.session.commit()

    activate_membership_dues(membership)

    assert membership.dues_reminder_sent is None, (
        'dues_reminder_sent must be cleared to None after activation'
    )


# ── Guest gating unit tests ───────────────────────────────────────────────────

def test_guest_club_rides_list_requires_login(client, db, sample_club):
    """Unauthenticated visitors are redirected to login for the rides calendar (v0.121)."""
    response = client.get(f'/clubs/{sample_club.slug}/rides/', follow_redirects=False)
    assert response.status_code == 302
    assert '/auth/login' in response.headers.get('Location', '')


def test_guest_club_ride_detail_requires_login(client, db, sample_club, sample_rides):
    """Unauthenticated visitors are redirected to login for ride detail (v0.121)."""
    ride = sample_rides[0]
    response = client.get(f'/clubs/{sample_club.slug}/rides/{ride.id}', follow_redirects=False)
    assert response.status_code == 302
    assert '/auth/login' in response.headers.get('Location', '')
