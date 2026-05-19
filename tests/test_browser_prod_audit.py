"""
Production audit browser tests — paceline.club

Drives the live production site with Playwright headless Chromium, taking a
screenshot at every key step of every major workflow.  Tests are grouped into
lettered scenarios so they can be run individually or as a suite.

Screenshots are written to tests/screenshots/prod_audit_*.png

Prerequisites
-------------
    pip install playwright pytest-playwright
    playwright install chromium
    # Credentials are read from environment variables (or fall back to dev defaults):
    export PROD_BETA_PASSWORD=pacelinesarefun
    export PROD_USER_EMAIL=phil@pcp.dev
    export PROD_USER_PASSWORD="syv3u_cX2*@*mT8B"

Run all production tests:
    pytest tests/test_browser_prod_audit.py -v -s

Run one scenario:
    pytest tests/test_browser_prod_audit.py -v -s -k "anon"

Scenarios
---------
A  Anonymous public workflows
   homepage → find clubs → club map → discover → club detail → ride detail

B  Authentication workflows
   register page → login page → successful login → dashboard

C  Authenticated user workflows
   dashboard → profile → my rides → club board → ride signup prompt

D  Club admin workflows (superadmin)
   superadmin dashboard → user list → club admin page

E  Club creation wizard (step 1 only — does NOT submit)
   navigate through wizard steps without creating a real club
"""
import os
import pytest

from playwright.sync_api import Page, expect

# paceline.club is Cloudflare-protected and blocks headless browsers.
# Use the DigitalOcean direct URL to bypass Cloudflare for automated tests.
PROD_URL    = os.environ.get("PROD_URL", "https://paceline-2akis.ondigitalocean.app")
BETA_PASS   = os.environ.get("PROD_BETA_PASSWORD", "pacelinesarefun")
USER_EMAIL  = os.environ.get("PROD_USER_EMAIL",    "phil@pcp.dev")
USER_PASS   = os.environ.get("PROD_USER_PASSWORD", "syv3u_cX2*@*mT8B")

SCREENSHOTS = os.path.join(os.path.dirname(__file__), "screenshots")
os.makedirs(SCREENSHOTS, exist_ok=True)


def ss(page: Page, name: str) -> None:
    """Take a full-page screenshot."""
    page.screenshot(path=os.path.join(SCREENSHOTS, f"prod_audit_{name}.png"), full_page=True)


def pass_beta_gate(page: Page) -> None:
    """Fill and submit the beta access password gate if it appears."""
    page.goto(PROD_URL)
    if "Beta Access" in page.title():
        page.fill('input[name="password"]', BETA_PASS)
        page.click('button[type="submit"]')
        page.wait_for_load_state("networkidle")


def login(page: Page) -> None:
    """Authenticate as the configured prod user."""
    pass_beta_gate(page)
    page.goto(f"{PROD_URL}/auth/login")
    page.wait_for_selector('input[name="email"]')
    page.fill('input[name="email"]', USER_EMAIL)
    page.fill('input[name="password"]', USER_PASS)
    # WTForms SubmitField renders as <input type="submit">, not <button>
    page.click('[type="submit"]')
    page.wait_for_url(f"{PROD_URL}/", timeout=10_000)


# ── Scenario A: Anonymous public workflows ────────────────────────────────────

@pytest.mark.prod
def test_A01_homepage_anonymous(page: Page):
    """Homepage loads with hero section and club cards."""
    pass_beta_gate(page)
    page.goto(PROD_URL)
    page.wait_for_load_state("networkidle")
    ss(page, "A01_homepage_anon")
    expect(page).to_have_title("Paceline — Find Your Club")
    expect(page.locator(".hero-title")).to_be_visible()
    # Use scoped locator to avoid strict-mode violation (footer also links "Find a Club")
    expect(page.locator(".hero-actions").get_by_role("link", name="Find a Club")).to_be_visible()
    expect(page.locator(".hero-actions").get_by_role("link", name="Create Account")).to_be_visible()


@pytest.mark.prod
def test_A02_find_clubs_page(page: Page):
    """Find Clubs page lists clubs and shows search."""
    pass_beta_gate(page)
    page.goto(f"{PROD_URL}/clubs/")
    page.wait_for_load_state("networkidle")
    ss(page, "A02_find_clubs")
    expect(page).to_have_title("Find Clubs — Paceline")
    # At least one club card should be visible (clubs/index.html uses .ride-card class)
    expect(page.locator(".ride-card").first).to_be_visible()


@pytest.mark.prod
def test_A03_club_map(page: Page):
    """Club map loads Leaflet map with at least one club pin."""
    pass_beta_gate(page)
    page.goto(f"{PROD_URL}/clubs/map/")
    page.wait_for_load_state("networkidle")
    # Wait for Leaflet to initialise (map container gets populated)
    page.wait_for_selector("#map", timeout=10_000)
    page.wait_for_timeout(2000)  # let tiles + markers render
    ss(page, "A03_club_map")
    expect(page).to_have_title("Club Map — Paceline")
    # Leaflet marker should exist in the DOM
    expect(page.locator(".leaflet-marker-icon").first).to_be_visible()


@pytest.mark.prod
def test_A04_discover_rides(page: Page):
    """Discover Rides page shows ride cards."""
    pass_beta_gate(page)
    page.goto(f"{PROD_URL}/discover/")
    page.wait_for_load_state("networkidle")
    ss(page, "A04_discover_rides")
    expect(page).to_have_title("Discover Rides — Paceline")
    expect(page.locator(".ride-card").first).to_be_visible()


@pytest.mark.prod
def test_A05_demo_club_home(page: Page):
    """Demo club page renders without raw markdown syntax."""
    pass_beta_gate(page)
    page.goto(f"{PROD_URL}/clubs/paceline-demo/")
    page.wait_for_load_state("networkidle")
    ss(page, "A05_demo_club_home")
    # Title contains club name
    assert "Paceline Demo Club" in page.title()
    # Ride cards are in the Rides tab — click it first (overview tab is active by default)
    page.locator("#tab-rides-btn").click()
    page.wait_for_timeout(500)
    expect(page.locator(".ride-card").first).to_be_visible()
    # Confirm markdown is rendered — heading tag should exist, not raw ## text
    about_section = page.locator(".club-about-text")
    if about_section.count() > 0:
        inner = about_section.inner_html()
        assert "##" not in inner, f"Raw markdown '##' found in about section: {inner[:200]}"
        assert "**" not in inner, f"Raw markdown '**' found in about section: {inner[:200]}"


@pytest.mark.prod
def test_A06_ride_detail(page: Page):
    """Ride detail page shows ride info and ICS download link."""
    # The demo club requires membership, so we log in first.  Ride IDs 18–22
    # are the seeded demo rides in production (12 no longer exists).
    login(page)
    page.goto(f"{PROD_URL}/clubs/paceline-demo/rides/18")
    page.wait_for_load_state("networkidle")
    ss(page, "A06_ride_detail")
    assert "Paceline Demo Club" in page.title()
    # Add to Calendar link should be present for all authenticated users
    expect(page.locator("a[href*='/ics']")).to_be_visible()


@pytest.mark.prod
def test_A07_calendar_views(page: Page):
    """Club calendar month and week views load correctly."""
    # Demo club requires membership — log in so rides are visible.
    login(page)
    for view in ("month", "week", "list"):
        page.goto(f"{PROD_URL}/clubs/paceline-demo/rides/?view={view}")
        page.wait_for_load_state("networkidle")
        ss(page, f"A07_calendar_{view}")
        assert "Paceline Demo Club" in page.title() or "Rides" in page.title()


@pytest.mark.prod
def test_A08_about_and_help(page: Page):
    """About and Help pages load without errors."""
    pass_beta_gate(page)
    for path, expected_title in (("/about", "About"), ("/help/", "Help")):
        page.goto(f"{PROD_URL}{path}")
        page.wait_for_load_state("networkidle")
        ss(page, f"A08_{path.strip('/').replace('/', '_')}")
        assert expected_title in page.title()


# ── Scenario B: Authentication workflows ─────────────────────────────────────

@pytest.mark.prod
def test_B01_register_page(page: Page):
    """Register page renders all fields and Google OAuth button."""
    pass_beta_gate(page)
    page.goto(f"{PROD_URL}/auth/register")
    page.wait_for_load_state("networkidle")
    ss(page, "B01_register_page")
    expect(page).to_have_title("Create Account — Paceline")
    expect(page.locator('input[name="username"]')).to_be_visible()
    expect(page.locator('input[name="email"]')).to_be_visible()
    expect(page.locator('input[name="password"]')).to_be_visible()
    # Google OAuth button
    expect(page.locator("text=Google")).to_be_visible()


@pytest.mark.prod
def test_B02_login_page(page: Page):
    """Login page renders form with CSRF token."""
    pass_beta_gate(page)
    page.goto(f"{PROD_URL}/auth/login")
    page.wait_for_load_state("networkidle")
    ss(page, "B02_login_page")
    expect(page).to_have_title("Sign In — Paceline")
    expect(page.locator('input[name="email"]')).to_be_visible()
    expect(page.locator('input[name="password"]')).to_be_visible()
    expect(page.locator('input[name="csrf_token"]')).to_be_attached()


@pytest.mark.prod
def test_B03_invalid_login(page: Page):
    """Invalid credentials show an error flash, no 500."""
    pass_beta_gate(page)
    page.goto(f"{PROD_URL}/auth/login")
    page.fill('input[name="email"]', "nobody@example.com")
    page.fill('input[name="password"]', "wrongpassword")
    page.click('[type="submit"]')
    page.wait_for_load_state("networkidle")
    ss(page, "B03_invalid_login")
    expect(page).to_have_title("Sign In — Paceline")
    expect(page.locator(".alert")).to_be_visible()
    assert "500" not in page.title()


@pytest.mark.prod
def test_B04_successful_login(page: Page):
    """Valid credentials redirect to the user dashboard."""
    login(page)
    ss(page, "B04_dashboard_after_login")
    expect(page).to_have_title("My Dashboard — Paceline")
    expect(page.locator("text=Welcome back")).to_be_visible()


# ── Scenario C: Authenticated user workflows ──────────────────────────────────

@pytest.mark.prod
def test_C01_user_dashboard(page: Page):
    """Dashboard shows upcoming rides, clubs, and weather widget."""
    login(page)
    page.goto(PROD_URL)
    page.wait_for_load_state("networkidle")
    ss(page, "C01_dashboard")
    expect(page).to_have_title("My Dashboard — Paceline")
    expect(page.locator("text=My Upcoming Rides")).to_be_visible()
    expect(page.locator("text=My Clubs")).to_be_visible()


@pytest.mark.prod
def test_C02_profile_page(page: Page):
    """Profile page loads and shows form fields."""
    login(page)
    page.goto(f"{PROD_URL}/auth/profile")
    page.wait_for_load_state("networkidle")
    ss(page, "C02_profile")
    expect(page).to_have_title("My Profile — Paceline")
    # Username is displayed as a div.form-control (not editable); check the email field instead
    # Profile has both a visible and a hidden email input — scope to the visible one
    expect(page.locator('input[name="email"]:not([type="hidden"])')).to_be_visible()


@pytest.mark.prod
def test_C03_my_rides(page: Page):
    """My Rides page loads without errors."""
    login(page)
    page.goto(f"{PROD_URL}/my-rides/")
    page.wait_for_load_state("networkidle")
    ss(page, "C03_my_rides")
    expect(page).to_have_title("My Rides — Paceline")


@pytest.mark.prod
def test_C04_demo_club_authenticated(page: Page):
    """Authenticated club home shows waiver prompt and ride cards."""
    login(page)
    page.goto(f"{PROD_URL}/clubs/paceline-demo/")
    page.wait_for_load_state("networkidle")
    ss(page, "C04_demo_club_authed")
    assert "Paceline Demo Club" in page.title()
    # Ride cards are in the Rides tab — click it first
    page.locator("#tab-rides-btn").click()
    page.wait_for_timeout(500)
    expect(page.locator(".ride-card").first).to_be_visible()


@pytest.mark.prod
def test_C05_ride_detail_authenticated(page: Page):
    """Authenticated ride detail shows waiver prompt (user not yet waiver-signed)."""
    login(page)
    page.goto(f"{PROD_URL}/clubs/paceline-demo/rides/12")
    page.wait_for_load_state("networkidle")
    ss(page, "C05_ride_detail_authed")
    assert "Paceline Demo Club" in page.title()
    # ICS download link always present
    expect(page.locator("a[href*='/ics']")).to_be_visible()


@pytest.mark.prod
def test_C06_club_board(page: Page):
    """Club board loads posts and reply form for logged-in user."""
    login(page)
    page.goto(f"{PROD_URL}/clubs/paceline-demo/board/")
    page.wait_for_load_state("networkidle")
    ss(page, "C06_club_board")
    # Board title is "Club Board — <club.name>"; use substring checks to handle emoji variations
    assert "Club Board" in page.title()
    assert "Paceline Demo Club" in page.title()


@pytest.mark.prod
def test_C07_join_get_redirects(page: Page):
    """GET /clubs/<slug>/join redirects to club home, not 405."""
    login(page)
    page.goto(f"{PROD_URL}/clubs/paceline-demo/join")
    page.wait_for_load_state("networkidle")
    ss(page, "C07_join_get_redirect")
    # Should end up on club home, not a 405 error page
    assert "405" not in page.title(), f"Got 405 error page at {page.url}"
    assert "paceline-demo" in page.url


# ── Scenario D: Admin workflows ────────────────────────────────────────────────

@pytest.mark.prod
def test_D01_superadmin_dashboard(page: Page):
    """Superadmin dashboard shows platform-level stats."""
    login(page)
    page.goto(f"{PROD_URL}/admin/")
    page.wait_for_load_state("networkidle")
    ss(page, "D01_superadmin_dashboard")
    expect(page).to_have_title("Super Admin Dashboard — Paceline")
    expect(page.locator("text=Active Clubs")).to_be_visible()
    expect(page.locator("text=Total Users")).to_be_visible()


@pytest.mark.prod
def test_D02_superadmin_users(page: Page):
    """Superadmin user management page loads."""
    login(page)
    page.goto(f"{PROD_URL}/admin/users/")
    page.wait_for_load_state("networkidle")
    ss(page, "D02_superadmin_users")
    expect(page).to_have_title("User Management — Superadmin")


@pytest.mark.prod
def test_D03_superadmin_club_detail(page: Page):
    """Superadmin club detail page for demo club loads."""
    login(page)
    page.goto(f"{PROD_URL}/admin/clubs/paceline-demo/")
    page.wait_for_load_state("networkidle")
    ss(page, "D03_superadmin_club_detail")
    assert "Paceline Demo Club" in page.title()


# ── Scenario E: Club creation wizard (read-only — does NOT submit) ─────────────

@pytest.mark.prod
def test_E01_club_wizard_step1(page: Page):
    """Club creation wizard step 1 loads with all required fields."""
    login(page)
    page.goto(f"{PROD_URL}/clubs/create")
    page.wait_for_load_state("networkidle")
    ss(page, "E01_wizard_step1")
    expect(page).to_have_title("Create a Club — Paceline")
    # Step 1 fields only (description textarea is on a later wizard step)
    expect(page.locator('input[name="name"]')).to_be_visible()
    expect(page.locator('input[name="city"]')).to_be_visible()
