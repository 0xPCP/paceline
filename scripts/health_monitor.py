#!/usr/bin/env python3
"""Paceline Pulse: standalone production health and latency monitor.

Designed to run in a tiny Docker container outside the Paceline web app. It
checks the public site, sends Resend email alerts on down events, and sends a
recovery email once the site is healthy again.
"""
from __future__ import annotations

import json
import os
import socket
import ssl
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, request


DEFAULT_STATE_PATH = '/state/paceline-pulse.json'


@dataclass
class CheckResult:
    ok: bool
    status_code: int | None = None
    elapsed_ms: int | None = None
    body_excerpt: str = ''
    error: str = ''


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None = None) -> str:
    return (dt or _utc_now()).isoformat(timespec='seconds')


def load_state(path: str) -> dict[str, Any]:
    state_path = Path(path)
    if not state_path.exists():
        return {
            'consecutive_failures': 0,
            'alert_active': False,
            'latency_alert_active': False,
            'last_success_at': None,
            'last_failure_at': None,
            'last_slow_at': None,
            'last_alert_at': None,
            'last_latency_alert_at': None,
        }
    try:
        return json.loads(state_path.read_text())
    except Exception:
        return {
            'consecutive_failures': 0,
            'alert_active': False,
            'latency_alert_active': False,
            'last_success_at': None,
            'last_failure_at': None,
            'last_slow_at': None,
            'last_alert_at': None,
            'last_latency_alert_at': None,
        }


def save_state(path: str, state: dict[str, Any]) -> None:
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_path.with_suffix('.tmp')
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
    tmp.replace(state_path)


def check_url(url: str, timeout: int, expected_text: str = '') -> CheckResult:
    started = time.monotonic()
    req = request.Request(
        url,
        headers={
            'User-Agent': 'PacelineHealthMonitor/1.0',
            'Accept': 'text/plain,application/json,text/html;q=0.9,*/*;q=0.8',
        },
    )
    try:
        with request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as resp:
            raw = resp.read(4096)
            elapsed_ms = int((time.monotonic() - started) * 1000)
            body = raw.decode('utf-8', errors='replace')
            status_code = getattr(resp, 'status', None)
            ok = bool(status_code and 200 <= status_code < 400)
            if expected_text:
                ok = ok and expected_text in body
            return CheckResult(
                ok=ok,
                status_code=status_code,
                elapsed_ms=elapsed_ms,
                body_excerpt=body[:800],
                error='' if ok else 'Unexpected status code or response body.',
            )
    except error.HTTPError as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        body = exc.read(4096).decode('utf-8', errors='replace') if exc.fp else ''
        return CheckResult(
            ok=False,
            status_code=exc.code,
            elapsed_ms=elapsed_ms,
            body_excerpt=body[:800],
            error=f'HTTPError: {exc}',
        )
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return CheckResult(
            ok=False,
            elapsed_ms=elapsed_ms,
            error=f'{type(exc).__name__}: {exc}',
        )


def _html_escape(value: Any) -> str:
    text = str(value or '')
    return (
        text.replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
    )


def build_down_email(url: str, state: dict[str, Any], result: CheckResult) -> tuple[str, str, str]:
    subject = '[CRITICAL] PACELINE.CLUB IS DOWN - IMMEDIATE ATTENTION REQUIRED'
    text = (
        'PACELINE PRODUCTION DOWN EVENT\n\n'
        f'URL: {url}\n'
        f'Time: {_iso()}\n'
        f'Host running monitor: {socket.gethostname()}\n'
        f'Consecutive failures: {state.get("consecutive_failures")}\n'
        f'Status code: {result.status_code or "none"}\n'
        f'Elapsed: {result.elapsed_ms} ms\n'
        f'Error: {result.error or "none"}\n'
        f'Last successful check: {state.get("last_success_at") or "unknown"}\n\n'
        'Response excerpt:\n'
        f'{result.body_excerpt or "(no response body)"}\n\n'
        'Suggested checks:\n'
        '1. Open https://paceline.club/health and https://paceline.club/ from a browser.\n'
        '2. Check DigitalOcean App Platform deployment/runtime logs.\n'
        '3. Check Managed PostgreSQL health and connection limits.\n'
        '4. Check Cloudflare/DNS/TLS status if the app health endpoint is reachable directly.\n'
        '5. If a deploy just happened, review the latest commit and migration/schema logs.\n'
    )
    html = f"""
    <h1 style="color:#b00020">PACELINE PRODUCTION DOWN EVENT</h1>
    <p><strong>URL:</strong> {_html_escape(url)}</p>
    <p><strong>Time:</strong> {_html_escape(_iso())}</p>
    <p><strong>Monitor host:</strong> {_html_escape(socket.gethostname())}</p>
    <p><strong>Consecutive failures:</strong> {_html_escape(state.get('consecutive_failures'))}</p>
    <p><strong>Status code:</strong> {_html_escape(result.status_code or 'none')}</p>
    <p><strong>Elapsed:</strong> {_html_escape(result.elapsed_ms)} ms</p>
    <p><strong>Error:</strong> {_html_escape(result.error or 'none')}</p>
    <p><strong>Last successful check:</strong> {_html_escape(state.get('last_success_at') or 'unknown')}</p>
    <h2>Response excerpt</h2>
    <pre style="white-space:pre-wrap;background:#f6f8fa;padding:12px;border-radius:6px">{_html_escape(result.body_excerpt or '(no response body)')}</pre>
    <h2>Suggested checks</h2>
    <ol>
      <li>Open <code>https://paceline.club/health</code> and <code>https://paceline.club/</code>.</li>
      <li>Check DigitalOcean App Platform deployment/runtime logs.</li>
      <li>Check Managed PostgreSQL health and connection limits.</li>
      <li>Check Cloudflare/DNS/TLS status if direct app health is reachable.</li>
      <li>If a deploy just happened, review the latest commit and migration/schema logs.</li>
    </ol>
    """
    return subject, html, text


def build_recovery_email(url: str, state: dict[str, Any], result: CheckResult) -> tuple[str, str, str]:
    subject = '[RECOVERED] Paceline.club health check is passing again'
    text = (
        'Paceline health check recovered.\n\n'
        f'URL: {url}\n'
        f'Time: {_iso()}\n'
        f'Status code: {result.status_code}\n'
        f'Elapsed: {result.elapsed_ms} ms\n'
        f'Previous failure time: {state.get("last_failure_at") or "unknown"}\n'
    )
    html = f"""
    <h1 style="color:#166534">Paceline health check recovered</h1>
    <p><strong>URL:</strong> {_html_escape(url)}</p>
    <p><strong>Time:</strong> {_html_escape(_iso())}</p>
    <p><strong>Status code:</strong> {_html_escape(result.status_code)}</p>
    <p><strong>Elapsed:</strong> {_html_escape(result.elapsed_ms)} ms</p>
    <p><strong>Previous failure time:</strong> {_html_escape(state.get('last_failure_at') or 'unknown')}</p>
    """
    return subject, html, text


def build_latency_email(
    url: str,
    state: dict[str, Any],
    result: CheckResult,
    threshold_ms: int,
) -> tuple[str, str, str]:
    subject = '[WARNING] PACELINE.CLUB IS SLOW - LATENCY DEGRADED'
    text = (
        'PACELINE PRODUCTION LATENCY WARNING\n\n'
        f'URL: {url}\n'
        f'Time: {_iso()}\n'
        f'Monitor: Paceline Pulse on {socket.gethostname()}\n'
        f'Latency threshold: {threshold_ms} ms\n'
        f'Observed latency: {result.elapsed_ms} ms\n'
        f'Status code: {result.status_code or "none"}\n'
        f'Consecutive slow checks: {state.get("consecutive_slow_checks")}\n'
        f'Last successful fast check: {state.get("last_success_at") or "unknown"}\n\n'
        'Suggested checks:\n'
        '1. Check DigitalOcean App Platform CPU/memory and recent deploy logs.\n'
        '2. Check database latency, connection count, and slow queries.\n'
        '3. Check Cloudflare/network timing if app logs look normal.\n'
        '4. Review recent feature changes that added dashboard, map, media, or recommendation queries.\n'
    )
    html = f"""
    <h1 style="color:#b45309">PACELINE PRODUCTION LATENCY WARNING</h1>
    <p><strong>URL:</strong> {_html_escape(url)}</p>
    <p><strong>Time:</strong> {_html_escape(_iso())}</p>
    <p><strong>Monitor:</strong> Paceline Pulse on {_html_escape(socket.gethostname())}</p>
    <p><strong>Latency threshold:</strong> {_html_escape(threshold_ms)} ms</p>
    <p><strong>Observed latency:</strong> {_html_escape(result.elapsed_ms)} ms</p>
    <p><strong>Status code:</strong> {_html_escape(result.status_code or 'none')}</p>
    <p><strong>Consecutive slow checks:</strong> {_html_escape(state.get('consecutive_slow_checks'))}</p>
    <p><strong>Last successful fast check:</strong> {_html_escape(state.get('last_success_at') or 'unknown')}</p>
    <h2>Suggested checks</h2>
    <ol>
      <li>Check DigitalOcean App Platform CPU/memory and recent deploy logs.</li>
      <li>Check database latency, connection count, and slow queries.</li>
      <li>Check Cloudflare/network timing if app logs look normal.</li>
      <li>Review recent feature changes that added dashboard, map, media, or recommendation queries.</li>
    </ol>
    """
    return subject, html, text


def build_latency_recovery_email(
    url: str,
    state: dict[str, Any],
    result: CheckResult,
    threshold_ms: int,
) -> tuple[str, str, str]:
    subject = '[RECOVERED] Paceline.club latency is back under threshold'
    text = (
        'Paceline latency recovered.\n\n'
        f'URL: {url}\n'
        f'Time: {_iso()}\n'
        f'Latency threshold: {threshold_ms} ms\n'
        f'Observed latency: {result.elapsed_ms} ms\n'
        f'Status code: {result.status_code}\n'
        f'Previous slow check time: {state.get("last_slow_at") or "unknown"}\n'
    )
    html = f"""
    <h1 style="color:#166534">Paceline latency recovered</h1>
    <p><strong>URL:</strong> {_html_escape(url)}</p>
    <p><strong>Time:</strong> {_html_escape(_iso())}</p>
    <p><strong>Latency threshold:</strong> {_html_escape(threshold_ms)} ms</p>
    <p><strong>Observed latency:</strong> {_html_escape(result.elapsed_ms)} ms</p>
    <p><strong>Status code:</strong> {_html_escape(result.status_code)}</p>
    <p><strong>Previous slow check time:</strong> {_html_escape(state.get('last_slow_at') or 'unknown')}</p>
    """
    return subject, html, text


def send_resend(subject: str, html: str, text: str) -> None:
    api_key = os.environ.get('RESEND_API_KEY', '').strip()
    if not api_key:
        raise RuntimeError('RESEND_API_KEY is not configured.')
    api_url = os.environ.get('RESEND_API_URL', 'https://api.resend.com/emails').strip()
    sender = os.environ.get('MAIL_DEFAULT_SENDER', 'Paceline Monitor <noreply@paceline.club>').strip()
    recipients = [
        value.strip()
        for value in os.environ.get('MONITOR_ALERT_TO', 'phil@pcp.dev').split(',')
        if value.strip()
    ]
    if not recipients:
        raise RuntimeError('MONITOR_ALERT_TO has no recipients.')
    payload = json.dumps({
        'from': sender,
        'to': recipients,
        'subject': subject,
        'html': html,
        'text': text,
    }).encode('utf-8')
    req = request.Request(
        api_url,
        data=payload,
        method='POST',
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        },
    )
    timeout = _env_int('RESEND_TIMEOUT_SECONDS', 10)
    with request.urlopen(req, timeout=timeout) as resp:
        if getattr(resp, 'status', 0) >= 400:
            raise RuntimeError(f'Resend returned HTTP {resp.status}')


def should_send_down_alert(state: dict[str, Any], failures_before_alert: int, cooldown_seconds: int) -> bool:
    if state.get('consecutive_failures', 0) < failures_before_alert:
        return False
    if not state.get('alert_active'):
        return True
    last_alert_raw = state.get('last_alert_at')
    if not last_alert_raw:
        return True
    try:
        last_alert = datetime.fromisoformat(last_alert_raw)
    except ValueError:
        return True
    return (_utc_now() - last_alert).total_seconds() >= cooldown_seconds


def should_send_latency_alert(state: dict[str, Any], slow_before_alert: int, cooldown_seconds: int) -> bool:
    if state.get('consecutive_slow_checks', 0) < slow_before_alert:
        return False
    if not state.get('latency_alert_active'):
        return True
    last_alert_raw = state.get('last_latency_alert_at')
    if not last_alert_raw:
        return True
    try:
        last_alert = datetime.fromisoformat(last_alert_raw)
    except ValueError:
        return True
    return (_utc_now() - last_alert).total_seconds() >= cooldown_seconds


def run_once(url: str, state_path: str) -> CheckResult:
    timeout = _env_int('MONITOR_TIMEOUT_SECONDS', 10)
    failures_before_alert = _env_int('MONITOR_FAILURES_BEFORE_ALERT', 3)
    latency_threshold_ms = _env_int('MONITOR_LATENCY_ALERT_MS', 3000)
    slow_before_alert = _env_int('MONITOR_LATENCY_FAILURES_BEFORE_ALERT', 3)
    cooldown_seconds = _env_int('MONITOR_ALERT_COOLDOWN_SECONDS', 1800)
    expected_text = os.environ.get('MONITOR_EXPECTED_TEXT', '').strip()

    state = load_state(state_path)
    result = check_url(url, timeout, expected_text)

    if result.ok:
        if state.get('alert_active'):
            subject, html, text = build_recovery_email(url, state, result)
            send_resend(subject, html, text)
        state['consecutive_failures'] = 0
        state['alert_active'] = False

        is_slow = bool(latency_threshold_ms > 0 and result.elapsed_ms and result.elapsed_ms > latency_threshold_ms)
        if is_slow:
            state['consecutive_slow_checks'] = int(state.get('consecutive_slow_checks') or 0) + 1
            state['last_slow_at'] = _iso()
            if should_send_latency_alert(state, slow_before_alert, cooldown_seconds):
                subject, html, text = build_latency_email(url, state, result, latency_threshold_ms)
                send_resend(subject, html, text)
                state['latency_alert_active'] = True
                state['last_latency_alert_at'] = _iso()
                print(
                    f'{_iso()} LATENCY ALERT SENT {url} '
                    f'slow_checks={state["consecutive_slow_checks"]} elapsed_ms={result.elapsed_ms}',
                    flush=True,
                )
            else:
                print(
                    f'{_iso()} SLOW {url} slow_checks={state["consecutive_slow_checks"]} '
                    f'elapsed_ms={result.elapsed_ms} threshold_ms={latency_threshold_ms}',
                    flush=True,
                )
            save_state(state_path, state)
            return result

        if state.get('latency_alert_active'):
            subject, html, text = build_latency_recovery_email(url, state, result, latency_threshold_ms)
            send_resend(subject, html, text)
        state['consecutive_slow_checks'] = 0
        state['latency_alert_active'] = False
        state['last_success_at'] = _iso()
        save_state(state_path, state)
        print(f'{_iso()} OK {url} status={result.status_code} elapsed_ms={result.elapsed_ms}', flush=True)
        return result

    state['consecutive_failures'] = int(state.get('consecutive_failures') or 0) + 1
    state['consecutive_slow_checks'] = 0
    state['last_failure_at'] = _iso()
    if should_send_down_alert(state, failures_before_alert, cooldown_seconds):
        subject, html, text = build_down_email(url, state, result)
        send_resend(subject, html, text)
        state['alert_active'] = True
        state['last_alert_at'] = _iso()
        print(f'{_iso()} ALERT SENT {url} failures={state["consecutive_failures"]} error={result.error}', flush=True)
    else:
        print(f'{_iso()} FAIL {url} failures={state["consecutive_failures"]} error={result.error}', flush=True)
    save_state(state_path, state)
    return result


def main() -> int:
    url = os.environ.get('MONITOR_URL', 'https://paceline.club/health').strip()
    interval = _env_int('MONITOR_INTERVAL_SECONDS', 60)
    state_path = os.environ.get('MONITOR_STATE_PATH', DEFAULT_STATE_PATH).strip()
    print(f'{_iso()} Starting Paceline Pulse url={url} interval={interval}s', flush=True)
    while True:
        try:
            run_once(url, state_path)
        except Exception as exc:
            print(f'{_iso()} Monitor internal error: {type(exc).__name__}: {exc}', flush=True)
            traceback.print_exc()
        time.sleep(interval)


if __name__ == '__main__':
    raise SystemExit(main())
