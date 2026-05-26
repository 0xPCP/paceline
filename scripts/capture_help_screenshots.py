#!/usr/bin/env python3
"""Capture help-page screenshots for the new doc sections.

Run with:
    python scripts/capture_help_screenshots.py

Requires playwright:  pip install playwright && playwright install chromium
"""
from __future__ import annotations
import os
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

PROD_URL   = os.environ.get("PROD_URL", "https://paceline-2akis.ondigitalocean.app")
EMAIL      = os.environ.get("PROD_USER_EMAIL", "phil@pcp.dev")
PASSWORD   = os.environ.get("PROD_USER_PASSWORD", "")
OUT_DIR    = Path(__file__).parent.parent / "app" / "static" / "img" / "help"

VIEWPORT   = {"width": 1280, "height": 900}


def login(page):
    page.goto(f"{PROD_URL}/auth/login")
    page.wait_for_selector('input[name="email"]')
    page.fill('input[name="email"]', EMAIL)
    page.fill('input[name="password"]', PASSWORD)
    page.locator('[type="submit"]').click()
    page.wait_for_url(f"{PROD_URL}/", timeout=12_000)


def ss(page, name: str, locator=None, full_page=False):
    path = OUT_DIR / f"{name}.png"
    if locator:
        locator.screenshot(path=str(path))
    else:
        page.screenshot(path=str(path), full_page=full_page)
    print(f"  saved {path.name}")


def run():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport=VIEWPORT)
        page = ctx.new_page()
        login(page)
        print("Logged in.")

        # ── Auto-cancel settings section ─────────────────────────────────
        print("Auto-cancel settings...")
        page.goto(f"{PROD_URL}/admin/clubs/paceline-demo/settings")
        page.wait_for_load_state("networkidle")
        # Scroll to auto-cancel section and screenshot it
        section = page.locator("#cancel-thresholds").first
        section.scroll_into_view_if_needed()
        page.wait_for_timeout(300)
        # Screenshot the whole auto-cancel card (parent of the toggle + thresholds)
        cancel_card = page.locator("text=Weather Auto-Cancel").locator("..")
        ss(page, "club-auto-cancel", locator=cancel_card)

        # ── Contact page (rider view) ─────────────────────────────────────
        print("Contact page...")
        page.goto(f"{PROD_URL}/clubs/paceline-demo/contact")
        page.wait_for_load_state("networkidle")
        page.wait_for_selector('input[name="subject"], textarea[name="subject"]')
        # Screenshot the contact form card
        form_area = page.locator("form").first
        ss(page, "club-contact", locator=form_area)

        # ── Ride detail: ICS + GPX buttons ───────────────────────────────
        print("Ride detail ICS/GPX...")
        page.goto(f"{PROD_URL}/clubs/paceline-demo/rides/18")
        page.wait_for_load_state("networkidle")
        # Screenshot the ride tools area (ICS/GPX links + weather)
        page.wait_for_selector("a[href*='/ics']", timeout=8_000)
        ics_area = page.locator("a[href*='/ics']").locator("..").locator("..")
        ics_area.scroll_into_view_if_needed()
        page.wait_for_timeout(300)
        ss(page, "ride-ics-gpx", locator=ics_area)

        # ── Ride detail: comments section ────────────────────────────────
        print("Ride comments...")
        page.goto(f"{PROD_URL}/clubs/paceline-demo/rides/18")
        page.wait_for_load_state("networkidle")
        comments_section = page.locator("#comments, [id*='comment'], .comments-section, textarea[name='body']").first
        if comments_section.count() == 0:
            # Fall back: grab any textarea or discussion heading
            comments_section = page.locator("textarea").first
        comments_section.scroll_into_view_if_needed()
        page.wait_for_timeout(300)
        # Screenshot a larger parent container
        parent = comments_section.locator("..").locator("..")
        ss(page, "ride-comments", locator=parent)

        # ── Ride detail: media upload section ────────────────────────────
        print("Ride media upload...")
        page.goto(f"{PROD_URL}/clubs/paceline-demo/rides/18")
        page.wait_for_load_state("networkidle")
        # Try CSS selectors first, then text-based
        media_candidates = [
            page.locator("[id*='media']").first,
            page.locator(".media-upload").first,
            page.locator("input[type='file']").first,
            page.get_by_text("Share Photos", exact=False).first,
            page.get_by_text("Add Photo", exact=False).first,
            page.get_by_text("Upload", exact=False).first,
        ]
        found_media = False
        for candidate in media_candidates:
            if candidate.count() > 0:
                candidate.scroll_into_view_if_needed()
                page.wait_for_timeout(300)
                parent = candidate.locator("..").locator("..")
                ss(page, "ride-media", locator=parent)
                found_media = True
                break
        if not found_media:
            print("  (no media upload visible on ride 18 — may be future ride)")

        # ── Profile with friends button ───────────────────────────────────
        print("Profile friends...")
        page.goto(f"{PROD_URL}/users/wazup16")
        page.wait_for_load_state("networkidle")
        friend_candidates = [
            page.locator("form[action*='friend']").first,
            page.get_by_text("Add Friend", exact=False).first,
            page.get_by_role("button", name="Friends").first,
        ]
        found_friend = False
        for candidate in friend_candidates:
            if candidate.count() > 0:
                candidate.scroll_into_view_if_needed()
                page.wait_for_timeout(300)
                card = candidate.locator("..").locator("..")
                ss(page, "profile-friends", locator=card)
                found_friend = True
                break
        if not found_friend:
            ss(page, "profile-friends")

        # ── Profile distance units setting ───────────────────────────────
        print("Profile distance units setting...")
        page.goto(f"{PROD_URL}/auth/profile")
        page.wait_for_load_state("networkidle")
        units_select = page.locator('[name="distance_unit"]').first
        if units_select.count() > 0:
            units_select.scroll_into_view_if_needed()
            page.wait_for_timeout(300)
            units_card = units_select.locator("..").locator("..")
            ss(page, "profile-distance-units", locator=units_card)
        else:
            print("  (distance_unit field not found on profile page)")

        # ── Gear suggestions on a ride page ──────────────────────────────
        print("Gear suggestions...")
        page.goto(f"{PROD_URL}/clubs/paceline-demo/rides/18")
        page.wait_for_load_state("networkidle")
        gear_candidates = [
            page.locator("[id*='gear']").first,
            page.locator(".gear-suggestions").first,
            page.get_by_text("What to wear", exact=False).first,
            page.get_by_text("Gear suggestions", exact=False).first,
        ]
        found_gear = False
        for candidate in gear_candidates:
            if candidate.count() > 0:
                candidate.scroll_into_view_if_needed()
                page.wait_for_timeout(300)
                parent = candidate.locator("..").locator("..")
                ss(page, "ride-gear", locator=parent)
                found_gear = True
                break
        if not found_gear:
            print("  (no gear section visible on ride 18)")

        # ── Ride poll screenshots ────────────────────────────────────────
        print("Ride polls — admin rides page...")
        page.goto(f"{PROD_URL}/admin/clubs/paceline-demo/rides")
        page.wait_for_load_state("networkidle")
        ss(page, "poll-admin-rides", full_page=False)

        print("Ride polls — create form...")
        page.goto(f"{PROD_URL}/clubs/paceline-demo/polls/create")
        page.wait_for_load_state("networkidle")
        # Check the start-time and length toggles so options blocks are visible
        page.locator('#poll_start_time').check()
        page.locator('#poll_length').check()
        page.wait_for_timeout(300)
        # Fill in sample options so the form looks realistic
        page.locator('#list_start_time input').nth(0).fill('7:00 AM')
        page.locator('#list_start_time input').nth(1).fill('7:30 AM')
        page.locator('#list_length input').nth(0).fill('20 miles')
        page.locator('#list_length input').nth(1).fill('35 miles')
        page.locator('input[name="title"]').fill('Sunday Morning Ride — Vote Now!')
        page.locator('input[name="ride_date"]').fill('2026-06-08')
        page.locator('input[name="meeting_location"]').fill('Lake Fairfax Park')
        ss(page, "poll-create-form", full_page=True)

        print("Ride polls — creating a test poll for screenshots...")
        import datetime as _dt
        closes_at = (_dt.datetime.now() + _dt.timedelta(days=3)).strftime('%Y-%m-%dT%H:%M')
        page.goto(f"{PROD_URL}/clubs/paceline-demo/polls/create")
        page.wait_for_load_state("networkidle")
        page.locator('input[name="title"]').fill('Screenshot Test Poll — please ignore')
        page.locator('input[name="ride_date"]').fill('2026-06-15')
        page.locator('input[name="meeting_location"]').fill('Lake Fairfax Park')
        page.locator('#poll_start_time').check()
        page.locator('#poll_length').check()
        page.wait_for_timeout(200)
        page.locator('#list_start_time input').nth(0).fill('7:00 AM')
        page.locator('#list_start_time input').nth(1).fill('7:30 AM')
        page.locator('#list_length input').nth(0).fill('20 miles')
        page.locator('#list_length input').nth(1).fill('35 miles')
        page.locator('input[name="closes_at"]').fill(closes_at)
        page.locator('#fm_manual').check()
        page.locator('[data-testid="poll-submit"]').click()
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(500)
        # Should be redirected to the poll detail page
        if '/polls/' in page.url:
            print(f"  test poll created at {page.url}")
            ss(page, "poll-detail-open", full_page=False)

            # Try to get the finalize screenshot by closing the poll early
            # first note the poll ID from URL
            poll_url = page.url
            close_btn = page.locator('button:has-text("Close Poll Early")')
            if close_btn.count() > 0:
                page.on('dialog', lambda d: d.accept())
                close_btn.click()
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(500)
                # Should now be on poll detail (closed) with a Finalize button
                finalize_link = page.locator('a:has-text("Finalize Ride")')
                if finalize_link.count() > 0:
                    finalize_link.click()
                    page.wait_for_load_state("networkidle")
                    ss(page, "poll-finalize", full_page=False)
                    print(f"  finalize page captured")
                    # Go back and delete the test poll
                    page.goto(poll_url.replace('/polls/', '/polls/').split('?')[0])
                else:
                    print("  (finalize link not found after closing poll)")
            else:
                print("  (close poll button not found)")
        else:
            print(f"  poll creation may have failed — at {page.url}")

        # ── Ride share button ─────────────────────────────────────────────────
        print("Ride share button...")
        page.goto(f"{PROD_URL}/clubs/paceline-demo/rides/18")
        page.wait_for_load_state("networkidle")
        share_btn = page.locator('.ride-share-btn').first
        if share_btn.count() > 0:
            share_btn.scroll_into_view_if_needed()
            page.wait_for_timeout(300)
            # Screenshot the card/column containing the share button
            share_area = share_btn.locator("..").locator("..")
            ss(page, "ride-share-button", locator=share_area)
        else:
            # Fall back to a partial viewport screenshot centred around the button
            print("  (.ride-share-btn not found — screenshotting page)")
            ss(page, "ride-share-button", full_page=False)

        # ── Club admin messages view ──────────────────────────────────────────
        print("Club admin messages view...")
        # Send a test message from superadmin if the thread is empty
        page.goto(f"{PROD_URL}/admin/messages/club/paceline-demo")
        page.wait_for_load_state("networkidle")
        if '/admin/messages/club/' in page.url:
            existing = page.locator('.msg-bubble').count()
            if existing == 0:
                subj = page.locator('input[name="subject"]')
                body = page.locator('textarea[name="body"]')
                if subj.count() > 0 and body.count() > 0:
                    subj.fill('Welcome to Paceline!')
                    body.fill('Hi! Just checking in — let us know if you have any questions '
                              'about setting up your club or if there is anything the Paceline '
                              'team can help with.')
                    page.locator('button[type="submit"]').last.click()
                    page.wait_for_load_state("networkidle")
                    page.wait_for_timeout(400)

        # Screenshot the club-admin view (logged in as club admin equivalent)
        page.goto(f"{PROD_URL}/admin/clubs/paceline-demo/messages")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(400)
        ss(page, "club-messages", full_page=False)

        browser.close()
    print("Done.")


if __name__ == "__main__":
    sys.exit(run())
