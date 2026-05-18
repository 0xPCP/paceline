import hmac
import hashlib
import json
import time

import requests
from flask import current_app


STRIPE_API_BASE = 'https://api.stripe.com/v1'
STRIPE_API_VERSION = '2026-04-22.dahlia'


class StripeConnectError(RuntimeError):
    pass


def connect_enabled():
    return bool(current_app.config.get('STRIPE_SECRET_KEY'))


def webhook_enabled():
    return bool(current_app.config.get('STRIPE_WEBHOOK_SECRET'))


def _headers():
    secret = current_app.config.get('STRIPE_SECRET_KEY')
    if not secret:
        raise StripeConnectError('Stripe secret key is not configured.')
    return {
        'Authorization': f'Bearer {secret}',
        'Stripe-Version': STRIPE_API_VERSION,
    }


def create_connected_account(*, club, user):
    data = {
        'email': user.email,
        'business_profile[name]': club.name,
        'metadata[club_id]': str(club.id),
        'metadata[club_slug]': club.slug,
    }
    if club.website:
        data['business_profile[url]'] = club.website
    response = requests.post(
        f'{STRIPE_API_BASE}/accounts',
        headers=_headers(),
        data=data,
        timeout=15,
    )
    if response.status_code >= 400:
        raise StripeConnectError('Stripe could not create the connected account.')
    payload = response.json()
    if not payload.get('id'):
        raise StripeConnectError('Stripe returned an incomplete connected account.')
    return payload


def create_onboarding_link(*, account_id, refresh_url, return_url):
    response = requests.post(
        f'{STRIPE_API_BASE}/account_links',
        headers=_headers(),
        data={
            'account': account_id,
            'refresh_url': refresh_url,
            'return_url': return_url,
            'type': 'account_onboarding',
        },
        timeout=15,
    )
    if response.status_code >= 400:
        raise StripeConnectError('Stripe could not create the onboarding link.')
    payload = response.json()
    if not payload.get('url'):
        raise StripeConnectError('Stripe returned an incomplete onboarding link.')
    return payload


def retrieve_connected_account(account_id):
    response = requests.get(
        f'{STRIPE_API_BASE}/accounts/{account_id}',
        headers=_headers(),
        timeout=15,
    )
    if response.status_code >= 400:
        raise StripeConnectError('Stripe could not retrieve the connected account.')
    return response.json()


def create_checkout_session(*, club, user, membership, payment, success_url, cancel_url):
    """Create a Checkout Session as a direct charge on the club's connected account.

    The platform fee (application_fee_amount) is deducted from the charge
    before the remaining funds settle to the connected account. The fee is
    invisible to the customer — they see only the membership line item.

    The webhook that handles checkout.session.completed must be registered
    in the Stripe dashboard as a Connect webhook so it receives events from
    connected accounts. Set STRIPE_CONNECT_WEBHOOK_SECRET in .env to the
    signing secret Stripe assigns to that Connect webhook endpoint.
    """
    if not club.stripe_account_id:
        raise StripeConnectError('This club has not connected Stripe.')

    platform_fee_cents = current_app.config.get('STRIPE_PLATFORM_FEE_CENTS', 100)

    data = {
        'mode': 'payment',
        'success_url': success_url,
        'cancel_url': cancel_url,
        'client_reference_id': str(payment.id),
        'customer_email': user.email,
        'line_items[0][quantity]': '1',
        'line_items[0][price_data][currency]': club.membership_dues_currency or 'usd',
        'line_items[0][price_data][unit_amount]': str(payment.amount_cents),
        'line_items[0][price_data][product_data][name]': f'{club.name} — {club.membership_duration_months}-Month Membership',
        'line_items[0][price_data][product_data][description]': 'Cycling club membership',
        'payment_intent_data[application_fee_amount]': str(platform_fee_cents),
        'metadata[payment_id]': str(payment.id),
        'metadata[club_id]': str(club.id),
        'metadata[user_id]': str(user.id),
        'metadata[membership_id]': str(membership.id),
    }

    # Direct charge: session is created on the connected account.
    # The Stripe-Account header routes the API call to the club's account.
    headers = _headers()
    headers['Stripe-Account'] = club.stripe_account_id

    response = requests.post(
        f'{STRIPE_API_BASE}/checkout/sessions',
        headers=headers,
        data=data,
        timeout=15,
    )
    if response.status_code >= 400:
        raise StripeConnectError('Stripe could not create the checkout session.')
    payload = response.json()
    if not payload.get('id') or not payload.get('url'):
        raise StripeConnectError('Stripe returned an incomplete checkout session.')
    return payload


def verify_webhook_payload(payload, signature_header, secret, tolerance=300):
    if not signature_header:
        raise StripeConnectError('Missing Stripe signature.')
    values = {}
    for item in signature_header.split(','):
        if '=' in item:
            key, value = item.split('=', 1)
            values.setdefault(key, []).append(value)
    timestamps = values.get('t') or []
    signatures = values.get('v1') or []
    if not timestamps or not signatures:
        raise StripeConnectError('Malformed Stripe signature.')
    timestamp = int(timestamps[0])
    if abs(time.time() - timestamp) > tolerance:
        raise StripeConnectError('Expired Stripe signature.')
    signed_payload = f'{timestamp}.'.encode() + payload
    expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
        raise StripeConnectError('Invalid Stripe signature.')
    return json.loads(payload.decode('utf-8'))
