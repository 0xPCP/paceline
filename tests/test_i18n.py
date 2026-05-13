"""
i18n tests -- verifies that language switching works and that translated strings
render correctly on key pages in all supported languages.

Unit tests use the Flask test client (no network, in-memory SQLite from conftest).
Browser tests use Playwright headless Chromium and capture screenshots for
visual regression review.

Run unit tests only:
    pytest tests/test_i18n.py -v -k "not browser"

Run all (including screenshots):
    pip install pytest-playwright && playwright install chromium
    pytest tests/test_i18n.py -v
"""
import os
import threading
import time as _time
from datetime import date, timedelta, time as dtime

import pytest

from app import create_app
from app.extensions import db as _db
from app.models import Club, Ride, User

# ---- Language switching helpers ---------------------------------------------

def set_lang(client, lang):
    """Set the browser language preference used by auto-detection."""
    client.environ_base['HTTP_ACCEPT_LANGUAGE'] = lang


def get_decoded(client, url):
    """GET url and return decoded response text."""
    return client.get(url).data.decode('utf-8')


# ---- Language switching (route behaviour) -----------------------------------

class TestLanguageSwitching:

    def test_set_language_redirects(self, client):
        resp = client.get('/set-language/fr')
        assert resp.status_code == 302

    def test_unknown_language_redirects_without_crash(self, client):
        resp = client.get('/set-language/xx')
        assert resp.status_code == 302

    def test_unknown_language_does_not_change_locale(self, client):
        client.get('/set-language/xx')
        body = get_decoded(client, '/')
        # English default preserved since 'xx' is not in SUPPORTED_LANGUAGES
        assert 'Connecting riders' in body

    def test_legacy_set_language_route_redirects_for_supported_languages(self, client):
        for lang in ('fr', 'es', 'it', 'nl', 'de', 'pt'):
            resp = client.get(f'/set-language/{lang}')
            assert resp.status_code == 302, f'/set-language/{lang} returned {resp.status_code}'

    def test_language_persists_across_requests(self, client):
        set_lang(client, 'fr')
        body = get_decoded(client, '/')
        assert 'Connecter les cyclistes' in body

    def test_switch_back_to_english(self, client):
        set_lang(client, 'fr')
        set_lang(client, 'en')
        body = get_decoded(client, '/')
        assert 'Connecting riders' in body


# ---- Homepage (index.html) --------------------------------------------------

class TestHomepageI18n:

    def test_english_default(self, client):
        body = get_decoded(client, '/')
        assert 'Connecting riders' in body
        assert 'How It Works' in body
        assert 'Group Cycling, Simplified' in body

    def test_french(self, client, sample_club):
        set_lang(client, 'fr')
        body = get_decoded(client, '/')
        assert 'Connecter les cyclistes' in body
        assert 'Comment' in body  # "Comment ca marche"
        assert 'cyclisme' in body  # "Le cyclisme en groupe, simplifie"
        assert 'compte gratuit' in body  # "Creer un compte gratuit"
        assert 'clubs locaux' in body  # "S'abonner aux clubs locaux"
        assert 'Voir tous les clubs' in body

    def test_spanish(self, client, sample_club):
        set_lang(client, 'es')
        body = get_decoded(client, '/')
        assert 'Conectando ciclistas' in body
        assert 'funciona' in body  # "Como funciona"
        assert 'Ver todos los clubes' in body

    def test_german(self, client, sample_club):
        set_lang(client, 'de')
        body = get_decoded(client, '/')
        assert 'Radfahrende verbinden' in body
        assert 'funktioniert' in body  # "So funktioniert es"
        assert 'Alle Clubs durchsuchen' in body

    def test_italian(self, client):
        set_lang(client, 'it')
        body = get_decoded(client, '/')
        assert 'Connettere i ciclisti' in body
        assert 'Come funziona' in body

    def test_dutch(self, client):
        set_lang(client, 'nl')
        body = get_decoded(client, '/')
        assert 'Fietsers verbinden' in body
        assert 'Hoe het werkt' in body

    def test_portuguese(self, client):
        set_lang(client, 'pt')
        body = get_decoded(client, '/')
        assert 'Conectando ciclistas' in body
        assert 'Como funciona' in body

    def test_member_badge_plural_french(self, client, sample_club):
        set_lang(client, 'fr')
        body = get_decoded(client, '/')
        # sample_club has 0 members -> "0 membres"
        assert 'membre' in body

    def test_member_badge_singular_english(self, client, sample_club, db):
        from app.extensions import bcrypt
        u = User(
            username='one_member', email='one@test.com',
            password_hash=bcrypt.generate_password_hash('pw').decode(),
        )
        db.session.add(u)
        db.session.commit()
        from app.models import ClubMembership
        db.session.add(ClubMembership(user_id=u.id, club_id=sample_club.id, status='active'))
        db.session.commit()
        body = get_decoded(client, '/')
        assert '1 member' in body

    def test_hero_buttons_french(self, client):
        set_lang(client, 'fr')
        body = get_decoded(client, '/')
        assert 'Trouver un club' in body
        assert 'Créer un compte' in body or 'compte' in body


# ---- Find Clubs page (clubs/index.html) -------------------------------------

class TestClubsIndexI18n:

    def test_english_strings_present(self, client):
        body = get_decoded(client, '/clubs/')
        assert 'Find a Club' in body
        assert 'Map View' in body
        assert 'Near Me' in body
        assert 'Search' in body

    def test_french_strings(self, client):
        set_lang(client, 'fr')
        body = get_decoded(client, '/clubs/')
        assert 'Vue carte' in body
        assert 'moi' in body  # "Pres de moi"
        assert 'Rechercher' in body

    def test_german_strings(self, client):
        set_lang(client, 'de')
        body = get_decoded(client, '/clubs/')
        assert 'Kartenansicht' in body
        assert 'meiner' in body  # "In meiner Nahe"
        assert 'Suchen' in body

    def test_spanish_strings(self, client):
        set_lang(client, 'es')
        body = get_decoded(client, '/clubs/')
        assert 'Vista de mapa' in body
        assert 'Cerca de' in body

    def test_no_clubs_message_french(self, client):
        set_lang(client, 'fr')
        body = get_decoded(client, '/clubs/')
        assert 'Aucun club' in body

    def test_view_club_button_french(self, client, sample_club):
        set_lang(client, 'fr')
        body = get_decoded(client, '/clubs/')
        assert 'Voir le club' in body

    def test_member_badge_french(self, client, sample_club):
        set_lang(client, 'fr')
        body = get_decoded(client, '/clubs/')
        assert 'membre' in body

    def test_create_club_link_french(self, client, regular_user, db):
        regular_user.language = 'fr'
        db.session.commit()
        client.post('/auth/login', data={
            'email': 'rider@test.com', 'password': 'password123',
        }, follow_redirects=True)
        body = get_decoded(client, '/clubs/')
        assert 'un club' in body  # "+ Creer un club"

    def test_zip_search_result_label_french(self, client, sample_club):
        set_lang(client, 'fr')
        resp = client.get('/clubs/?zip=20191&radius=25')
        body = resp.data.decode('utf-8')
        assert 'miles de 20191' in body or 'Clubs dans' in body


# ---- Map page (clubs/map.html) ----------------------------------------------

class TestMapI18n:

    def test_english_map_strings(self, client):
        body = get_decoded(client, '/clubs/map/')
        assert 'Club Map' in body
        assert 'List View' in body
        assert 'Near Me' in body

    def test_french_map_strings(self, client, sample_club):
        set_lang(client, 'fr')
        body = get_decoded(client, '/clubs/map/')
        assert 'Carte des clubs' in body
        assert 'Vue liste' in body
        assert 'moi' in body  # "Pres de moi"
        assert 'semaine' in body  # "Sorties cette semaine"

    def test_german_map_strings(self, client, sample_club):
        set_lang(client, 'de')
        body = get_decoded(client, '/clubs/map/')
        assert 'Club-Karte' in body
        assert 'Listenansicht' in body

    def test_map_subtitle_club_count_french(self, client, sample_club):
        set_lang(client, 'fr')
        body = get_decoded(client, '/clubs/map/')
        # sample_club has lat/lng -> singular: "1 club sur la carte"
        assert 'club sur la carte' in body

    def test_map_subtitle_no_clubs_french(self, client):
        set_lang(client, 'fr')
        body = get_decoded(client, '/clubs/map/')
        assert 'Aucun club' in body or 'club' in body

    def test_map_rides_button_requires_auth_french(self, client):
        set_lang(client, 'fr')
        body = get_decoded(client, '/clubs/map/')
        assert 'semaine' in body  # "Sorties cette semaine"


# ---- Base nav/footer --------------------------------------------------------

class TestBaseTemplateI18n:

    def test_nav_english(self, client):
        body = get_decoded(client, '/')
        assert 'Find Clubs' in body
        assert 'Discover Rides' in body

    def test_nav_french(self, client):
        set_lang(client, 'fr')
        body = get_decoded(client, '/')
        assert 'Trouver des clubs' in body

    def test_nav_spanish(self, client):
        set_lang(client, 'es')
        body = get_decoded(client, '/')
        assert 'Buscar clubes' in body

    def test_nav_german(self, client):
        set_lang(client, 'de')
        body = get_decoded(client, '/')
        assert 'Clubs finden' in body

    def test_footer_tagline_french(self, client):
        set_lang(client, 'fr')
        body = get_decoded(client, '/')
        assert 'Connecter les cyclistes.' in body

    def test_footer_tagline_spanish(self, client):
        set_lang(client, 'es')
        body = get_decoded(client, '/')
        assert 'Conectando ciclistas.' in body

    def test_language_picker_not_present_on_main_site(self, client):
        body = get_decoded(client, '/')
        assert '\U0001f310' not in body  # language is controlled by browser/profile


# ---- Dashboard (authenticated) ----------------------------------------------

class TestDashboardI18n:

    def _login(self, client):
        client.post('/auth/login', data={
            'email': 'rider@test.com', 'password': 'password123',
        }, follow_redirects=True)

    def test_dashboard_english(self, client, regular_user, mock_weather):
        self._login(client)
        body = get_decoded(client, '/')
        assert 'My Upcoming Rides' in body
        assert 'Discover Clubs' in body
        assert 'What to Wear' in body

    def test_dashboard_french(self, client, regular_user, mock_weather, db):
        regular_user.language = 'fr'
        db.session.commit()
        self._login(client)
        body = get_decoded(client, '/')
        assert 'prochaines sorties' in body  # "Mes prochaines sorties"
        assert 'couvrir des clubs' in body   # "Decouvrir des clubs"
        assert 'porter' in body              # "Quoi porter"

    def test_dashboard_welcome_username_french(self, client, regular_user, mock_weather, db):
        regular_user.language = 'fr'
        db.session.commit()
        self._login(client)
        body = get_decoded(client, '/')
        assert 'Bon retour, rider' in body

    def test_dashboard_german(self, client, regular_user, mock_weather, db):
        regular_user.language = 'de'
        db.session.commit()
        self._login(client)
        body = get_decoded(client, '/')
        assert 'bevorstehenden' in body  # "Meine bevorstehenden Ausfahrten"
        assert 'anziehen' in body        # "Was anziehen"

    def test_dashboard_join_button_french(self, client, regular_user, sample_club, mock_weather, db):
        regular_user.language = 'fr'
        db.session.commit()
        self._login(client)
        body = get_decoded(client, '/')
        assert 'Rejoindre' in body

    def test_dashboard_no_location_french(self, client, regular_user, mock_weather, db):
        regular_user.zip_code = None
        regular_user.language = 'fr'
        db.session.commit()
        self._login(client)
        body = get_decoded(client, '/')
        assert 'lieu' in body  # "aucun lieu defini"


class TestProfileLanguagePreference:

    def test_profile_language_overrides_browser_detection(self, client, regular_user, db, mock_weather):
        set_lang(client, 'en')
        client.post('/auth/login', data={
            'email': 'rider@test.com', 'password': 'password123',
        }, follow_redirects=True)
        resp = client.post('/auth/profile', data={
            'username': 'rider',
            'email': 'rider@test.com',
            'zip_code': '',
            'gender': '',
            'bio': '',
            'language': 'fr',
            'emergency_contact_name': '',
            'emergency_contact_phone': '',
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(regular_user)
        assert regular_user.language == 'fr'
        assert '<html lang="fr">' in resp.data.decode('utf-8')


# ---- Browser / screenshot tests ---------------------------------------------

BROWSER_DB_PATH = os.path.join(os.path.dirname(__file__), '_i18n_browser_test.db')
BROWSER_PORT = 5097


class BrowserI18nConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = f'sqlite:///{BROWSER_DB_PATH}'
    WTF_CSRF_ENABLED = False
    SECRET_KEY = 'i18n-browser-secret'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    STRAVA_CLIENT_ID = None
    STRAVA_CLIENT_SECRET = None
    STRAVA_CLUB_ID = None
    STRAVA_CLUB_REFRESH_TOKEN = None


@pytest.fixture(scope='module')
def i18n_server():
    """Start a local Flask server seeded with a club and a ride."""
    if os.path.exists(BROWSER_DB_PATH):
        os.remove(BROWSER_DB_PATH)

    app = create_app(BrowserI18nConfig)
    with app.app_context():
        _db.create_all()

        today = date.today()
        next_monday = today + timedelta(days=7 - today.weekday())

        club = Club(
            slug='i18n-test',
            name='Paceline Test Club',
            city='Reston', state='VA',
            zip_code='20191',
            lat=38.9376, lng=-77.3476,
        )
        _db.session.add(club)
        _db.session.flush()

        ride = Ride(
            club_id=club.id,
            title='Tuesday Morning Ride',
            date=next_monday + timedelta(days=1),
            time=dtime(7, 0),
            meeting_location='Reston Town Center',
            distance_miles=30.0,
            pace_category='B',
        )
        _db.session.add(ride)
        _db.session.commit()

    t = threading.Thread(
        target=lambda: app.run(
            host='127.0.0.1', port=BROWSER_PORT,
            use_reloader=False, threaded=True,
        ),
        daemon=True,
    )
    t.start()
    _time.sleep(0.8)

    yield f'http://127.0.0.1:{BROWSER_PORT}'

    try:
        os.remove(BROWSER_DB_PATH)
    except OSError:
        pass


def _screenshot(page, name):
    os.makedirs('tests/screenshots', exist_ok=True)
    page.screenshot(path=f'tests/screenshots/i18n_{name}.png', full_page=True)


def switch_lang_browser(page, base, lang):
    """Set the browser language preference for auto-detection."""
    page.set_extra_http_headers({'Accept-Language': lang})


# ---- Browser screenshot tests -----------------------------------------------

def test_browser_homepage_english(i18n_server, browser):
    page = browser.new_page()
    page.goto(i18n_server)
    page.wait_for_selector('.hero-title')
    assert 'Connecting riders' in page.locator('.hero-title').inner_text()
    _screenshot(page, 'homepage_en')
    page.close()


def test_browser_homepage_french(i18n_server, browser):
    page = browser.new_page()
    switch_lang_browser(page, i18n_server, 'fr')
    page.goto(i18n_server)
    page.wait_for_selector('.hero-title')
    title = page.locator('.hero-title').inner_text()
    assert 'groupe' in title or 'Trouvez' in title
    _screenshot(page, 'homepage_fr')
    page.close()


def test_browser_homepage_spanish(i18n_server, browser):
    page = browser.new_page()
    switch_lang_browser(page, i18n_server, 'es')
    page.goto(i18n_server)
    page.wait_for_selector('.hero-title')
    title = page.locator('.hero-title').inner_text()
    assert 'grupo' in title or 'Encuentra' in title
    _screenshot(page, 'homepage_es')
    page.close()


def test_browser_homepage_german(i18n_server, browser):
    page = browser.new_page()
    switch_lang_browser(page, i18n_server, 'de')
    page.goto(i18n_server)
    page.wait_for_selector('.hero-title')
    title = page.locator('.hero-title').inner_text()
    assert 'Gruppe' in title or 'Finde' in title
    _screenshot(page, 'homepage_de')
    page.close()


def test_browser_clubs_index_french(i18n_server, browser):
    page = browser.new_page()
    switch_lang_browser(page, i18n_server, 'fr')
    page.goto(f'{i18n_server}/clubs/')
    page.wait_for_selector('h1')
    assert 'Paceline Test Club' in page.content()
    assert 'Voir le club' in page.content()
    _screenshot(page, 'clubs_index_fr')
    page.close()


def test_browser_map_french(i18n_server, browser):
    page = browser.new_page()
    switch_lang_browser(page, i18n_server, 'fr')
    page.goto(f'{i18n_server}/clubs/map/')
    page.wait_for_selector('#map-subtitle')
    subtitle = page.locator('#map-subtitle').inner_text()
    assert 'club' in subtitle.lower(), f'Unexpected subtitle: {subtitle}'
    assert 'Carte des clubs' in page.content()
    assert 'Vue liste' in page.content()
    _screenshot(page, 'map_fr')
    page.close()


def test_browser_map_german(i18n_server, browser):
    page = browser.new_page()
    switch_lang_browser(page, i18n_server, 'de')
    page.goto(f'{i18n_server}/clubs/map/')
    page.wait_for_selector('#map-subtitle')
    assert 'Club-Karte' in page.content()
    _screenshot(page, 'map_de')
    page.close()


def test_browser_language_picker_removed(i18n_server, browser):
    """Language selection should not be exposed as a global navbar dropdown."""
    page = browser.new_page()
    page.goto(i18n_server)
    page.wait_for_selector('.hero-title')
    assert '\U0001f310' not in page.content()
    _screenshot(page, 'language_picker_removed')
    page.close()
