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

    The member pays the club dues amount plus Paceline's platform fee. Stripe
    creates the charge on the connected club account and transfers the platform
    fee to Paceline with application_fee_amount.

    The webhook that handles checkout.session.completed must be registered
    in the Stripe dashboard as a Connect webhook so it receives events from
    connected accounts. Set STRIPE_CONNECT_WEBHOOK_SECRET in .env to the
    signing secret Stripe assigns to that Connect webhook endpoint.
    """
    if not club.stripe_account_id:
        raise StripeConnectError('This club has not connected Stripe.')

    platform_fee_cents = current_app.config.get('STRIPE_PLATFORM_FEE_CENTS', 100)
    club_dues_cents = payment.amount_cents - platform_fee_cents
    if club_dues_cents <= 0:
        raise StripeConnectError('Invalid dues amount for checkout.')

    data = {
        'mode': 'payment',
        'success_url': success_url,
        'cancel_url': cancel_url,
        'client_reference_id': str(payment.id),
        'customer_email': user.email,
        'line_items[0][quantity]': '1',
        'line_items[0][price_data][currency]': club.membership_dues_currency or 'usd',
        'line_items[0][price_data][unit_amount]': str(club_dues_cents),
        'line_items[0][price_data][product_data][name]': f'{club.name} — {club.membership_duration_months}-Month Membership',
        'line_items[0][price_data][product_data][description]': 'Cycling club membership',
        'line_items[1][quantity]': '1',
        'line_items[1][price_data][currency]': club.membership_dues_currency or 'usd',
        'line_items[1][price_data][unit_amount]': str(platform_fee_cents),
        'line_items[1][price_data][product_data][name]': 'Paceline platform fee',
        'line_items[1][price_data][product_data][description]': 'Supports Paceline payment processing and platform development',
        'payment_intent_data[application_fee_amount]': str(platform_fee_cents),
        'metadata[payment_id]': str(payment.id),
        'metadata[club_id]': str(club.id),
        'metadata[user_id]': str(user.id),
        'metadata[membership_id]': str(membership.id),
        'metadata[club_dues_amount_cents]': str(club_dues_cents),
        'metadata[platform_fee_cents]': str(platform_fee_cents),
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


def create_shop_checkout_session(*, club, user, item, order, success_url, cancel_url):
    """Create a Checkout Session for a club shop item as a direct charge."""
    if not club.stripe_account_id:
        raise StripeConnectError('This club has not connected Stripe.')

    platform_fee_cents = current_app.config.get('STRIPE_PLATFORM_FEE_CENTS', 100)
    if order.item_amount_cents <= 0 or order.platform_fee_cents != platform_fee_cents:
        raise StripeConnectError('Invalid shop order amount for checkout.')

    data = {
        'mode': 'payment',
        'success_url': success_url,
        'cancel_url': cancel_url,
        'client_reference_id': f'shop_order:{order.id}',
        'customer_email': user.email,
        'line_items[0][quantity]': '1',
        'line_items[0][price_data][currency]': item.currency or 'usd',
        'line_items[0][price_data][unit_amount]': str(order.item_amount_cents),
        'line_items[0][price_data][product_data][name]': item.name,
        'line_items[0][price_data][product_data][description]': item.description or 'Club shop item',
        'line_items[1][quantity]': '1',
        'line_items[1][price_data][currency]': item.currency or 'usd',
        'line_items[1][price_data][unit_amount]': str(platform_fee_cents),
        'line_items[1][price_data][product_data][name]': 'Paceline platform fee',
        'line_items[1][price_data][product_data][description]': 'Supports Paceline payment processing and platform development',
        'payment_intent_data[application_fee_amount]': str(platform_fee_cents),
        'metadata[kind]': 'club_shop_order',
        'metadata[order_id]': str(order.id),
        'metadata[club_id]': str(club.id),
        'metadata[item_id]': str(item.id),
        'metadata[user_id]': str(user.id),
        'metadata[item_amount_cents]': str(order.item_amount_cents),
        'metadata[platform_fee_cents]': str(platform_fee_cents),
    }
    if club.shop_tax_enabled:
        data['automatic_tax[enabled]'] = 'true'
    if club.shop_shipping_enabled:
        countries = [
            c.strip().upper()
            for c in (club.shop_shipping_countries or 'US').split(',')
            if c.strip()
        ] or ['US']
        for index, country in enumerate(countries):
            data[f'shipping_address_collection[allowed_countries][{index}]'] = country
        shipping_fee_cents = club.shop_shipping_fee_cents or 0
        data['shipping_options[0][shipping_rate_data][type]'] = 'fixed_amount'
        data['shipping_options[0][shipping_rate_data][fixed_amount][amount]'] = str(shipping_fee_cents)
        data['shipping_options[0][shipping_rate_data][fixed_amount][currency]'] = item.currency or 'usd'
        data['shipping_options[0][shipping_rate_data][display_name]'] = (
            'Free club-managed shipping' if shipping_fee_cents == 0 else 'Club-managed shipping'
        )
    if item.image_url:
        data['line_items[0][price_data][product_data][images][0]'] = item.image_url

    headers = _headers()
    headers['Stripe-Account'] = club.stripe_account_id

    response = requests.post(
        f'{STRIPE_API_BASE}/checkout/sessions',
        headers=headers,
        data=data,
        timeout=15,
    )
    if response.status_code >= 400:
        raise StripeConnectError('Stripe could not create the shop checkout session.')
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
