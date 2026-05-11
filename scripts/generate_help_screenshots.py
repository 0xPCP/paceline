import os
import sys
import threading
import time as time_module
from datetime import date, datetime, time, timedelta, timezone

from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app import create_app
from app.extensions import bcrypt, db
from app.models import Club, ClubAdmin, ClubMembership, Ride, RideSignup, User


OUTPUT_DIR = os.path.join(ROOT_DIR, 'app', 'static', 'img', 'help')
DB_PATH = os.path.join('/tmp', 'paceline_help_screenshots.db')
PORT = 5210
BASE_URL = f'http://127.0.0.1:{PORT}'


class ScreenshotConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = f'sqlite:///{DB_PATH}'
    WTF_CSRF_ENABLED = False
    SECRET_KEY = 'help-screenshot-secret'
    COOKIE_SECURE = False
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = 'Lax'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    STRAVA_CLIENT_ID = None
    STRAVA_CLIENT_SECRET = None
    STRAVA_CLUB_ID = None
    STRAVA_CLUB_REFRESH_TOKEN = None


class ServerThread(threading.Thread):
    def __init__(self, app):
        super().__init__(daemon=True)
        self.server = make_server('127.0.0.1', PORT, app)
        self.context = app.app_context()
        self.context.push()

    def run(self):
        self.server.serve_forever()

    def shutdown(self):
        self.server.shutdown()
        self.context.pop()


def seed_data(app):
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    with app.app_context():
        db.create_all()

        admin = User(
            username='phil',
            email='phil@example.com',
            password_hash=bcrypt.generate_password_hash('TestPass1!').decode(),
            zip_code='20191',
        )
        rider = User(
            username='newrider',
            email='rider@example.com',
            password_hash=bcrypt.generate_password_hash('TestPass1!').decode(),
            zip_code='20191',
        )
        leader = User(
            username='rideleader',
            email='leader@example.com',
            password_hash=bcrypt.generate_password_hash('TestPass1!').decode(),
        )
        db.session.add_all([admin, rider, leader])
        db.session.flush()

        club = Club(
            slug='nova-paceline',
            name='NOVA Paceline',
            tagline='Road and gravel rides in Northern Virginia',
            description='',
            city='Reston',
            state='VA',
            zip_code='20191',
            lat=38.9586,
            lng=-77.3570,
            contact_email='rides@example.com',
            website='https://example.com',
            is_hidden=False,
            require_membership=False,
            join_approval='auto',
            membership_dues_required=True,
            membership_dues_mode='stripe_connect',
            membership_dues_url='https://buy.stripe.com/example',
            membership_dues_amount_cents=4500,
            membership_dues_currency='usd',
            membership_duration_months=12,
            stripe_account_id='acct_demo_connected',
            stripe_account_connected_at=datetime.now(timezone.utc),
            safety_guidelines='',
        )
        db.session.add(club)
        db.session.flush()

        db.session.add_all([
            ClubAdmin(user_id=admin.id, club_id=club.id, role='admin'),
            ClubMembership(user_id=admin.id, club_id=club.id, status='active'),
            ClubMembership(user_id=rider.id, club_id=club.id, status='pending_payment'),
            ClubMembership(user_id=leader.id, club_id=club.id, status='active'),
        ])

        today = date.today()
        next_saturday = today + timedelta(days=(5 - today.weekday()) % 7 or 7)
        next_sunday = next_saturday + timedelta(days=1)
        past_saturday = today - timedelta(days=(today.weekday() + 2) % 7 or 7)

        road_ride = Ride(
            club_id=club.id,
            title='Saturday Road Ride - B Group',
            date=next_saturday,
            time=time(8, 30),
            meeting_location='Reston Town Center Pavilion',
            distance_miles=42.0,
            elevation_feet=2100,
            pace_category='B',
            ride_type='road',
            leader_id=leader.id,
            ride_leader='rideleader',
            route_url='https://ridewithgps.com/routes/123456',
            description='No-drop regroup points. Bring two bottles and flat repair supplies.',
            max_riders=20,
            created_by=admin.id,
        )
        gravel_ride = Ride(
            club_id=club.id,
            title='Sunday Gravel Social',
            date=next_sunday,
            time=time(9, 0),
            meeting_location='Vienna Caboose',
            distance_miles=28.0,
            elevation_feet=1200,
            pace_category='C',
            ride_type='gravel',
            ride_leader='Phil',
            description='Mixed surface route with a coffee stop after the ride.',
            max_riders=16,
            created_by=admin.id,
        )
        completed_ride = Ride(
            club_id=club.id,
            title='Last Week Recovery Ride',
            date=past_saturday,
            time=time(8, 0),
            meeting_location='Lake Anne Plaza',
            distance_miles=24.0,
            elevation_feet=700,
            pace_category='D',
            ride_type='social',
            ride_leader='Phil',
            created_by=admin.id,
        )
        db.session.add_all([road_ride, gravel_ride, completed_ride])
        db.session.flush()

        db.session.add_all([
            RideSignup(ride_id=road_ride.id, user_id=admin.id),
            RideSignup(ride_id=road_ride.id, user_id=rider.id),
            RideSignup(ride_id=completed_ride.id, user_id=rider.id, attended=True),
        ])
        db.session.commit()
        return road_ride.id


def login(page, email='phil@example.com'):
    page.goto(f'{BASE_URL}/auth/login')
    page.fill('input[name="email"]', email)
    page.fill('input[name="password"]', 'TestPass1!')
    page.click('button[type="submit"], input[type="submit"]')
    page.wait_for_load_state('networkidle')


def shot(page, path, selector=None):
    page.wait_for_load_state('networkidle')
    if selector:
        page.locator(selector).first.wait_for(state='visible', timeout=5000)
    page.screenshot(path=os.path.join(OUTPUT_DIR, path), full_page=True)


def shot_element(page, path, selector):
    page.wait_for_load_state('networkidle')
    locator = page.locator(selector).first
    locator.wait_for(state='visible', timeout=5000)
    locator.screenshot(path=os.path.join(OUTPUT_DIR, path))


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    app = create_app(ScreenshotConfig)

    import app.routes.main as main_routes
    main_routes.get_weather_for_rides = lambda rides: {}

    road_ride_id = seed_data(app)
    server = ServerThread(app)
    server.start()
    time_module.sleep(0.5)

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context(viewport={'width': 1365, 'height': 900})
            page = context.new_page()
            login(page)

            page.goto(f'{BASE_URL}/clubs/create')
            shot(page, 'club-create.png', 'h1')

            page.goto(f'{BASE_URL}/admin/clubs/nova-paceline/settings')
            shot(page, 'club-settings.png', 'h1')
            shot_element(page, 'club-dues-settings.png', '#membership-section')

            page.goto(f'{BASE_URL}/admin/clubs/nova-paceline/team')
            shot(page, 'club-team.png', 'h1')

            page.goto(f'{BASE_URL}/admin/clubs/nova-paceline/rides')
            shot(page, 'club-rides-admin.png', 'h1')

            page.goto(f'{BASE_URL}/clubs/')
            shot(page, 'find-clubs.png', 'h1')

            page.goto(f'{BASE_URL}/discover/?range=two-weeks')
            shot(page, 'discover-rides.png', 'h1')

            page.goto(f'{BASE_URL}/clubs/nova-paceline/rides/{road_ride_id}')
            shot(page, 'ride-detail.png', 'h1')

            context.clear_cookies()
            login(page, email='rider@example.com')
            page.goto(f'{BASE_URL}/clubs/nova-paceline/')
            shot(page, 'club-dues-payment.png', 'button:has-text("Pay Club Dues")')

            context.close()
            browser.close()
    finally:
        server.shutdown()


if __name__ == '__main__':
    main()
