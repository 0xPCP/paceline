"""Tests for club theming: color utilities, CSS injection, form saving."""
import pytest
from app.utils import club_theme_vars, is_valid_hex, _mix_white, _mix_black
from app.models import Club
from app.extensions import db


# ── Color utility unit tests ──────────────────────────────────────────────────

def test_is_valid_hex_accepts_valid():
    assert is_valid_hex('#2d6a4f') is True
    assert is_valid_hex('#FFFFFF') is True
    assert is_valid_hex('#000000') is True
    assert is_valid_hex('#abc123') is True


def test_is_valid_hex_rejects_invalid():
    assert is_valid_hex('') is False
    assert is_valid_hex(None) is False
    assert is_valid_hex('2d6a4f') is False    # missing #
    assert is_valid_hex('#gggggg') is False   # invalid chars
    assert is_valid_hex('#2d6a4') is False    # too short
    assert is_valid_hex('#2d6a4fff') is False  # too long


def test_mix_white_returns_lighter():
    r, g, b = 0x2d, 0x6a, 0x4f
    result = _mix_white('#2d6a4f', 0.5)
    rr, rg, rb = int(result[1:3], 16), int(result[3:5], 16), int(result[5:7], 16)
    assert rr > r
    assert rg > g
    assert rb > b


def test_mix_black_returns_darker():
    r, g, b = 0x2d, 0x6a, 0x4f
    result = _mix_black('#2d6a4f', 0.3)
    rr, rg, rb = int(result[1:3], 16), int(result[3:5], 16), int(result[5:7], 16)
    assert rr < r
    assert rg < g
    assert rb < b


def test_club_theme_vars_empty_when_no_theme(app, sample_club):
    """No CSS vars generated for a club with no theme colors."""
    sample_club.theme_primary = None
    sample_club.theme_accent = None
    assert club_theme_vars(sample_club) == {}


def test_club_theme_vars_primary_generates_four_vars(app, sample_club):
    """Setting theme_primary generates all four green-family variables."""
    sample_club.theme_primary = '#003366'
    vars = club_theme_vars(sample_club)
    assert '--paceline-green-dark' in vars
    assert '--paceline-green' in vars
    assert '--paceline-green-light' in vars
    assert '--paceline-green-pale' in vars
    assert vars['--paceline-green'] == '#003366'


def test_club_theme_vars_primary_dark_is_darker(app, sample_club):
    """--rbc-green-dark should be darker than the primary color."""
    sample_club.theme_primary = '#2d6a4f'
    vars = club_theme_vars(sample_club)
    # dark variant has lower channel values
    p = int('2d', 16)
    d = int(vars['--paceline-green-dark'][1:3], 16)
    assert d < p


def test_club_theme_vars_primary_pale_is_lighter(app, sample_club):
    """--rbc-green-pale should be much lighter than the primary color."""
    sample_club.theme_primary = '#2d6a4f'
    vars = club_theme_vars(sample_club)
    pale_r = int(vars['--paceline-green-pale'][1:3], 16)
    assert pale_r > 200   # well into the light range


def test_club_theme_vars_accent_generates_two_vars(app, sample_club):
    """Setting theme_accent generates both orange-family variables."""
    sample_club.theme_accent = '#cc0033'
    vars = club_theme_vars(sample_club)
    assert '--paceline-orange' in vars
    assert '--paceline-orange-dark' in vars
    assert vars['--paceline-orange'] == '#cc0033'


def test_club_theme_vars_ignores_invalid_hex(app, sample_club):
    """Invalid hex strings are silently ignored — no CSS vars emitted."""
    sample_club.theme_primary = 'not-a-color'
    sample_club.theme_accent = '#gggggg'
    assert club_theme_vars(sample_club) == {}


# ── Template injection tests ──────────────────────────────────────────────────

def test_theme_css_injected_on_club_home(client, sample_club, mock_weather):
    """Club home page injects <style> with CSS vars when theme is set."""
    sample_club.theme_primary = '#003366'
    db.session.commit()

    resp = client.get(f'/clubs/{sample_club.slug}/')
    assert resp.status_code == 200
    assert b'--paceline-green' in resp.data
    assert b'#003366' in resp.data


def test_no_theme_css_without_theme(client, sample_club, mock_weather):
    """No extra <style> block is injected when club has no theme."""
    sample_club.theme_primary = None
    sample_club.theme_accent = None
    db.session.commit()

    resp = client.get(f'/clubs/{sample_club.slug}/')
    assert resp.status_code == 200
    assert b'--paceline-green-dark' not in resp.data


def test_theme_css_injected_on_calendar(client, sample_club, regular_user, mock_weather):
    """Club calendar list page also gets the theme CSS."""
    from tests.conftest import login
    sample_club.theme_primary = '#880000'
    db.session.commit()

    login(client)
    resp = client.get(f'/clubs/{sample_club.slug}/rides/')
    assert resp.status_code == 200
    assert b'--paceline-green' in resp.data


def test_theme_css_injected_on_ride_detail(client, sample_club, sample_rides, regular_user, mock_weather):
    """Ride detail page gets the theme CSS."""
    from tests.conftest import login
    sample_club.theme_accent = '#cc3300'
    db.session.commit()

    ride = sample_rides[0]
    login(client)
    resp = client.get(f'/clubs/{sample_club.slug}/rides/{ride.id}')
    assert resp.status_code == 200
    assert b'--paceline-orange' in resp.data


# ── Logo / banner display tests ───────────────────────────────────────────────

def test_logo_shown_on_club_home(client, sample_club, mock_weather):
    """Logo image tag is present when club has a logo_url."""
    sample_club.logo_url = 'https://example.com/logo.png'
    db.session.commit()

    resp = client.get(f'/clubs/{sample_club.slug}/')
    assert resp.status_code == 200
    assert b'logo.png' in resp.data
    assert b'<img' in resp.data


def test_no_logo_img_without_logo_url(client, sample_club, mock_weather):
    """No logo image tag when club has no logo_url."""
    sample_club.logo_url = None
    db.session.commit()

    resp = client.get(f'/clubs/{sample_club.slug}/')
    assert b'object-fit:contain' not in resp.data


def test_banner_url_applied_to_club_home(client, sample_club, mock_weather):
    """Banner URL is rendered as an image, not inline CSS, when set."""
    sample_club.banner_url = 'https://example.com/banner.jpg'
    db.session.commit()

    resp = client.get(f'/clubs/{sample_club.slug}/')
    assert b'banner.jpg' in resp.data
    assert b'background-image' not in resp.data


# ── Admin settings form tests ─────────────────────────────────────────────────

def test_settings_saves_theme_colors(client, app, sample_club, club_admin_user):
    """Admin can save theme_primary and theme_accent via club settings form."""
    from tests.conftest import login
    login(client, email='clubadmin@test.com')

    resp = client.post(
        f'/admin/clubs/{sample_club.slug}/settings',
        data={
            'name': sample_club.name,
            'theme_primary': '#003366',
            'theme_accent': '#cc0033',
            'cancel_rain_prob': '80',
            'cancel_wind_mph': '35',
            'cancel_temp_min_f': '28',
            'cancel_temp_max_f': '100',
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    db.session.refresh(sample_club)
    assert sample_club.theme_primary == '#003366'
    assert sample_club.theme_accent == '#cc0033'


def test_settings_clears_theme_when_blank(client, app, sample_club, club_admin_user):
    """Submitting blank colors clears them (sets to None)."""
    sample_club.theme_primary = '#003366'
    db.session.commit()

    from tests.conftest import login
    login(client, email='clubadmin@test.com')

    resp = client.post(
        f'/admin/clubs/{sample_club.slug}/settings',
        data={
            'name': sample_club.name,
            'theme_primary': '',
            'theme_accent': '',
            'cancel_rain_prob': '80',
            'cancel_wind_mph': '35',
            'cancel_temp_min_f': '28',
            'cancel_temp_max_f': '100',
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    db.session.refresh(sample_club)
    assert sample_club.theme_primary is None


def test_settings_rejects_invalid_hex(client, app, sample_club, club_admin_user):
    """Form validation rejects malformed hex colors."""
    from tests.conftest import login
    login(client, email='clubadmin@test.com')

    resp = client.post(
        f'/admin/clubs/{sample_club.slug}/settings',
        data={
            'name': sample_club.name,
            'theme_primary': 'not-a-color',
            'cancel_rain_prob': '80',
            'cancel_wind_mph': '35',
            'cancel_temp_min_f': '28',
            'cancel_temp_max_f': '100',
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    # Form re-renders with validation error, color not saved
    db.session.refresh(sample_club)
    assert sample_club.theme_primary != 'not-a-color'


def test_settings_saves_banner_url(client, app, sample_club, club_admin_user):
    """Banner URL is saved via club settings."""
    from tests.conftest import login
    login(client, email='clubadmin@test.com')

    resp = client.post(
        f'/admin/clubs/{sample_club.slug}/settings',
        data={
            'name': sample_club.name,
            'banner_url': 'https://example.com/banner.jpg',
            'cancel_rain_prob': '80',
            'cancel_wind_mph': '35',
            'cancel_temp_min_f': '28',
            'cancel_temp_max_f': '100',
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    db.session.refresh(sample_club)
    assert sample_club.banner_url == 'https://example.com/banner.jpg'


def test_club_default_homepage_layout_is_magazine(app, db):
    club = Club(slug='layout-default', name='Layout Default Club')
    db.session.add(club)
    db.session.commit()
    assert club.homepage_layout == 'magazine'


def test_settings_saves_homepage_layout(client, app, sample_club, club_admin_user):
    from tests.conftest import login
    login(client, email='clubadmin@test.com')

    resp = client.post(
        f'/admin/clubs/{sample_club.slug}/settings',
        data={
            'name': sample_club.name,
            'homepage_layout': 'newspaper',
            'cancel_rain_prob': '80',
            'cancel_wind_mph': '35',
            'cancel_temp_min_f': '28',
            'cancel_temp_max_f': '100',
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    db.session.refresh(sample_club)
    assert sample_club.homepage_layout == 'newspaper'


def test_club_home_uses_selected_homepage_layout(client, app, sample_club, db):
    sample_club.homepage_layout = 'newspaper'
    db.session.commit()

    resp = client.get(f'/clubs/{sample_club.slug}/')
    assert resp.status_code == 200
    assert b'remix-paper' in resp.data


def test_club_home_layout_preview_override(client, app, sample_club):
    resp = client.get(f'/clubs/{sample_club.slug}/?layout=dashboard')
    assert resp.status_code == 200
    assert b'club-concept-dashboard' in resp.data
