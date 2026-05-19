"""
Visual screenshot test for the new club homepage design.
Run: pytest tests/test_screenshot_homepage.py -v -s
Screenshots saved to tests/screenshots/homepage/
"""
import os, threading, time as _time
from datetime import date, timedelta, time as dtime
import pytest
from app import create_app
from app.extensions import db as _db
from app.models import Club, Ride, ClubPost, ClubLeader, ClubSponsor, ClubWaiver

DESKTOP  = {'width': 1440, 'height': 900}
MOBILE   = {'width': 390,  'height': 844}
PORT     = 5098
DB_PATH  = os.path.join(os.path.dirname(__file__), '_screenshot_test.db')
OUT_DIR  = os.path.join(os.path.dirname(__file__), 'screenshots', 'homepage')
BANNER   = 'https://images.unsplash.com/photo-1541625602330-2277a4c46182?w=1400&q=80'


class Cfg:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = f'sqlite:///{DB_PATH}'
    WTF_CSRF_ENABLED = False
    SECRET_KEY = 'ss-secret'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    STRAVA_CLIENT_ID = STRAVA_CLIENT_SECRET = STRAVA_CLUB_ID = STRAVA_CLUB_REFRESH_TOKEN = None


@pytest.fixture(scope='module')
def srv():
    os.makedirs(OUT_DIR, exist_ok=True)
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    app = create_app(Cfg)
    today = date.today()

    with app.app_context():
        _db.create_all()

        # Club WITH banner, tagline, social, safety
        rbc = Club(
            slug='rbc', name='Reston Bike Club',
            is_hidden=False,
            tagline="Northern Virginia's premier road cycling community since 1972",
            description=(
                'One of the largest cycling clubs in Northern Virginia. '
                'Weekly rides for all levels — Tuesday Worlds to leisurely Sunday spins. '
                'Home of the annual Ken Thompson Reston Century.\n\n'
                'Founded in 1972, RBC welcomes cyclists of all abilities. '
                'We ride rain or shine and believe cycling is best done together.'
            ),
            city='Reston', state='VA', zip_code='20191',
            contact_email='info@restonbikeclub.org',
            banner_url=BANNER,
            facebook_url='https://facebook.com/restonbikeclub',
            instagram_url='https://instagram.com/restonbikeclub',
            newsletter_url='https://restonbikeclub.org/newsletter',
            safety_guidelines=(
                'Always wear a properly fitted helmet — no exceptions.\n'
                'Obey all traffic laws and stop at red lights and stop signs.\n'
                'Call out hazards: "Car back!", "Car up!", "Hole!", "Stopping!".\n'
                'No earbuds or headphones while riding in a group.\n'
                'Carry ID, phone, emergency cash, and a basic repair kit.\n'
                'Ride predictably: no sudden moves, signal turns, and hold your line.'
            ),
        )

        # Club WITHOUT banner (solid color fallback)
        nvcc = Club(
            slug='nvcc', name='Northern Virginia Cycling Club',
            is_hidden=False,
            tagline='Fast-paced road and gravel in the DC suburbs',
            description='Known for challenging Saturday hammerfests.',
            city='McLean', state='VA',
            theme_primary='#1a5276', theme_accent='#f39c12',
        )

        _db.session.add_all([rbc, nvcc])
        _db.session.flush()

        # Rides for RBC
        rides = [
            Ride(club_id=rbc.id, title='RBC Spring Kickoff Ride',
                 date=today + timedelta(days=1), time=dtime(9, 0),
                 meeting_location='Hunterwoods', distance_miles=26.0,
                 elevation_feet=750, pace_category='D'),
            Ride(club_id=rbc.id, title='Tuesday Evening — B Group',
                 date=today + timedelta(days=3), time=dtime(17, 0),
                 meeting_location='Lake Fairfax', distance_miles=28.0,
                 elevation_feet=1350, pace_category='B'),
            Ride(club_id=rbc.id, title='Tuesday Worlds — A Group',
                 date=today + timedelta(days=3), time=dtime(17, 0),
                 meeting_location='Lake Fairfax', distance_miles=38.0,
                 elevation_feet=2100, pace_category='A'),
            Ride(club_id=rbc.id, title='Wednesday Morning Ramble',
                 date=today + timedelta(days=4), time=dtime(10, 0),
                 meeting_location='Reston Town Center', distance_miles=22.0,
                 elevation_feet=800, pace_category='C'),
            Ride(club_id=rbc.id, title='Thursday Evening — B Group',
                 date=today + timedelta(days=5), time=dtime(17, 0),
                 meeting_location='Lake Fairfax', distance_miles=32.0,
                 elevation_feet=1600, pace_category='B'),
        ]
        for r in rides:
            _db.session.add(r)

        # News posts
        _db.session.add_all([
            ClubPost(club_id=rbc.id, title='Season Kickoff This Saturday!',
                     body='Join us for the official start of the 2026 road season. All paces welcome, coffee stop at the turnaround.'),
            ClubPost(club_id=rbc.id, title='New Kit Pre-Order Open',
                     body='The 2026 RBC kit is here. Order by May 1 to guarantee sizing.'),
            ClubPost(club_id=rbc.id, title='Tuesday Worlds Route Change',
                     body='Effective April 8, the A group departs from Lake Fairfax Park.'),
        ])

        # Leaders
        _db.session.add_all([
            ClubLeader(club_id=rbc.id, name='Jake Morrison',
                       bio='A Group lead · 12 yrs experience', display_order=1),
            ClubLeader(club_id=rbc.id, name='Sarah Chen',
                       bio='B Group lead · former Cat 3 racer', display_order=2),
            ClubLeader(club_id=rbc.id, name='Marcus Webb',
                       bio='D Group lead · no-drop specialist', display_order=3),
        ])

        # Sponsors
        _db.session.add_all([
            ClubSponsor(club_id=rbc.id, name='The Bike Lane', display_order=1),
            ClubSponsor(club_id=rbc.id, name="Conte's Cycling", display_order=2),
        ])

        # Waiver
        _db.session.add(ClubWaiver(
            club_id=rbc.id, year=today.year,
            title='2026 RBC Waiver',
            body='I agree to ride safely and follow all club rules.',
        ))

        _db.session.commit()

    t = threading.Thread(
        target=lambda: app.run(host='127.0.0.1', port=PORT,
                               use_reloader=False, threaded=True),
        daemon=True,
    )
    t.start()
    _time.sleep(1.0)
    yield f'http://127.0.0.1:{PORT}', 'rbc', 'nvcc'

    try:
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
    except OSError:
        pass


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_homepage_desktop_overview(srv, browser):
    base, rbc_slug, _ = srv
    page = browser.new_page(viewport=DESKTOP)
    page.goto(f'{base}/clubs/{rbc_slug}/')
    page.wait_for_selector('.club-hero-name')
    page.wait_for_timeout(800)  # let banner image load
    page.screenshot(path=f'{OUT_DIR}/01_desktop_overview.png', full_page=True)
    page.close()


def test_homepage_desktop_rides_tab(srv, browser):
    base, rbc_slug, _ = srv
    page = browser.new_page(viewport=DESKTOP)
    page.goto(f'{base}/clubs/{rbc_slug}/')
    page.wait_for_selector('.club-tab-bar')
    page.locator('.club-tab').filter(has_text='Rides').click()
    page.wait_for_selector('.ride-card')
    page.wait_for_timeout(300)
    page.screenshot(path=f'{OUT_DIR}/02_desktop_rides_tab.png', full_page=True)
    page.close()


def test_homepage_desktop_safety_tab(srv, browser):
    base, rbc_slug, _ = srv
    page = browser.new_page(viewport=DESKTOP)
    page.goto(f'{base}/clubs/{rbc_slug}/')
    page.wait_for_selector('.club-tab-bar')
    page.locator('.club-tab').filter(has_text='Safety').click()
    page.wait_for_timeout(300)
    page.screenshot(path=f'{OUT_DIR}/03_desktop_safety_tab.png', full_page=True)
    page.close()


def test_homepage_hero_closeup(srv, browser):
    """Crop just the hero area to inspect it closely."""
    base, rbc_slug, _ = srv
    page = browser.new_page(viewport=DESKTOP)
    page.goto(f'{base}/clubs/{rbc_slug}/')
    page.wait_for_selector('.club-hero-name')
    page.wait_for_timeout(1200)
    hero = page.locator('.club-hero')
    hero.screenshot(path=f'{OUT_DIR}/04_hero_closeup.png')
    page.close()


def test_homepage_mobile_overview(srv, browser):
    base, rbc_slug, _ = srv
    page = browser.new_page(viewport=MOBILE)
    page.goto(f'{base}/clubs/{rbc_slug}/')
    page.wait_for_selector('.club-hero-name')
    page.wait_for_timeout(800)
    page.screenshot(path=f'{OUT_DIR}/05_mobile_overview.png', full_page=True)
    page.close()


def test_homepage_mobile_rides_tab(srv, browser):
    base, rbc_slug, _ = srv
    page = browser.new_page(viewport=MOBILE)
    page.goto(f'{base}/clubs/{rbc_slug}/')
    page.wait_for_selector('.club-tab-bar')
    page.locator('.club-tab').filter(has_text='Rides').click()
    page.wait_for_selector('.ride-card')
    page.wait_for_timeout(300)
    page.screenshot(path=f'{OUT_DIR}/06_mobile_rides_tab.png', full_page=True)
    page.close()


def test_homepage_no_banner(srv, browser):
    """Club without a banner — should show solid primary color."""
    base, _, nvcc_slug = srv
    page = browser.new_page(viewport=DESKTOP)
    page.goto(f'{base}/clubs/{nvcc_slug}/')
    page.wait_for_selector('.club-hero-name')
    page.wait_for_timeout(400)
    page.screenshot(path=f'{OUT_DIR}/07_no_banner_club.png', full_page=True)
    page.close()


def test_homepage_tab_bar_scroll(srv, browser):
    """Scroll past the hero to verify the tab bar becomes sticky."""
    base, rbc_slug, _ = srv
    page = browser.new_page(viewport=DESKTOP)
    page.goto(f'{base}/clubs/{rbc_slug}/')
    page.wait_for_selector('.club-tab-bar')
    page.wait_for_timeout(800)
    page.evaluate('window.scrollBy(0, 600)')
    page.wait_for_timeout(400)
    page.screenshot(path=f'{OUT_DIR}/08_tab_bar_sticky.png')
    page.close()
