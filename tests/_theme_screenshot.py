"""
Standalone script — takes legibility screenshots of all 3 clubs on desktop + mobile.
Run: cd /home/nullbnx/Projects/rbc && .venv/bin/python tests/_theme_screenshot.py
"""
import os, sys, threading, time
from datetime import date, timedelta
from datetime import time as dtime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import create_app
from app.extensions import db, bcrypt
from app.models import Club, User, Ride, ClubMembership, ClubAdmin

OUT = os.path.join(os.path.dirname(__file__), 'screenshots', 'theming')
os.makedirs(OUT, exist_ok=True)
PORT = 5198

DB_PATH = os.path.join(os.path.dirname(__file__), '_theme_shot.db')

class Cfg:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = f'sqlite:///{DB_PATH}'
    WTF_CSRF_ENABLED = False
    SECRET_KEY = 'theme-shot-secret'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    STRAVA_CLIENT_ID = STRAVA_CLIENT_SECRET = STRAVA_CLUB_ID = STRAVA_CLUB_REFRESH_TOKEN = None

CLUBS = [
    dict(slug='rbc',     name='Reston Bike Club',                  theme_primary='#2d6a4f', theme_accent='#e76f51',
         tagline="Northern Virginia's premier road cycling community", city='Reston', state='VA'),
    dict(slug='nvcc',    name='Northern Virginia Cycling Club',      theme_primary='#1565c0', theme_accent='#f39c12',
         tagline='Fast-paced road and gravel in the DC suburbs',       city='McLean', state='VA'),
    dict(slug='artemis', name='Artemis Cycling — Women\'s Club',     theme_primary='#6c3483', theme_accent='#e74c3c',
         tagline="Every pace, every level, every ride",               city='Arlington', state='VA'),
]

app = create_app(Cfg)
today = date.today()

if os.path.exists(DB_PATH):
    os.remove(DB_PATH)

with app.app_context():
    db.create_all()
    pw = bcrypt.generate_password_hash('password').decode('utf-8')
    user = User(username='rider', email='rider@test.com', password_hash=pw)
    db.session.add(user)
    db.session.flush()

    for cd in CLUBS:
        club = Club(slug=cd['slug'], name=cd['name'], tagline=cd['tagline'],
                    city=cd['city'], state=cd['state'], is_active=True,
                    theme_primary=cd['theme_primary'], theme_accent=cd['theme_accent'])
        db.session.add(club)
        db.session.flush()
        db.session.add(ClubAdmin(user_id=user.id, club_id=club.id, role='admin'))
        db.session.add(ClubMembership(user_id=user.id, club_id=club.id, status='active'))
        for i in range(3):
            db.session.add(Ride(
                club_id=club.id, title=f'Weekly Ride {i+1}',
                pace_category=['A','B','C'][i],
                date=today + timedelta(days=i+1),
                time=dtime(7+i, 0),
                distance_miles=25 + i*10,
                elevation_feet=600 + i*200,
                meeting_location='Town Center',
            ))
    db.session.commit()

t = threading.Thread(
    target=lambda: app.run(host='127.0.0.1', port=PORT, use_reloader=False, threaded=True),
    daemon=True,
)
t.start()
time.sleep(1.2)

from playwright.sync_api import sync_playwright

DESKTOP = {'width': 1440, 'height': 900}
MOBILE  = {'width': 390,  'height': 844}

with sync_playwright() as p:
    browser = p.chromium.launch()

    for cd in CLUBS:
        slug = cd['slug']
        url  = f'http://127.0.0.1:{PORT}/clubs/{slug}/'

        # Desktop full page
        page = browser.new_page(viewport=DESKTOP)
        page.goto(url)
        page.wait_for_selector('.club-hero-name')
        page.wait_for_timeout(600)
        page.screenshot(path=f'{OUT}/{slug}_desktop.png', full_page=True)

        # Desktop nav closeup
        page.locator('.club-page-nav').screenshot(path=f'{OUT}/{slug}_nav.png')

        # Desktop tab bar closeup
        page.locator('.club-tab-bar').screenshot(path=f'{OUT}/{slug}_tabbar.png')
        page.close()

        # Mobile full page
        page = browser.new_page(viewport=MOBILE)
        page.goto(url)
        page.wait_for_selector('.club-hero-name')
        page.wait_for_timeout(600)
        page.screenshot(path=f'{OUT}/{slug}_mobile.png', full_page=True)

        # Mobile above-fold only
        page.screenshot(path=f'{OUT}/{slug}_mobile_fold.png')
        page.close()

    browser.close()

try:
    os.remove(DB_PATH)
except OSError:
    pass

print(f'\nScreenshots saved to {OUT}/')
for f in sorted(os.listdir(OUT)):
    print(f'  {f}')
