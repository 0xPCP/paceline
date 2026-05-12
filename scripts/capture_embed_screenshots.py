from datetime import date, time, timedelta
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright

from app import create_app
from app.extensions import db
from app.models import Club, Ride


class ScreenshotConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'embed-screenshot-secret'
    WTF_CSRF_ENABLED = False
    COOKIE_SECURE = False
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = '/tmp/paceline_embed_screenshots'
    SPACES_BUCKET = ''


def seed_embed_html():
    app = create_app(ScreenshotConfig)
    with app.app_context():
        db.create_all()
        club = Club(
            slug='embed-demo',
            name='Northern Virginia Cycling Club',
            tagline='Road and gravel rides around Northern Virginia',
            city='Reston',
            state='VA',
            zip_code='20191',
            is_hidden=False,
            theme_primary='#2d6a4f',
            theme_accent='#e76f51',
        )
        db.session.add(club)
        db.session.flush()
        rides = [
            ('Saturday B Ride to Leesburg', 2, time(8, 0), 'B', 'road', 48, 2400, 'Reston Town Center'),
            ('Sunday Gravel Social', 3, time(9, 15), 'C', 'gravel', 32, 1700, 'The Bike Lane, Reston'),
            ('Tuesday Worlds Practice Loop', 5, time(18, 0), 'A', 'training', 36, 2100, 'Hunter Woods Shopping Center'),
            ('Coffee Recovery Ride', 7, time(7, 30), 'D', 'road', 18, 650, 'Lake Anne Plaza'),
            ('Loudoun County Endurance Ride', 10, time(8, 0), 'B', 'road', 72, 3900, 'Ashburn Village Center'),
        ]
        for title, days, start, pace, ride_type, distance, elevation, location in rides:
            db.session.add(Ride(
                club_id=club.id,
                title=title,
                date=date.today() + timedelta(days=days),
                time=start,
                meeting_location=location,
                pace_category=pace,
                ride_type=ride_type,
                distance_miles=distance,
                elevation_feet=elevation,
            ))
        db.session.commit()
        return app.test_client().get('/clubs/embed-demo/embed').get_data(as_text=True)


def main():
    out_dir = Path('tests/screenshots/embed')
    out_dir.mkdir(parents=True, exist_ok=True)
    html = seed_embed_html()
    viewports = [
        ('desktop-full-page', 1440, 1000),
        ('tablet-iframe', 820, 760),
        ('mobile-iframe', 390, 760),
    ]
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for name, width, height in viewports:
            page = browser.new_page(viewport={'width': width, 'height': height})
            page.set_content(html, wait_until='domcontentloaded')
            page.screenshot(path=str(out_dir / f'{name}.png'), full_page=True)
            page.close()
        browser.close()
    print(f'Wrote {len(viewports)} screenshots to {out_dir}')


if __name__ == '__main__':
    main()
