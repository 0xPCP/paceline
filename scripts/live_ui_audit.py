import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


BASE_URL = os.environ.get('PACELINE_BASE_URL', 'https://paceline.club').rstrip('/')
EMAIL = os.environ.get('PACELINE_EMAIL', '')
PASSWORD = os.environ.get('PACELINE_PASSWORD', '')
BETA_PASSWORD = os.environ.get('PACELINE_BETA_PASSWORD', '')
OUT_DIR = Path(os.environ.get('PACELINE_AUDIT_OUT', 'tests/screenshots/live_audit'))


PAGES = [
    ('home', '/'),
    ('clubs', '/clubs/'),
    ('discover', '/discover/'),
    ('about', '/about'),
    ('donate', '/donate'),
    ('help', '/help/'),
    ('club_manager_help', '/help/club-managers'),
    ('rider_help', '/help/riders'),
    ('admin_dashboard', '/admin/'),
    ('profile', '/auth/profile'),
]


def required_env():
    missing = [
        name for name, value in (
            ('PACELINE_EMAIL', EMAIL),
            ('PACELINE_PASSWORD', PASSWORD),
            ('PACELINE_BETA_PASSWORD', BETA_PASSWORD),
        )
        if not value
    ]
    if missing:
        print(f'Missing required env vars: {", ".join(missing)}', file=sys.stderr)
        sys.exit(2)


def safe_name(name):
    return re.sub(r'[^a-z0-9_.-]+', '_', name.lower())


def maybe_pass_beta_gate(page):
    if '/_beta' not in page.url and 'Enter the beta access password' not in page.content():
        return
    if page.locator('input[name="password"]').count() == 0:
        raise RuntimeError(f'Beta gate password field was not available. Title: {page.title()} URL: {page.url}')
    page.fill('input[name="password"]', BETA_PASSWORD)
    page.click('button[type="submit"], input[type="submit"]')
    page.wait_for_load_state('domcontentloaded')
    page.wait_for_timeout(1000)


def wait_for_cloudflare(page):
    if 'Just a moment' not in page.title() and 'cf-mitigated' not in page.content():
        return
    try:
        page.wait_for_function(
            "() => !document.title.includes('Just a moment')",
            timeout=25000,
        )
    except PlaywrightTimeoutError:
        return
    page.wait_for_timeout(1000)


def login(page):
    page.goto(urljoin(BASE_URL + '/', '_beta'), wait_until='domcontentloaded', timeout=45000)
    page.wait_for_timeout(1000)
    wait_for_cloudflare(page)
    maybe_pass_beta_gate(page)
    page.goto(urljoin(BASE_URL + '/', 'auth/login'), wait_until='domcontentloaded', timeout=45000)
    page.wait_for_timeout(1000)
    wait_for_cloudflare(page)
    maybe_pass_beta_gate(page)
    if 'auth/login' not in page.url and 'Sign In' not in page.content():
        return
    if page.locator('input[name="email"]').count() == 0:
        debug_path = OUT_DIR / 'debug_login_page.png'
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(debug_path), full_page=True)
        raise RuntimeError(f'Login email field was not available. Title: {page.title()} URL: {page.url} Screenshot: {debug_path}')
    page.fill('input[name="email"]', EMAIL)
    page.fill('input[name="password"]', PASSWORD)
    page.click('button[type="submit"], input[type="submit"]')
    page.wait_for_load_state('domcontentloaded')
    page.wait_for_timeout(1000)


def collect_metrics(page):
    return page.evaluate(
        """
        () => {
          const header = document.querySelector('header, nav.navbar, .navbar, .site-header');
          const links = Array.from(document.querySelectorAll(
            'header a, header button, nav a, nav button, .navbar a, .navbar button'
          )).slice(0, 30);
          const h1 = document.querySelector('h1');
          const body = document.body;
          const styleFor = (el) => {
            if (!el) return null;
            const cs = getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return {
              text: (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 80),
              tag: el.tagName.toLowerCase(),
              fontSize: cs.fontSize,
              fontWeight: cs.fontWeight,
              lineHeight: cs.lineHeight,
              height: Math.round(rect.height),
              width: Math.round(rect.width),
              className: el.className || '',
            };
          };
          return {
            title: document.title,
            url: location.href,
            bodyText: body ? body.innerText.slice(0, 5000) : '',
            header: styleFor(header),
            h1: styleFor(h1),
            navItems: links.map(styleFor).filter(Boolean),
            viewport: { width: innerWidth, height: innerHeight },
          };
        }
        """
    )


def audit_viewport(browser, viewport_name, viewport):
    context = browser.new_context(
        viewport=viewport,
        user_agent=(
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
            '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
        ),
    )
    page = context.new_page()
    console_errors = []
    page_errors = []
    failed_requests = []

    page.on('console', lambda msg: console_errors.append({
        'type': msg.type,
        'text': msg.text,
        'url': page.url,
    }) if msg.type in ('error', 'warning') else None)
    page.on('pageerror', lambda exc: page_errors.append({'error': str(exc), 'url': page.url}))
    page.on('response', lambda response: failed_requests.append({
        'status': response.status,
        'url': response.url,
    }) if response.status >= 400 and not response.url.startswith('data:') else None)

    login(page)
    results = []
    for name, path in PAGES:
        url = urljoin(BASE_URL + '/', path.lstrip('/'))
        entry = {'name': name, 'path': path, 'viewport': viewport_name, 'url': url}
        try:
            page.goto(url, wait_until='domcontentloaded', timeout=45000)
            wait_for_cloudflare(page)
            maybe_pass_beta_gate(page)
            page.wait_for_timeout(750)
            entry['status_url'] = page.url
            entry['metrics'] = collect_metrics(page)
            screenshot_path = OUT_DIR / f'{viewport_name}_{safe_name(name)}.png'
            page.screenshot(path=str(screenshot_path), full_page=True)
            entry['screenshot'] = str(screenshot_path)
        except PlaywrightTimeoutError as exc:
            entry['error'] = f'timeout: {exc}'
        except Exception as exc:
            entry['error'] = str(exc)
        results.append(entry)

    context.close()
    return {
        'viewport': viewport_name,
        'results': results,
        'console_errors': console_errors,
        'page_errors': page_errors,
        'failed_requests': failed_requests,
    }


def summarize(audit):
    summaries = []
    for viewport in audit['viewports']:
        for result in viewport['results']:
            metrics = result.get('metrics') or {}
            header = metrics.get('header') or {}
            h1 = metrics.get('h1') or {}
            nav_sizes = sorted({
                item.get('fontSize')
                for item in metrics.get('navItems', [])
                if item.get('text') and item.get('fontSize')
            })
            summaries.append({
                'viewport': result['viewport'],
                'name': result['name'],
                'final_url': result.get('status_url'),
                'title': metrics.get('title'),
                'header_height': header.get('height'),
                'header_font_size': header.get('fontSize'),
                'h1': h1.get('text'),
                'h1_font_size': h1.get('fontSize'),
                'nav_font_sizes': nav_sizes,
                'screenshot': result.get('screenshot'),
                'error': result.get('error'),
            })
    return summaries


def main():
    required_env()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=['--disable-blink-features=AutomationControlled'],
        )
        audit = {
            'base_url': BASE_URL,
            'viewports': [
                audit_viewport(browser, 'desktop', {'width': 1440, 'height': 1000}),
                audit_viewport(browser, 'mobile', {'width': 390, 'height': 844}),
            ],
        }
        browser.close()

    audit['summary'] = summarize(audit)
    report_path = OUT_DIR / 'audit.json'
    report_path.write_text(json.dumps(audit, indent=2), encoding='utf-8')
    print(json.dumps(audit['summary'], indent=2))
    print(f'\nFull report: {report_path}')


if __name__ == '__main__':
    main()
