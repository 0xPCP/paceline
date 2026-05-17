"""
Renders every email template with realistic fake data and screenshots each one
using a headless Chromium browser via Playwright.

Usage:
    python tests/screenshot_emails.py

Output: tests/screenshots/email/*.png
"""
import os
import sys
from datetime import date, time, timedelta
from pathlib import Path
from types import SimpleNamespace

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT_DIR = ROOT / 'tests' / 'screenshots' / 'email'
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Flask app ──────────────────────────────────────────────────────────────────
os.environ.setdefault('FLASK_ENV', 'testing')
from app import create_app

class _TestCfg:
    TESTING = True
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'screenshot-test-key'
    MAIL_SUPPRESS_SEND = True
    SERVER_NAME = 'localhost'
    PREFERRED_URL_SCHEME = 'http'
    SPACES_PUBLIC_BASE_URL = ''

app = create_app(_TestCfg)

# ── Fake data factory ──────────────────────────────────────────────────────────

def _club(slug='rbc', name='Reston Bike Club'):
    return SimpleNamespace(
        id=1, slug=slug, name=name,
        contact_email='admin@restonbikeclub.org',
    )

def _user(username='johndoe', email='john@example.com'):
    return SimpleNamespace(id=1, username=username, email=email)

def _ride(club=None, offset_days=3):
    club = club or _club()
    ride_date = date.today() + timedelta(days=offset_days)
    return SimpleNamespace(
        id=42,
        title='Saturday Morning B-Ride',
        club=club,
        club_id=club.id,
        date=ride_date,
        time=time(7, 30),
        meeting_location='Lake Anne Plaza, Reston VA',
        distance_miles=35.0,
        elevation_feet=1200,
        pace_category='B',
        pace_label='B — Moderate (18–22 mph)',
        ride_leader='Jane Smith',
        signup_count=12,
        route_url='https://ridewithgps.com/routes/12345',
        cancel_reason='High wind advisory — gusts up to 40 mph forecast.',
        description='Rolling terrain through the Reston National area. Regrouping at the top of Glade and Fox Mill.',
        is_cancelled=False,
    )

def _post(club=None, author=None):
    club = club or _club()
    author = author or _user(username='bikeadmin')
    return SimpleNamespace(
        id=7,
        club=club,
        author=author,
        body='Reminder: the Saturday ride has been moved to 8am due to the holiday weekend. See you all there!',
    )

def _invite(club=None, creator=None):
    club = club or _club()
    creator = creator or _user(username='clubadmin')
    return SimpleNamespace(
        club=club,
        email='newrider@example.com',
        creator=creator,
        token='abc123token',
    )

def _transfer(club=None, from_user=None, to_user=None):
    club = club or _club()
    return SimpleNamespace(
        club=club,
        from_user=from_user or _user(username='oldowner', email='old@example.com'),
        to_user=to_user or _user(username='newowner', email='new@example.com'),
    )

def _feedback():
    return SimpleNamespace(
        id=3,
        name='Alex Rider',
        email='alex@example.com',
        source='ride-detail',
        message='Love the weather widget on the ride detail page. Would be great to show wind direction too!',
    )

def _signup(ride=None):
    ride = ride or _ride()
    return SimpleNamespace(ride=ride, user=_user())

# ── Template renders ───────────────────────────────────────────────────────────

def render(template_name, **ctx):
    from flask import render_template
    return render_template(f'email/{template_name}', **ctx)

def screenshots():
    club  = _club()
    ride  = _ride(club)
    post  = _post(club)
    reply_author = _user(username='speedracer', email='speed@example.com')

    templates = [
        ('reminder.html',     'reminder',     lambda: render('reminder.html', ride=ride)),
        ('cancellation.html', 'cancellation', lambda: render('cancellation.html', ride=ride)),
        ('new_ride.html',     'new_ride',     lambda: render('new_ride.html', ride=ride)),
        ('weekly_digest.html','weekly_digest', lambda: render('weekly_digest.html', club=club, rides=[
            _ride(club, offset_days=1),
            _ride(club, offset_days=3).__class__(**{**_ride(club, offset_days=3).__dict__,
                'title':'Sunday Social Spin','pace_label':'C — Casual (14–18 mph)','pace_category':'C','distance_miles':22.0}),
            _ride(club, offset_days=5).__class__(**{**_ride(club, offset_days=5).__dict__,
                'title':'Tuesday Night Worlds','pace_label':'A — Fast (22+ mph)','pace_category':'A','distance_miles':28.0}),
        ])),
        ('password_reset.html','password_reset', lambda: render('password_reset.html',
            user=_user(), reset_url='https://paceline.club/auth/reset/abc123')),
        ('membership_approved.html','membership_approved', lambda: render('membership_approved.html', club=club)),
        ('membership_rejected.html','membership_rejected', lambda: render('membership_rejected.html', club=club)),
        ('waitlist_promoted.html','waitlist_promoted', lambda: render('waitlist_promoted.html', ride=ride)),
        ('invite.html',       'invite',        lambda: render('invite.html',
            invite=_invite(club), claim_url='https://paceline.club/clubs/rbc/invite/abc123')),
        ('import_welcome.html','import_welcome', lambda: render('import_welcome.html',
            invite=_invite(club), setup_url='https://paceline.club/auth/setup/abc123')),
        ('import_invite.html','import_invite', lambda: render('import_invite.html',
            invite=_invite(club), claim_url='https://paceline.club/clubs/rbc/invite/abc123')),
        ('club_news.html',    'club_news',     lambda: render('club_news.html',
            post=SimpleNamespace(club=club, title='Season Kickoff Ride Recap',
                body='What a fantastic turnout last Saturday! Over 40 riders joined us for the season kickoff. '
                     'Thanks to everyone who showed up and to our sweep riders for keeping the group safe. '
                     'See you out there next weekend!'))),
        ('board_notification.html','board_notification', lambda: render('board_notification.html',
            post=post, user=_user())),
        ('mention_notification.html','mention_notification', lambda: render('mention_notification.html',
            user=_user(), author=reply_author, post=post,
            body='@johndoe — you should definitely come to the Tuesday night ride, it\'s a blast!')),
        ('reply_notification.html','reply_notification', lambda: render('reply_notification.html',
            post=post, reply=SimpleNamespace(author=reply_author,
                body='I\'ll be there! Meeting at Lake Anne at 6:30pm, right?'))),
        ('club_ownership_transfer.html','ownership_transfer', lambda: render('club_ownership_transfer.html',
            transfer=_transfer(), accept_url='https://paceline.club/admin/transfer/accept/abc123')),
        ('feedback_notification.html','feedback_notification', lambda: render('feedback_notification.html',
            feedback=_feedback())),
    ]
    return templates


def main():
    html_dir = OUT_DIR / '_html'
    html_dir.mkdir(exist_ok=True)

    with app.test_request_context('/'):
        app.config['SERVER_NAME'] = 'localhost'
        rendered = []
        for filename, slug, fn in screenshots():
            try:
                html = fn()
                html_path = html_dir / f'{slug}.html'
                html_path.write_text(html, encoding='utf-8')
                rendered.append((slug, html_path))
                print(f'  ✓ rendered {slug}')
            except Exception as exc:
                print(f'  ✗ {slug}: {exc}')
        app.config.pop('SERVER_NAME', None)

    # ── Playwright screenshots ─────────────────────────────────────────────────
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('\nPlaywright not installed — HTML files saved, no screenshots taken.')
        print('Install with: pip install playwright && playwright install chromium')
        return

    print(f'\nScreenshotting {len(rendered)} emails...')
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 700, 'height': 900})
        for slug, html_path in rendered:
            try:
                page.goto(f'file://{html_path}', wait_until='networkidle')
                # Measure full-content height for a tall screenshot
                height = page.evaluate('document.body.scrollHeight')
                page.set_viewport_size({'width': 700, 'height': max(height + 40, 400)})
                out = OUT_DIR / f'{slug}.png'
                page.screenshot(path=str(out), full_page=True)
                print(f'  ✓ {out.name}')
            except Exception as exc:
                print(f'  ✗ screenshot {slug}: {exc}')
        browser.close()

    print(f'\nDone. Screenshots in {OUT_DIR}')


if __name__ == '__main__':
    main()
