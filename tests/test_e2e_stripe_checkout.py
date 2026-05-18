"""
End-to-end Stripe Connect dues checkout test — runs against https://paceline.club.

Prerequisites
-------------
  pip install pytest-playwright
  playwright install chromium

Setup
-----
  The paceline-demo club must have:
    - stripe_account_connected_at set (Stripe onboarding complete)
    - membership_dues_mode = 'stripe_connect'
    - membership_dues_amount_cents > 0
    - require_membership = True
    - membership_dues_required = True

  Configure via admin UI or directly:
    UPDATE clubs SET require_membership=TRUE, membership_dues_required=TRUE,
      membership_dues_mode='stripe_connect', membership_dues_amount_cents=1000,
      membership_duration_months=12 WHERE slug='paceline-demo';

Run
---
  pytest tests/test_e2e_stripe_checkout.py -v -s

Note on Cloudflare
------------------
  https://paceline.club is protected by Cloudflare's bot management and will
  block headless browsers. The test therefore runs against the DigitalOcean
  direct URL which bypasses Cloudflare:
    https://paceline-2akis.ondigitalocean.app

  To run against paceline.club, disable CF Bot Management for your IP first,
  or use playwright-stealth with a real Chrome channel.

Stripe test card
----------------
  4242 4242 4242 4242  exp: 12/29  CVC: 123

Cleanup
-------
  Test users have usernames matching e2e_checkout_* — eligible for admin
  "Delete test user" action.
"""

import os
import time
import pytest
from playwright.sync_api import Page, expect

# ── Config ────────────────────────────────────────────────────────────────────

# Use the DigitalOcean direct URL to bypass Cloudflare bot protection.
# paceline.club routes through Cloudflare which blocks headless browsers.
SITE_URL = "https://paceline-2akis.ondigitalocean.app"
BETA_PASSWORD = "pacelinesarefun"
CLUB_SLUG = "paceline-demo"

_ts = int(time.time())
TEST_USERNAME = f"e2e_checkout_{_ts}"
TEST_EMAIL = f"e2e_checkout_{_ts}@example.com"
TEST_PASSWORD = "E2eTest_CheckoutPass1!"

SCREENSHOT_DIR = os.path.join(os.path.dirname(__file__), "screenshots", "e2e_stripe")

STRIPE_CARD = "4242424242424242"
STRIPE_EXPIRY = "12 / 29"
STRIPE_CVC = "123"


# ── Helpers ───────────────────────────────────────────────────────────────────

def shot(page: Page, name: str) -> str:
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    path = os.path.join(SCREENSHOT_DIR, f"{name}.png")
    page.screenshot(path=path, full_page=True)
    print(f"  📸 {path}")
    return path


def goto(page: Page, url: str) -> None:
    """Navigate and wait for DOM content (avoids networkidle timeouts from iframes/analytics)."""
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(500)


def pass_beta_gate(page: Page) -> None:
    """Enter beta password if the gate page is showing."""
    if "/_beta" in page.url or page.locator("form[action='/_beta']").count() > 0:
        page.locator("input[name='password']").fill(BETA_PASSWORD)
        page.locator("button[type='submit']").click()
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(300)


# ── Test ──────────────────────────────────────────────────────────────────────

def test_stripe_checkout_full_dues_flow(page: Page) -> None:
    """
    Full Stripe Connect dues checkout workflow:
      1. Club home page (logged out)
      2. Register a new test user
      3. Join club → pending_payment status
      4. Pay Club Dues → Stripe Checkout
      5. Fill test card and pay
      6. Verify active membership on return
    """

    # ── Step 1: Club home (logged out) ────────────────────────────────────────
    print("\n→ Step 1: Club home page (logged out)")
    goto(page, f"{SITE_URL}/clubs/{CLUB_SLUG}/")
    pass_beta_gate(page)
    shot(page, "01_club_home_logged_out")

    # ── Step 2: Register test user ────────────────────────────────────────────
    print(f"→ Step 2: Register {TEST_USERNAME}")
    goto(page, f"{SITE_URL}/auth/register")
    pass_beta_gate(page)
    shot(page, "02_register_page")

    page.locator("input[name='username']").fill(TEST_USERNAME)
    page.locator("input[name='email']").fill(TEST_EMAIL)
    page.locator("input[name='password']").fill(TEST_PASSWORD)
    page.locator("input[name='confirm_password']").fill(TEST_PASSWORD)
    page.locator("input[name='policy_ack']").check()
    shot(page, "03_register_form_filled")

    page.get_by_role("button", name="Create Account").click()
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(500)
    shot(page, "04_after_registration")
    print(f"  Registered — now at: {page.url}")

    # ── Step 3: Go to club, join ──────────────────────────────────────────────
    print("→ Step 3: Club home (logged in) — join club")
    goto(page, f"{SITE_URL}/clubs/{CLUB_SLUG}/")
    shot(page, "05_club_home_logged_in")

    join_btn = page.locator("button:has-text('Join Club')")
    expect(join_btn).to_be_visible(timeout=8_000)
    join_btn.click()
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(500)
    shot(page, "06_after_join_pending_payment")
    print("  Joined club — expecting pending_payment with Pay Dues button")

    # ── Step 4: Pay Club Dues → Stripe Checkout ───────────────────────────────
    print("→ Step 4: Click Pay Club Dues")
    pay_btn = page.locator("button:has-text('Pay Club Dues')")
    expect(pay_btn).to_be_visible(timeout=8_000)
    shot(page, "07_pay_dues_button_visible")
    pay_btn.click()

    page.wait_for_url("**/checkout.stripe.com/**", timeout=20_000)
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(2_000)  # let Stripe JS render
    shot(page, "08_stripe_checkout_landing")
    print(f"  On Stripe Checkout: {page.url}")

    # ── Step 5: Select Card and fill details ─────────────────────────────────
    print("→ Step 5: Disable Stripe Link and select Card")

    # Uncheck "Save my information for faster checkout" to bypass Stripe Link
    # (leaving it checked forces a phone number before payment goes through)
    page.get_by_label("Save my information for faster checkout").uncheck()
    page.wait_for_timeout(1_500)
    shot(page, "09a_save_info_unchecked")

    # After unchecking Link, Card may now be visible directly or still behind accordion
    if page.locator('[placeholder="1234 1234 1234 1234"]').count() == 0:
        # Card form not yet expanded — click the card accordion button via JS
        page.evaluate(
            'document.querySelector(\'[data-testid="card-accordion-item-button"]\').click()'
        )
        page.wait_for_timeout(2_000)
    shot(page, "09_card_selected")

    print("→ Step 5b: Fill Stripe test card (4242...)")
    # Card inputs are directly in checkout.stripe.com main page (no nested iframes)
    page.locator('[placeholder="1234 1234 1234 1234"]').fill(STRIPE_CARD)
    page.wait_for_timeout(300)
    page.locator('[placeholder="MM / YY"]').fill(STRIPE_EXPIRY)
    page.wait_for_timeout(300)
    page.locator('[placeholder="CVC"]').fill(STRIPE_CVC)
    page.wait_for_timeout(300)
    # Cardholder name and ZIP are required
    page.locator('[placeholder="Full name on card"]').fill("E2E Tester")
    page.wait_for_timeout(200)
    zip_input = page.locator('[placeholder="ZIP"]')
    if zip_input.count() > 0:
        zip_input.fill("10001")
    page.wait_for_timeout(200)

    shot(page, "10_stripe_checkout_card_filled")

    # ── Step 6: Submit payment ────────────────────────────────────────────────
    print("→ Step 6: Submit payment")
    page.get_by_role("button", name="Pay", exact=True).click()
    page.wait_for_timeout(3_000)
    shot(page, "10b_after_pay_click")
    print(f"  After Pay click URL: {page.url}")

    # ── Step 7: Verify redirect and active membership ─────────────────────────
    print("→ Step 7: Wait for redirect back to Paceline")
    page.wait_for_url(f"**/{CLUB_SLUG}/**", timeout=30_000)
    page.wait_for_load_state("domcontentloaded")

    # Give webhook a moment to fire and activate membership
    print("  Waiting 4s for Stripe webhook to activate membership...")
    page.wait_for_timeout(4_000)
    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(500)
    shot(page, "11_after_payment_club_page")

    # Active member sees Leave Club, not Join Club or Pay Dues
    print("→ Verifying active membership")
    leave_btn = page.locator("button:has-text('Leave Club')")
    shot(page, "12_membership_active_verified")
    expect(leave_btn).to_be_visible(timeout=10_000)
    print("  ✅ Membership active — Leave Club button visible")
    shot(page, "13_final_state")

    print(f"\n✅ Full Stripe Connect dues checkout flow PASSED")
    print(f"   Test user : {TEST_USERNAME}  ({TEST_EMAIL})")
    print(f"   Screenshots: {SCREENSHOT_DIR}")


# ── Cancel flow ────────────────────────────────────────────────────────────────

def test_stripe_checkout_cancel_flow(page: Page) -> None:
    """
    User initiates dues checkout but abandons it at the Stripe page.

    Flow:
      1. Register a new test user
      2. Join club → pending_payment
      3. Click Pay Club Dues → redirected to Stripe
      4. Navigate directly to the cancel_url (simulates clicking Back / Cancel on Stripe)
      5. Verify membership is still pending_payment (Pay Dues button still visible)

    Stripe redirects to cancel_url when the user hits the browser back button or the
    explicit cancel link; this test exercises the same redirect target directly so we
    don't depend on Stripe's UI layout.
    """
    _ts_cancel = int(time.time()) + 1
    username = f"e2e_cancel_{_ts_cancel}"
    email = f"e2e_cancel_{_ts_cancel}@example.com"
    password = "E2eTest_CancelPass1!"

    # Register
    print(f"\n→ Cancel test: registering {username}")
    goto(page, f"{SITE_URL}/auth/register")
    pass_beta_gate(page)
    page.locator("input[name='username']").fill(username)
    page.locator("input[name='email']").fill(email)
    page.locator("input[name='password']").fill(password)
    page.locator("input[name='confirm_password']").fill(password)
    page.locator("input[name='policy_ack']").check()
    page.get_by_role("button", name="Create Account").click()
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(500)

    # Join club
    print("→ Cancel test: joining club")
    goto(page, f"{SITE_URL}/clubs/{CLUB_SLUG}/")
    join_btn = page.locator("button:has-text('Join Club')")
    expect(join_btn).to_be_visible(timeout=8_000)
    join_btn.click()
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(500)
    shot(page, "cancel_01_after_join_pending_payment")

    # Click Pay Club Dues → goes to Stripe
    print("→ Cancel test: clicking Pay Club Dues")
    pay_btn = page.locator("button:has-text('Pay Club Dues')")
    expect(pay_btn).to_be_visible(timeout=8_000)
    pay_btn.click()
    page.wait_for_url("**/checkout.stripe.com/**", timeout=20_000)
    page.wait_for_timeout(1_000)
    shot(page, "cancel_02_on_stripe_checkout")
    print(f"  On Stripe: {page.url}")

    # Simulate user abandoning checkout — navigate directly to cancel_url
    cancel_url = f"{SITE_URL}/clubs/{CLUB_SLUG}/?dues=cancel"
    print(f"→ Cancel test: navigating to cancel URL ({cancel_url})")
    goto(page, cancel_url)
    page.wait_for_timeout(500)
    shot(page, "cancel_03_after_cancel_redirect")

    # Membership should still be pending_payment — Pay Dues button must be visible
    print("→ Cancel test: verifying Pay Dues button still present")
    pay_btn_after = page.locator("button:has-text('Pay Club Dues')")
    expect(pay_btn_after).to_be_visible(timeout=8_000)
    shot(page, "cancel_04_pay_dues_still_visible")
    print("  ✅ Cancel flow verified — membership still pending_payment, Pay Dues visible")


# ── Declined card flow ─────────────────────────────────────────────────────────

STRIPE_CARD_DECLINED = "4000000000000002"


def test_stripe_checkout_declined_card(page: Page) -> None:
    """
    User reaches Stripe checkout, enters a card that is always declined, and sees
    an inline error. The user remains on the Stripe page (not redirected back).

    Stripe test card: 4000 0000 0000 0002 — always declined (generic decline).
    """
    _ts_decline = int(time.time()) + 2
    username = f"e2e_decline_{_ts_decline}"
    email = f"e2e_decline_{_ts_decline}@example.com"
    password = "E2eTest_DeclinePass1!"

    # Register
    print(f"\n→ Decline test: registering {username}")
    goto(page, f"{SITE_URL}/auth/register")
    pass_beta_gate(page)
    page.locator("input[name='username']").fill(username)
    page.locator("input[name='email']").fill(email)
    page.locator("input[name='password']").fill(password)
    page.locator("input[name='confirm_password']").fill(password)
    page.locator("input[name='policy_ack']").check()
    page.get_by_role("button", name="Create Account").click()
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(500)

    # Join club
    goto(page, f"{SITE_URL}/clubs/{CLUB_SLUG}/")
    join_btn = page.locator("button:has-text('Join Club')")
    expect(join_btn).to_be_visible(timeout=8_000)
    join_btn.click()
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(500)

    # Pay Club Dues → Stripe
    print("→ Decline test: clicking Pay Club Dues")
    pay_btn = page.locator("button:has-text('Pay Club Dues')")
    expect(pay_btn).to_be_visible(timeout=8_000)
    pay_btn.click()
    page.wait_for_url("**/checkout.stripe.com/**", timeout=20_000)
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(2_000)
    shot(page, "decline_01_stripe_checkout")

    # Disable Stripe Link save
    page.get_by_label("Save my information for faster checkout").uncheck()
    page.wait_for_timeout(1_500)

    if page.locator('[placeholder="1234 1234 1234 1234"]').count() == 0:
        page.evaluate(
            'document.querySelector(\'[data-testid="card-accordion-item-button"]\').click()'
        )
        page.wait_for_timeout(2_000)

    # Enter the always-declined card
    print("→ Decline test: entering declined card 4000000000000002")
    page.locator('[placeholder="1234 1234 1234 1234"]').fill(STRIPE_CARD_DECLINED)
    page.wait_for_timeout(300)
    page.locator('[placeholder="MM / YY"]').fill("12 / 29")
    page.wait_for_timeout(300)
    page.locator('[placeholder="CVC"]').fill("123")
    page.wait_for_timeout(300)
    page.locator('[placeholder="Full name on card"]').fill("E2E Decliner")
    page.wait_for_timeout(200)
    zip_input = page.locator('[placeholder="ZIP"]')
    if zip_input.count() > 0:
        zip_input.fill("10001")
    page.wait_for_timeout(200)
    shot(page, "decline_02_card_filled")

    page.get_by_role("button", name="Pay", exact=True).click()
    page.wait_for_timeout(5_000)
    shot(page, "decline_03_after_pay_click")
    print(f"  URL after declined pay: {page.url}")

    # Should still be on checkout.stripe.com with an error message
    assert "checkout.stripe.com" in page.url, (
        f"Expected to remain on Stripe checkout after decline, got: {page.url}"
    )
    # Stripe shows an inline error — any of these selectors may appear
    error_visible = (
        page.locator('[data-testid="error-message"]').count() > 0
        or page.locator('text=Your card has been declined').count() > 0
        or page.locator('text=declined').count() > 0
        or page.locator('[role="alert"]').count() > 0
    )
    shot(page, "decline_04_error_visible")
    assert error_visible, "Expected Stripe to show a card decline error message"
    print("  ✅ Decline flow verified — user sees error, stays on Stripe checkout")
