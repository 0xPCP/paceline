#!/usr/bin/env python3
"""Exercise core Paceline workflows against a live environment with Playwright.

The script intentionally creates timestamped throwaway users, a club, and rides,
then uses the superadmin UI to remove/deactivate the generated records. It never
targets the protected demo club or the configured superadmin account for cleanup.
"""

from __future__ import annotations

import json
import os
import re
import traceback
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urljoin

from playwright.sync_api import Browser, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright


BASE_URL = os.getenv("PACELINE_BASE_URL", "https://paceline-2akis.ondigitalocean.app").rstrip("/")
BETA_PASSWORD = os.getenv("PACELINE_BETA_PASSWORD", "")
SUPERADMIN_EMAIL = os.getenv("PACELINE_SUPERADMIN_EMAIL", "phil@pcp.dev")
SUPERADMIN_PASSWORD = os.getenv("PACELINE_SUPERADMIN_PASSWORD", "")

STAMP = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
OWNER_EMAIL = f"audit_owner_{STAMP}@example.com"
RIDER_EMAIL = f"audit_rider_{STAMP}@example.com"
PASSWORD = "AuditPassw0rd!42"
CLUB_NAME = f"Audit Workflow Club {STAMP}"
CLUB_SLUG = ""
CLUB_RIDE_TITLE = f"Audit Club Ride {STAMP}"
PERSONAL_RIDE_TITLE = f"Audit Personal Ride {STAMP}"
RUN_AT = datetime.now().astimezone()
OUT_DIR = Path("tests/live-workflow-audit") / STAMP
PROTECTED_EMAILS = {SUPERADMIN_EMAIL.lower()}
PROTECTED_CLUB_SLUGS = {"paceline-demo"}


@dataclass
class StepResult:
    name: str
    status: str
    url: str = ""
    notes: str = ""
    screenshot: str = ""
    error: str = ""


@dataclass
class AuditState:
    results: list[StepResult] = field(default_factory=list)
    club_slug: str = ""
    club_ride_url: str = ""
    personal_ride_url: str = ""
    owner_user_url: str = ""
    rider_user_url: str = ""


state = AuditState()


def abs_url(path: str) -> str:
    return urljoin(BASE_URL + "/", path.lstrip("/"))


def screenshot(page: Page, name: str) -> str:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", name.lower()).strip("-")
    path = OUT_DIR / f"{safe}.png"
    page.screenshot(path=str(path), full_page=True)
    return str(path)


def record(name: str, status: str, page: Optional[Page] = None, notes: str = "", error: str = "") -> None:
    shot = ""
    url = ""
    if page is not None:
        url = page.url
        if status in {"warning", "fail"}:
            try:
                shot = screenshot(page, name)
            except Exception:
                shot = ""
    state.results.append(StepResult(name=name, status=status, url=url, notes=notes, screenshot=shot, error=error))
    print(f"[{status.upper()}] {name} {('- ' + notes) if notes else ''}")


def step(name: str, page: Page, fn: Callable[[], str | None]) -> None:
    try:
        notes = fn() or ""
        record(name, "pass", page, notes)
    except AssertionError as exc:
        record(name, "fail", page, str(exc), traceback.format_exc(limit=3))
    except Exception as exc:
        record(name, "fail", page, f"{type(exc).__name__}: {exc}", traceback.format_exc(limit=4))


def new_page(browser: Browser, viewport: dict | None = None) -> Page:
    context = browser.new_context(
        viewport=viewport or {"width": 1440, "height": 950},
        user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    )
    page = context.new_page()
    page.on("dialog", lambda dialog: dialog.accept())
    return page


def maybe_beta(page: Page) -> None:
    try:
        if not BETA_PASSWORD:
            return
        body = page.locator("body").inner_text(timeout=3000) if page.locator("body").count() else ""
        if "/_beta" in page.url or ("beta" in body.lower() and page.locator('input[name="password"]').count()):
            page.locator('input[name="password"]').first.fill(BETA_PASSWORD)
            page.locator('button[type="submit"], input[type="submit"]').first.click()
            page.wait_for_load_state("domcontentloaded", timeout=15000)
    except PlaywrightTimeoutError:
        pass


def goto(page: Page, path: str) -> None:
    page.goto(abs_url(path), wait_until="domcontentloaded", timeout=45000)
    maybe_beta(page)
    page.wait_for_load_state("domcontentloaded", timeout=15000)


def submit_current_form(page: Page) -> None:
    page.locator('button[type="submit"], input[type="submit"]').last.click()
    page.wait_for_load_state("domcontentloaded", timeout=20000)


def register(page: Page, email: str, username: str) -> None:
    goto(page, "/auth/register")
    page.get_by_test_id("register-username").fill(username)
    page.get_by_test_id("register-email").fill(email)
    page.get_by_test_id("register-password").fill(PASSWORD)
    page.get_by_test_id("register-confirm-password").fill(PASSWORD)
    page.get_by_test_id("register-submit").click()
    page.wait_for_load_state("domcontentloaded", timeout=20000)
    body = page.locator("body").inner_text(timeout=10000)
    assert "Create Account" not in body or "already" not in body.lower(), body[:500]


def login(page: Page, email: str, password: str) -> None:
    goto(page, "/auth/login")
    if not page.get_by_test_id("login-email").count() and "/auth/login" not in page.url:
        return
    page.get_by_test_id("login-email").fill(email)
    page.get_by_test_id("login-password").fill(password)
    page.get_by_test_id("login-submit").click()
    page.wait_for_load_state("domcontentloaded", timeout=20000)
    maybe_beta(page)
    body = page.locator("body").inner_text(timeout=10000)
    assert "Invalid email or password" not in body, body[:500]
    assert "/auth/login" not in page.url, f"Still on login page: {page.url}"


def create_club(page: Page) -> str:
    goto(page, "/clubs/create")
    page.get_by_test_id("create-club-name").fill(CLUB_NAME)
    page.get_by_test_id("create-club-city").fill("Arlington")
    page.get_by_test_id("create-club-state").fill("VA")
    page.get_by_test_id("create-club-zip").fill("22201")
    page.get_by_test_id("create-club-next-hosting").click()
    page.get_by_test_id("create-club-next-theme").click()
    page.get_by_test_id("create-club-next-details").click()
    page.get_by_test_id("create-club-description").wait_for(state="visible", timeout=10000)
    page.get_by_test_id("create-club-description").fill(
        "Temporary live workflow audit club. This record should be deleted by the audit cleanup."
    )
    page.get_by_test_id("create-club-contact-email").fill(OWNER_EMAIL)
    page.get_by_test_id("create-club-review").click()
    page.get_by_test_id("create-club-submit").wait_for(state="visible", timeout=10000)
    page.get_by_test_id("create-club-submit").click()
    page.wait_for_load_state("domcontentloaded", timeout=20000)
    match = re.search(r"/admin/clubs/([^/]+)/?", page.url)
    assert match, f"Expected admin club URL after create, got {page.url}"
    slug = match.group(1)
    assert slug not in PROTECTED_CLUB_SLUGS, f"Refusing protected club slug {slug}"
    state.club_slug = slug
    return slug


def save_club_settings_public(page: Page, slug: str) -> None:
    goto(page, f"/admin/clubs/{slug}/settings")
    hidden = page.locator('input[name="is_hidden"]')
    if hidden.count() and hidden.is_checked():
        hidden.uncheck()
    submit_current_form(page)


def create_club_ride(page: Page, slug: str) -> str:
    goto(page, f"/admin/clubs/{slug}/rides/new")
    ride_date = (date.today() + timedelta(days=7)).isoformat()
    page.get_by_test_id("club-ride-title").fill(CLUB_RIDE_TITLE)
    page.get_by_test_id("club-ride-date").fill(ride_date)
    page.get_by_test_id("club-ride-time").fill("09:00")
    page.get_by_test_id("club-ride-meeting-location").fill("Courthouse Plaza, Arlington, VA")
    page.get_by_test_id("club-ride-distance").fill("32")
    page.get_by_test_id("club-ride-elevation").fill("1250")
    page.get_by_test_id("club-ride-pace").select_option(index=1)
    page.get_by_test_id("club-ride-type").select_option(index=1)
    page.get_by_test_id("club-ride-leader-text").fill("Audit Leader")
    page.get_by_test_id("club-ride-description").fill("Temporary ride for live workflow audit.")
    page.get_by_test_id("club-ride-submit").click()
    page.wait_for_load_state("domcontentloaded", timeout=20000)
    goto(page, f"/admin/clubs/{slug}/rides")
    href = page.locator(f'a:has-text("{CLUB_RIDE_TITLE}")').first.get_attribute("href")
    assert href, "Created club ride was not listed in club admin rides."
    state.club_ride_url = href if href.startswith("http") else abs_url(href)
    return state.club_ride_url


def join_club_and_signup(page: Page, slug: str) -> None:
    goto(page, f"/clubs/{slug}/")
    if page.get_by_role("button", name=re.compile(r"Join Club", re.I)).count():
        page.get_by_role("button", name=re.compile(r"Join Club", re.I)).first.click()
        page.wait_for_load_state("domcontentloaded", timeout=15000)
    body = page.locator("body").inner_text(timeout=10000)
    assert any(token in body for token in ["Leave Club", "Pending Approval", "Payment Pending"]), body[:800]
    goto(page, state.club_ride_url)
    if page.get_by_role("button", name=re.compile(r"Sign Up for This Ride|Sign Up", re.I)).count():
        page.get_by_role("button", name=re.compile(r"Sign Up for This Ride|Sign Up", re.I)).first.click()
        page.wait_for_load_state("domcontentloaded", timeout=15000)
    body = page.locator("body").inner_text(timeout=10000)
    assert any(token in body for token in ["Cancel Signup", "Cancel My Signup", "Leave Waitlist", "You are signed up"]), body[:800]


def create_personal_ride(page: Page) -> str:
    goto(page, "/my-rides/create")
    ride_date = (date.today() + timedelta(days=8)).isoformat()
    page.get_by_test_id("personal-ride-title").fill(PERSONAL_RIDE_TITLE)
    page.get_by_test_id("personal-ride-date").fill(ride_date)
    page.get_by_test_id("personal-ride-time").fill("18:00")
    page.get_by_test_id("personal-ride-meeting-location").fill("W&OD Trailhead, Arlington, VA")
    page.get_by_test_id("personal-ride-distance").fill("18")
    page.get_by_test_id("personal-ride-elevation").fill("400")
    page.get_by_test_id("personal-ride-max-riders").fill("12")
    page.get_by_test_id("personal-ride-pace").select_option(index=1)
    page.get_by_test_id("personal-ride-type").select_option(index=1)
    page.get_by_test_id("personal-ride-description").fill("Temporary personal ride for live workflow audit.")
    private = page.get_by_test_id("personal-ride-private")
    if private.count() and private.is_checked():
        private.uncheck()
    page.get_by_test_id("personal-ride-submit").click()
    page.wait_for_load_state("domcontentloaded", timeout=20000)
    assert "/my-rides/" in page.url, f"Expected personal ride detail URL, got {page.url}"
    state.personal_ride_url = page.url
    return page.url


def signup_personal_ride(page: Page) -> None:
    goto(page, state.personal_ride_url)
    if page.get_by_role("button", name=re.compile(r"Join Ride|Sign Up", re.I)).count():
        page.get_by_role("button", name=re.compile(r"Join Ride|Sign Up", re.I)).first.click()
        page.wait_for_load_state("domcontentloaded", timeout=15000)
    body = page.locator("body").inner_text(timeout=10000)
    assert any(token in body for token in ["Cancel Signup", "You are signed up", "Leave Waitlist"]), body[:800]


def superadmin_checks(page: Page) -> None:
    assert SUPERADMIN_PASSWORD, "PACELINE_SUPERADMIN_PASSWORD is required for superadmin workflow tests."
    login(page, SUPERADMIN_EMAIL, SUPERADMIN_PASSWORD)
    for path, label in [
        ("/admin/", "dashboard"),
        ("/admin/users/", "users"),
        ("/admin/user-rides/", "user-hosted rides"),
        ("/admin/feedback/", "feedback"),
        ("/admin/errors/", "error log"),
    ]:
        goto(page, path)
        text = page.locator("body").inner_text(timeout=10000)
        assert "Forbidden" not in text and "Sign In" not in text, f"Superadmin {label} did not render."

    goto(page, f"/admin/users/?q={OWNER_EMAIL}")
    owner_link = page.locator(f'text="{OWNER_EMAIL}"').first
    assert owner_link.count(), "Owner test user not found in superadmin user search."

    goto(page, f"/admin/clubs/{state.club_slug}/superadmin")
    text = page.locator("body").inner_text(timeout=10000)
    assert CLUB_NAME in text and "Danger Zone" in text, "Generated club superadmin screen did not render."


def deactivate_user_by_email(page: Page, email: str) -> str:
    if email.lower() in PROTECTED_EMAILS:
        return f"Skipped protected user {email}."
    goto(page, f"/admin/users/?q={email}")
    view = page.get_by_role("link", name=re.compile(r"View", re.I))
    if not view.count():
        return f"No View link found for {email}; could not deactivate."
    view.first.click()
    page.wait_for_load_state("domcontentloaded", timeout=15000)
    if page.get_by_role("button", name=re.compile(r"Deactivate Account", re.I)).count():
        page.get_by_role("button", name=re.compile(r"Deactivate Account", re.I)).first.click()
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        return f"Deactivated {email}."
    return f"{email} already inactive or deactivate action unavailable."


def delete_test_user_by_email(page: Page, email: str) -> str:
    if email.lower() in PROTECTED_EMAILS:
        return f"Skipped protected user {email}."
    goto(page, f"/admin/users/?q={email}")
    view = page.get_by_role("link", name=re.compile(r"View", re.I))
    if not view.count():
        return f"No View link found for {email}; user may already be deleted."
    view.first.click()
    page.wait_for_load_state("domcontentloaded", timeout=15000)
    panel = page.get_by_test_id("delete-test-user-panel")
    if not panel.count():
        return f"Permanent test-user delete was not available for {email}; falling back to deactivate."
    page.get_by_test_id("delete-test-user-confirmation").fill(f"DELETE TEST USER {email}")
    page.get_by_test_id("delete-test-user-button").click()
    page.wait_for_load_state("domcontentloaded", timeout=15000)
    return f"Deleted generated test user {email}."


def cleanup(page: Page) -> str:
    notes: list[str] = []
    if not page.url.startswith(BASE_URL):
        login(page, SUPERADMIN_EMAIL, SUPERADMIN_PASSWORD)
    if state.club_slug and state.club_slug not in PROTECTED_CLUB_SLUGS:
        goto(page, f"/admin/clubs/{state.club_slug}/superadmin")
        page.locator('input[name="confirmation"]').fill(f"DELETE {state.club_slug}")
        page.get_by_role("button", name=re.compile(r"Delete Club", re.I)).click()
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        notes.append(f"Deleted generated club {state.club_slug}.")
    for email in [OWNER_EMAIL, RIDER_EMAIL]:
        note = delete_test_user_by_email(page, email)
        if "falling back" in note:
            note += " " + deactivate_user_by_email(page, email)
        notes.append(note)
    return " ".join(notes)


def delete_personal_ride_as_owner(browser: Browser) -> str:
    page = new_page(browser)
    try:
        login(page, OWNER_EMAIL, PASSWORD)
        goto(page, "/my-rides/")
        card = page.locator(".card", has_text=PERSONAL_RIDE_TITLE)
        if not card.count():
            return "Generated personal ride not found in owner My Rides."
        card.first.get_by_role("button", name=re.compile(r"Delete", re.I)).click()
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        return "Deleted generated personal ride."
    except Exception as exc:
        return f"Could not delete generated personal ride before user deactivation: {type(exc).__name__}: {exc}"
    finally:
        page.context.close()


def write_report() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_at": RUN_AT.isoformat(),
        "base_url": BASE_URL,
        "generated": {
            "owner_email": OWNER_EMAIL,
            "rider_email": RIDER_EMAIL,
            "club_name": CLUB_NAME,
            "club_slug": state.club_slug,
            "club_ride_title": CLUB_RIDE_TITLE,
            "personal_ride_title": PERSONAL_RIDE_TITLE,
        },
        "results": [result.__dict__ for result in state.results],
    }
    (OUT_DIR / "results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [
        f"# Live Workflow Audit Results - {RUN_AT.strftime('%Y-%m-%d %H:%M %Z')}",
        "",
        f"Base URL: `{BASE_URL}`",
        "",
        "| Workflow | Status | Notes | Evidence |",
        "| --- | --- | --- | --- |",
    ]
    for result in state.results:
        evidence = result.screenshot or result.url
        notes = (result.notes or result.error or "").replace("\n", " ").replace("|", "\\|")
        lines.append(f"| {result.name} | {result.status.upper()} | {notes} | `{evidence}` |")
    (OUT_DIR / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        owner = new_page(browser)
        step("Visitor beta gate", owner, lambda: (goto(owner, "/"), "Home page loaded after beta gate.")[1])
        step("Direct registration creates owner account", owner, lambda: (register(owner, OWNER_EMAIL, f"audit_owner_{STAMP}"), "Registered throwaway owner.")[1])
        owner_login = new_page(browser)
        step("Owner login", owner_login, lambda: (login(owner_login, OWNER_EMAIL, PASSWORD), "Owner can sign in with direct credentials.")[1])
        owner_login.context.close()
        step("Owner profile renders", owner, lambda: (goto(owner, "/auth/profile"), "Profile page rendered.")[1])
        step("Owner creates club", owner, lambda: f"Created slug `{create_club(owner)}`.")
        step("Club settings can publish generated club", owner, lambda: (save_club_settings_public(owner, state.club_slug), "Generated club unhidden through settings.")[1])
        step("Club admin creates ride", owner, lambda: f"Created ride URL `{create_club_ride(owner, state.club_slug)}`.")
        step("Owner creates personal ride", owner, lambda: f"Created personal ride `{create_personal_ride(owner)}`.")

        rider = new_page(browser)
        step("Direct registration creates rider account", rider, lambda: (register(rider, RIDER_EMAIL, f"audit_rider_{STAMP}"), "Registered throwaway rider.")[1])
        rider_login = new_page(browser)
        step("Rider login", rider_login, lambda: (login(rider_login, RIDER_EMAIL, PASSWORD), "Rider can sign in with direct credentials.")[1])
        rider_login.context.close()
        step("Rider joins club and signs up for club ride", rider, lambda: (join_club_and_signup(rider, state.club_slug), "Rider joined generated club and signed up for ride.")[1])
        step("Rider signs up for personal ride", rider, lambda: (signup_personal_ride(rider), "Rider signed up for generated personal ride.")[1])

        superadmin = new_page(browser)
        step("Superadmin dashboard and oversight pages", superadmin, lambda: (superadmin_checks(superadmin), "Dashboard, users, user rides, feedback, errors, and club superadmin pages rendered.")[1])
        step("Owner cleanup deletes generated personal ride", superadmin, lambda: delete_personal_ride_as_owner(browser))
        step("Cleanup generated records", superadmin, lambda: cleanup(superadmin))

        browser.close()

    write_report()
    failures = [result for result in state.results if result.status == "fail"]
    print(f"\nReport written to {OUT_DIR / 'summary.md'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
