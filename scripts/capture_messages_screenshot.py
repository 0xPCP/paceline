#!/usr/bin/env python3
"""Capture the club admin messages screenshot using a local Flask test server.

Run from the project root:
    python scripts/capture_messages_screenshot.py
"""
from __future__ import annotations
import os
import sys
import threading
import time
from pathlib import Path

# Point at a local SQLite DB so we don't touch prod
_DB_PATH = str(Path(__file__).parent.parent / "instance" / "screenshot_msgs.db")
os.environ.setdefault('DATABASE_URL', f'sqlite:///{_DB_PATH}')
os.environ.setdefault('SECRET_KEY', 'screenshot-capture-key-not-for-prod')
os.environ.setdefault('SESSION_COOKIE_SECURE', 'False')
os.environ.setdefault('WTF_CSRF_ENABLED', 'False')
os.environ.setdefault('TESTING', '1')
os.environ.setdefault('MAIL_SUPPRESS_SEND', '1')

sys.path.insert(0, str(Path(__file__).parent.parent))

from app import create_app
from app.extensions import db, bcrypt
from app.models import AdminMessage, Club, ClubAdmin, ClubMembership, User

OUT_DIR = Path(__file__).parent.parent / "app" / "static" / "img" / "help"
PORT = 5679


def _seed(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        pw = bcrypt.generate_password_hash("password123").decode()

        superadmin = User(username="superadmin", email="admin@example.com",
                          password_hash=pw, is_admin=True, is_active=True)
        club_admin = User(username="rbc_admin", email="admin@rbc.example.com",
                          password_hash=pw, is_admin=False, is_active=True)
        db.session.add_all([superadmin, club_admin])
        db.session.flush()

        club = Club(name="Reston Bike Club", slug="reston-bike-club",
                    city="Reston", state="VA", zip_code="20191",
                    is_hidden=False)
        db.session.add(club)
        db.session.flush()

        membership = ClubMembership(user_id=club_admin.id, club_id=club.id,
                                    status="active")
        admin_role = ClubAdmin(user_id=club_admin.id, club_id=club.id,
                               role="admin")
        db.session.add_all([membership, admin_role])
        db.session.flush()

        # A message from superadmin to the club
        msg = AdminMessage(
            club_id=club.id,
            sender_id=superadmin.id,
            is_from_superadmin=True,
            subject="Welcome to Paceline!",
            body=(
                "Hi Reston Bike Club admins,\n\n"
                "Just checking in — let us know if you have any questions "
                "about getting your club set up or if there is anything the "
                "Paceline team can help with.\n\n"
                "— The Paceline Team"
            ),
            parent_id=None,
            is_read=False,
        )
        db.session.add(msg)
        db.session.flush()

        # A reply from the club admin
        reply = AdminMessage(
            club_id=club.id,
            sender_id=club_admin.id,
            is_from_superadmin=False,
            body="Thanks for reaching out! We are all set for now. Really liking the platform so far.",
            parent_id=msg.id,
            is_read=True,
        )
        db.session.add(reply)

        # A broadcast notice
        broadcast = AdminMessage(
            club_id=None,
            sender_id=superadmin.id,
            is_from_superadmin=True,
            subject="New feature: Ride Polls",
            body="Club admins can now create ride polls to let members vote on ride details before committing. Find the + New Ride Poll button on Admin → Rides.",
            parent_id=None,
            is_read=False,
        )
        db.session.add(broadcast)

        db.session.commit()
        print(f"  seeded: club={club.id}, admin={club_admin.id}, msg={msg.id}")
        return club_admin.email


def run():
    app = create_app()
    app.config.update({
        "TESTING": False,
        "WTF_CSRF_ENABLED": False,
        "SERVER_NAME": f"localhost:{PORT}",
        "MAIL_SUPPRESS_SEND": True,
    })

    email = _seed(app)

    # Start Flask in a background thread
    server_thread = threading.Thread(
        target=lambda: app.run(port=PORT, use_reloader=False, threaded=True),
        daemon=True,
    )
    server_thread.start()
    time.sleep(1.5)  # let Flask bind

    from playwright.sync_api import sync_playwright
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page()

        # Log in as club admin
        page.goto(f"http://localhost:{PORT}/auth/login")
        page.wait_for_selector('input[name="email"]', timeout=8000)
        page.fill('input[name="email"]', email)
        page.fill('input[name="password"]', "password123")
        page.locator('[type="submit"]').click()
        page.wait_for_load_state("networkidle")
        print(f"  logged in as {email}, now at {page.url}")

        page.goto(f"http://localhost:{PORT}/admin/clubs/reston-bike-club/messages")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(400)
        print(f"  messages page: {page.url}")

        bubbles = page.locator(".msg-bubble").count()
        print(f"  msg bubbles: {bubbles}")

        path = OUT_DIR / "club-messages.png"
        page.screenshot(path=str(path))
        print(f"  saved {path.name}")
        browser.close()

    print("Done.")


if __name__ == "__main__":
    run()
