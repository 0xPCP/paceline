from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.models import ClubShopItem, ClubShopOrder
from tests.conftest import login


def _settings_payload(club, **overrides):
    data = {
        'name': club.name,
        'tagline': '',
        'description': club.description or '',
        'city': club.city or '',
        'state': club.state or '',
        'zip_code': club.zip_code or '',
        'address': '',
        'contact_email': '',
        'logo_url': '',
        'theme_primary': '',
        'theme_accent': '',
        'banner_url': '',
        'strava_club_id': '',
        'hosting_mode': 'full',
        'join_approval': 'auto',
        'membership_dues_amount': '',
        'membership_duration_months': '12',
        'facebook_url': '',
        'instagram_url': '',
        'twitter_url': '',
        'newsletter_url': '',
        'whatsapp_url': '',
        'bylaws_url': '',
        'safety_guidelines': '',
        'cancel_rain_prob': '80',
        'cancel_wind_mph': '35',
        'cancel_temp_min_f': '28',
        'cancel_temp_max_f': '100',
    }
    data.update(overrides)
    return data


def test_club_settings_save_and_render_whatsapp_url(client, db, sample_club, club_admin_user, mock_weather):
    login(client, club_admin_user.email)
    response = client.post(
        f'/admin/clubs/{sample_club.slug}/settings',
        data=_settings_payload(sample_club, whatsapp_url='https://chat.whatsapp.com/example'),
        follow_redirects=True,
    )

    assert response.status_code == 200
    db.session.refresh(sample_club)
    assert sample_club.whatsapp_url == 'https://chat.whatsapp.com/example'

    public = client.get(f'/clubs/{sample_club.slug}/')
    assert public.status_code == 200
    assert b'WhatsApp' in public.data
    assert b'https://chat.whatsapp.com/example' in public.data


def test_admin_can_create_shop_item_and_public_shop_renders(client, db, sample_club, club_admin_user):
    login(client, club_admin_user.email)
    response = client.post(
        f'/admin/clubs/{sample_club.slug}/shop/new',
        data={
            'name': 'Club Jersey',
            'description': 'Short sleeve team jersey.',
            'image_url': 'https://example.com/jersey.jpg',
            'price': '65.00',
            'is_active': 'y',
            'display_order': '2',
            'fulfillment_notes': 'Pickup at a club ride.',
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b'Club Jersey' in response.data
    item = ClubShopItem.query.filter_by(club_id=sample_club.id, name='Club Jersey').first()
    assert item is not None
    assert item.price_cents == 6500

    public = client.get(f'/clubs/{sample_club.slug}/shop/')
    assert public.status_code == 200
    assert b'Club Jersey' in public.data
    assert b'+$1 Paceline fee' in public.data


def test_admin_can_configure_shop_tax_and_shipping(client, db, sample_club, club_admin_user):
    login(client, club_admin_user.email)
    response = client.post(
        f'/admin/clubs/{sample_club.slug}/shop/settings',
        data={
            'shop_tax_enabled': 'y',
            'shop_shipping_enabled': 'y',
            'shop_shipping_fee': '7.50',
            'shop_shipping_countries': 'US, ca',
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    db.session.refresh(sample_club)
    assert sample_club.shop_tax_enabled is True
    assert sample_club.shop_shipping_enabled is True
    assert sample_club.shop_shipping_fee_cents == 750
    assert sample_club.shop_shipping_countries == 'US,CA'


def test_shop_limits_active_items_to_50(client, db, sample_club, club_admin_user):
    for idx in range(50):
        db.session.add(ClubShopItem(
            club_id=sample_club.id,
            name=f'Item {idx}',
            price_cents=1000,
            is_active=True,
        ))
    db.session.commit()

    login(client, club_admin_user.email)
    response = client.post(
        f'/admin/clubs/{sample_club.slug}/shop/new',
        data={
            'name': 'Extra Item',
            'price': '10.00',
            'is_active': 'y',
            'display_order': '0',
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b'50 active shop items' in response.data
    assert ClubShopItem.query.filter_by(club_id=sample_club.id, is_active=True).count() == 50
    assert ClubShopItem.query.filter_by(club_id=sample_club.id, name='Extra Item').first() is None


def test_delete_shop_item_with_order_archives_instead(client, db, sample_club, club_admin_user, regular_user):
    item = ClubShopItem(club_id=sample_club.id, name='Ordered Tee', price_cents=2500, is_active=True)
    db.session.add(item)
    db.session.flush()
    db.session.add(ClubShopOrder(
        club_id=sample_club.id,
        item_id=item.id,
        user_id=regular_user.id,
        item_amount_cents=2500,
        platform_fee_cents=100,
        amount_cents=2600,
    ))
    db.session.commit()

    login(client, club_admin_user.email)
    response = client.post(
        f'/admin/clubs/{sample_club.slug}/shop/{item.id}/delete',
        follow_redirects=True,
    )

    assert response.status_code == 200
    db.session.refresh(item)
    assert item.is_active is False
    assert ClubShopOrder.query.filter_by(item_id=item.id).count() == 1


def test_shop_checkout_creates_order_and_redirects(client, app, db, sample_club, regular_user, monkeypatch):
    app.config['STRIPE_SECRET_KEY'] = 'sk_test_fake'
    app.config['STRIPE_PLATFORM_FEE_CENTS'] = 100
    sample_club.stripe_account_id = 'acct_123'
    sample_club.stripe_account_connected_at = datetime.now(timezone.utc)
    item = ClubShopItem(club_id=sample_club.id, name='Club Tee', price_cents=2500, is_active=True)
    db.session.add(item)
    db.session.commit()

    def fake_checkout(**kwargs):
        assert kwargs['club'].id == sample_club.id
        assert kwargs['item'].id == item.id
        assert kwargs['order'].item_amount_cents == 2500
        assert kwargs['order'].platform_fee_cents == 100
        assert kwargs['order'].amount_cents == 2600
        return {'id': 'cs_shop_123', 'url': 'https://checkout.stripe.com/c/shop'}

    monkeypatch.setattr('app.routes.stripe_connect.create_shop_checkout_session', fake_checkout)

    login(client, regular_user.email)
    response = client.post(f'/stripe/clubs/{sample_club.slug}/shop/{item.id}/checkout')

    assert response.status_code == 302
    assert response.headers['Location'] == 'https://checkout.stripe.com/c/shop'
    order = ClubShopOrder.query.filter_by(provider_session_id='cs_shop_123').first()
    assert order is not None
    assert order.amount_cents == 2600
    assert order.status == 'pending'


def test_create_shop_checkout_session_uses_direct_charge_and_platform_fee(app):
    from app.stripe_connect import create_shop_checkout_session

    club = MagicMock()
    club.id = 1
    club.name = 'Test Club'
    club.stripe_account_id = 'acct_test_123'
    club.shop_tax_enabled = False
    club.shop_shipping_enabled = False

    user = MagicMock()
    user.id = 2
    user.email = 'rider@test.com'

    item = MagicMock()
    item.id = 3
    item.name = 'Club Jersey'
    item.description = 'Team kit'
    item.currency = 'usd'
    item.image_url = 'https://example.com/jersey.jpg'

    order = MagicMock()
    order.id = 4
    order.item_amount_cents = 6500
    order.platform_fee_cents = 100

    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {'id': 'cs_shop_abc', 'url': 'https://checkout.stripe.com/c/shop'}

    with app.app_context():
        app.config['STRIPE_SECRET_KEY'] = 'sk_test_fake'
        app.config['STRIPE_PLATFORM_FEE_CENTS'] = 100
        with patch('app.stripe_connect.requests.post', return_value=fake_response) as mock_post:
            create_shop_checkout_session(
                club=club,
                user=user,
                item=item,
                order=order,
                success_url='https://example.com/success',
                cancel_url='https://example.com/cancel',
            )

    posted_headers = mock_post.call_args.kwargs['headers']
    posted_data = mock_post.call_args.kwargs['data']

    assert posted_headers.get('Stripe-Account') == 'acct_test_123'
    assert posted_data['line_items[0][price_data][unit_amount]'] == '6500'
    assert posted_data['line_items[1][price_data][unit_amount]'] == '100'
    assert posted_data['line_items[1][price_data][product_data][name]'] == 'Paceline platform fee'
    assert posted_data['payment_intent_data[application_fee_amount]'] == '100'
    assert posted_data['metadata[kind]'] == 'club_shop_order'
    assert posted_data['metadata[item_amount_cents]'] == '6500'
    assert posted_data['metadata[platform_fee_cents]'] == '100'
    assert 'payment_intent_data[transfer_data][destination]' not in posted_data


def test_create_shop_checkout_session_adds_tax_and_shipping_when_enabled(app):
    from app.stripe_connect import create_shop_checkout_session

    club = MagicMock()
    club.id = 1
    club.name = 'Test Club'
    club.stripe_account_id = 'acct_test_123'
    club.shop_tax_enabled = True
    club.shop_shipping_enabled = True
    club.shop_shipping_fee_cents = 750
    club.shop_shipping_countries = 'US,CA'

    user = MagicMock()
    user.id = 2
    user.email = 'rider@test.com'

    item = MagicMock()
    item.id = 3
    item.name = 'Club Jersey'
    item.description = 'Team kit'
    item.currency = 'usd'
    item.image_url = None

    order = MagicMock()
    order.id = 4
    order.item_amount_cents = 6500
    order.platform_fee_cents = 100

    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {'id': 'cs_shop_tax', 'url': 'https://checkout.stripe.com/c/shop'}

    with app.app_context():
        app.config['STRIPE_SECRET_KEY'] = 'sk_test_fake'
        app.config['STRIPE_PLATFORM_FEE_CENTS'] = 100
        with patch('app.stripe_connect.requests.post', return_value=fake_response) as mock_post:
            create_shop_checkout_session(
                club=club,
                user=user,
                item=item,
                order=order,
                success_url='https://example.com/success',
                cancel_url='https://example.com/cancel',
            )

    posted_data = mock_post.call_args.kwargs['data']
    assert posted_data['automatic_tax[enabled]'] == 'true'
    assert posted_data['shipping_address_collection[allowed_countries][0]'] == 'US'
    assert posted_data['shipping_address_collection[allowed_countries][1]'] == 'CA'
    assert posted_data['shipping_options[0][shipping_rate_data][fixed_amount][amount]'] == '750'
    assert posted_data['shipping_options[0][shipping_rate_data][display_name]'] == 'Club-managed shipping'
