#!/usr/bin/env python3
"""Clean up specific live audit artifacts through the UI."""

from __future__ import annotations

import argparse
import os
import re
from urllib.parse import urljoin

from playwright.sync_api import Page, sync_playwright


BASE_URL = os.getenv("PACELINE_BASE_URL", "https://paceline-2akis.ondigitalocean.app").rstrip("/")
BETA_PASSWORD = os.getenv("PACELINE_BETA_PASSWORD", "")
SUPERADMIN_EMAIL = os.getenv("PACELINE_SUPERADMIN_EMAIL", "phil@pcp.dev")
SUPERADMIN_PASSWORD = os.getenv("PACELINE_SUPERADMIN_PASSWORD", "")


def abs_url(path: str) -> str:
    return urljoin(BASE_URL + "/", path.lstrip("/"))


def maybe_beta(page: Page) -> None:
    if not BETA_PASSWORD:
        return
    body = page.locator("body").inner_text(timeout=3000) if page.locator("body").count() else ""
    if "/_beta" in page.url or ("beta" in body.lower() and page.locator('input[name="password"]').count()):
        page.locator('input[name="password"]').first.fill(BETA_PASSWORD)
        page.locator('button[type="submit"], input[type="submit"]').first.click()
        page.wait_for_load_state("domcontentloaded", timeout=15000)


def goto(page: Page, path: str) -> None:
    page.goto(abs_url(path), wait_until="domcontentloaded", timeout=45000)
    maybe_beta(page)


def login(page: Page, email: str, password: str) -> None:
    goto(page, "/auth/login")
    page.locator('input[name="email"]').fill(email)
    page.locator('input[name="password"]').fill(password)
    page.locator('button[type="submit"], input[type="submit"]').last.click()
    page.wait_for_load_state("domcontentloaded", timeout=15000)


def toggle_user_active(page: Page, email: str, desired_active: bool) -> str:
    goto(page, f"/admin/users/?q={email}")
    view = page.get_by_role("link", name=re.compile(r"View", re.I))
    if not view.count():
        return f"No user detail link found for {email}."
    view.first.click()
    page.wait_for_load_state("domcontentloaded", timeout=15000)
    action = "Reactivate Account" if desired_active else "Deactivate Account"
    button = page.get_by_role("button", name=re.compile(action, re.I))
    if button.count():
        button.first.click()
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        return f"{action} submitted for {email}."
    return f"{email} already in desired active state."


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--ride-title", required=True)
    args = parser.parse_args()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        superadmin = browser.new_page()
        superadmin.on("dialog", lambda dialog: dialog.accept())
        login(superadmin, SUPERADMIN_EMAIL, SUPERADMIN_PASSWORD)
        print(toggle_user_active(superadmin, args.email, True))

        owner = browser.new_page()
        owner.on("dialog", lambda dialog: dialog.accept())
        login(owner, args.email, args.password)
        goto(owner, "/my-rides/")
        card = owner.locator(".card", has_text=args.ride_title)
        if card.count():
            card.first.get_by_role("button", name=re.compile(r"Delete", re.I)).click()
            owner.wait_for_load_state("domcontentloaded", timeout=15000)
            print(f"Deleted ride {args.ride_title}.")
        else:
            print(f"Ride {args.ride_title} not found.")

        print(toggle_user_active(superadmin, args.email, False))
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
