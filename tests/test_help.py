from pathlib import Path


HELP_IMAGE_DIR = Path(__file__).resolve().parents[1] / 'app' / 'static' / 'img' / 'help'


def test_help_footer_link_present(client):
    resp = client.get('/')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert '<a class="nav-link" href="/help/">' not in html
    assert 'href="/help/"' in html
    assert 'Help' in html


def test_help_index_links_to_guides(client):
    resp = client.get('/help/')
    assert resp.status_code == 200
    assert b'Club Manager Guide' in resp.data
    assert b'Rider Guide' in resp.data
    assert b'href="/help/club-managers"' in resp.data
    assert b'href="/help/riders"' in resp.data
    assert b'choose email notifications' in resp.data


def test_club_manager_help_page(client):
    resp = client.get('/help/club-managers')
    assert resp.status_code == 200
    assert b'Create your club' in resp.data
    assert b'Publish rides' in resp.data
    assert b'Manage signups' in resp.data
    assert b'Handle paid club dues' in resp.data
    assert b'Keep members informed' in resp.data
    assert b'club news emails are sent right away' in resp.data
    assert b'accidental high-volume email sends' in resp.data
    assert b'does not hold club dues' in resp.data
    assert b'direct charges' in resp.data
    assert b'$1 platform fee' in resp.data
    assert b'is not refunded' in resp.data
    assert b'Clubs handle their own refunds' in resp.data
    assert b'future club store feature' in resp.data
    assert b'Use advanced ride options' in resp.data
    assert b'Garmin GroupRide' in resp.data
    assert b'Transfer club ownership' in resp.data
    assert b'superadmin can' in resp.data
    assert b'manually transfer ownership' in resp.data
    assert b'img/help/club-create.png' in resp.data
    assert b'img/help/club-settings.png' in resp.data
    assert b'img/help/club-dues-settings.png' in resp.data
    assert b'img/help/club-dues-payment.png' in resp.data
    assert b'img/help/club-team.png' in resp.data
    assert b'img/help/club-rides-admin.png' in resp.data


def test_rider_help_page(client):
    resp = client.get('/help/riders')
    assert resp.status_code == 200
    assert b'Find clubs near you' in resp.data
    assert b'Discover and sign up for rides' in resp.data
    assert b'Keep your profile current' in resp.data
    assert b'Manage email notifications' in resp.data
    assert b'Protect your account' in resp.data
    assert b'Control profile privacy' in resp.data
    assert b'Use ride tools' in resp.data
    assert b'Garmin GroupRide Code' in resp.data
    assert b'Profiles are private by default' in resp.data
    assert b'https://www.strava.com/athletes/123456' in resp.data
    assert b'Message board activity is bundled into a daily digest' in resp.data
    assert b'account and security emails are always sent' in resp.data
    assert b'img/help/find-clubs.png' in resp.data
    assert b'img/help/discover-rides.png' in resp.data
    assert b'img/help/ride-detail.png' in resp.data


def test_help_screenshots_exist():
    expected = {
        'club-create.png',
        'club-settings.png',
        'club-dues-settings.png',
        'club-dues-payment.png',
        'club-team.png',
        'club-rides-admin.png',
        'find-clubs.png',
        'discover-rides.png',
        'ride-detail.png',
    }
    for filename in expected:
        path = HELP_IMAGE_DIR / filename
        assert path.exists()
        assert path.stat().st_size > 0
