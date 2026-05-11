import hmac
import hashlib
import json
import time
from urllib.parse import urlencode

import requests
from flask import current_app


STRIPE_API_BASE = 'https://api.stripe.com/v1'
STRIPE_CONNECT_AUTHORIZE_URL = 'https://connect.stripe.com/oauth/authorize'
STRIPE_API_VERSION = '2026-04-22.dahlia'


class StripeConnectError(RuntimeError):
    pass


def connect_enabled():
    return bool(
        current_app.config.get('STRIPE_SECRET_KEY')
        and current_app.config.get('STRIPE_CONNECT_CLIENT_ID')
    )


def webhook_enabled():
    return bool(current_app.config.get('STRIPE_WEBHOOK_SECRET'))


def authorization_url(state, redirect_uri):
    client_id = current_app.config.get('STRIPE_CONNECT_CLIENT_ID')
    if not client_id:
        raise StripeConnectError('Stripe Connect client ID is not configured.')
    query = urlencode({
        'response_type': 'code',
        'client_id': client_id,
        'scope': 'read_write',
        'state': state,
        'redirect_uri': redirect_uri,
    })
    return f'{STRIPE_CONNECT_AUTHORIZE_URL}?{query}'


def _headers():
    secret = current_app.config.get('STRIPE_SECRET_KEY')
    if not secret:
        raise StripeConnectError('Stripe secret key is not configured.')
    return {
        'Authorization': f'Bearer {secret}',
        'Stripe-Version': STRIPE_API_VERSION,
    }


def exchange_authorization_code(code):
    response = requests.post(
        f'{STRIPE_API_BASE}/oauth/token',
        headers=_headers(),
        data={'grant_type': 'authorization_code', 'code': code},
        timeout=15,
    )
    if response.status_code >= 400:
        raise StripeConnectError('Stripe rejected the Connect authorization.')
    return response.json()


def create_checkout_session(*, club, user, membership, payment, success_url, cancel_url):
    if not club.stripe_account_id:
        raise StripeConnectError('This club has not connected Stripe.')
    data = {
        'mode': 'payment',
        'success_url': success_url,
        'cancel_url': cancel_url,
        'client_reference_id': str(payment.id),
        'customer_email': user.email,
        'line_items[0][quantity]': '1',
        'line_items[0][price_data][currency]': club.membership_dues_currency or 'usd',
        'line_items[0][price_data][unit_amount]': str(payment.amount_cents),
        'line_items[0][price_data][product_data][name]': f'{club.name} membership dues',
        'metadata[payment_id]': str(payment.id),
        'metadata[club_id]': str(club.id),
        'metadata[user_id]': str(user.id),
        'metadata[membership_id]': str(membership.id),
    }
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
