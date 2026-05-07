def test_footer_shows_donate_link(client):
    resp = client.get('/')
    assert resp.status_code == 200
    assert b'href="/donate"' in resp.data
    assert b'Donate' in resp.data


def test_club_footer_shows_donate_link(client, sample_club):
    resp = client.get(f'/clubs/{sample_club.slug}/')
    assert resp.status_code == 200
    assert b'href="/donate"' in resp.data
    assert b'Donate' in resp.data


def test_donate_stub_page_without_config(client, app):
    app.config['DONATE_URL'] = ''
    resp = client.get('/donate')
    assert resp.status_code == 200
    assert b'Stripe donation link coming soon' in resp.data
    assert b'Donate with Stripe' in resp.data
    assert b'Phil Porter' in resp.data
    assert b'cyclist in Northern Virginia' in resp.data
    assert b'passion project' in resp.data


def test_donate_page_links_to_configured_stripe_link(client, app):
    app.config['DONATE_URL'] = 'https://buy.stripe.com/test_donation'
    resp = client.get('/donate')
    assert resp.status_code == 200
    assert b'href="https://buy.stripe.com/test_donation"' in resp.data
    assert b'Support the project securely through Stripe' in resp.data
    assert b'Send a note or suggestion' in resp.data


def test_donate_page_orders_about_donate_feedback(client, app):
    app.config['DONATE_URL'] = 'https://buy.stripe.com/test_donation'
    body = client.get('/donate').get_data(as_text=True)

    assert body.index('About the founder') < body.index('Stripe-hosted donations')
    assert body.index('Stripe-hosted donations') < body.index('Feedback')


def test_donate_page_uses_live_stripe_link(client, app):
    app.config['DONATE_URL'] = 'https://buy.stripe.com/dRm7sFgkK2yb8VwgrZ9AA00'
    resp = client.get('/donate')
    assert resp.status_code == 200
    assert b'href="https://buy.stripe.com/dRm7sFgkK2yb8VwgrZ9AA00"' in resp.data
    assert b'Stripe-hosted donations' in resp.data


def test_donate_rejects_non_http_configured_url(client, app):
    app.config['DONATE_URL'] = 'javascript:alert(1)'
    resp = client.get('/donate')
    assert resp.status_code == 200
    assert b'Stripe donation link coming soon' in resp.data
