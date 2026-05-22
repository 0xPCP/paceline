#!/usr/bin/env python3
"""Capture help-page screenshots for the new doc sections.

Run with:
    python scripts/capture_help_screenshots.py

Requires playwright:  pip install playwright && playwright install chromium
"""
from __future__ import annotations
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

PROD_URL   = "https://paceline-2akis.ondigitalocean.app"
EMAIL      = "phil@pcp.dev"
PASSWORD   = "REDACTED"
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

        browser.close()
    print("Done.")


if __name__ == "__main__":
    sys.exit(run())
