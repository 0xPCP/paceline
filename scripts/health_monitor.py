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
import threading
import time
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, request


DEFAULT_STATE_PATH = '/state/paceline-pulse.json'
DEFAULT_HISTORY_PATH = '/state/paceline-pulse-history.json'
DEFAULT_HISTORY_LIMIT = 1440

# Project sunset date — shut down if no clubs join by then
_SUNSET_DATE = datetime(2027, 6, 1, tzinfo=timezone.utc)


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
            'consecutive_slow_checks': 0,
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
            'consecutive_slow_checks': 0,
        }


def save_state(path: str, state: dict[str, Any]) -> None:
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_path.with_suffix('.tmp')
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
    tmp.replace(state_path)


def load_history(path: str) -> list[dict[str, Any]]:
    history_path = Path(path)
    if not history_path.exists():
        return []
    try:
        data = json.loads(history_path.read_text())
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def save_history(path: str, history: list[dict[str, Any]]) -> None:
    history_path = Path(path)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = history_path.with_suffix('.tmp')
    tmp.write_text(json.dumps(history, indent=2, sort_keys=True))
    tmp.replace(history_path)


def record_history(path: str, state: dict[str, Any], result: CheckResult, limit: int | None = None) -> None:
    limit = limit or _env_int('MONITOR_HISTORY_LIMIT', DEFAULT_HISTORY_LIMIT)
    history = load_history(path)
    history.append({
        'checked_at': _iso(),
        'ok': result.ok,
        'status_code': result.status_code,
        'elapsed_ms': result.elapsed_ms,
        'error': result.error,
        'alert_active': bool(state.get('alert_active')),
        'latency_alert_active': bool(state.get('latency_alert_active')),
    })
    if limit > 0:
        history = history[-limit:]
    save_history(path, history)


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


def _percentile(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return ordered[index]


def summarize_monitor(
    state: dict[str, Any],
    history: list[dict[str, Any]],
    latency_threshold_ms: int,
) -> dict[str, Any]:
    latest = history[-1] if history else {}
    recent = history[-1440:]
    latencies = [
        int(item['elapsed_ms'])
        for item in recent
        if isinstance(item.get('elapsed_ms'), int) and item.get('ok')
    ]
    checks = len(recent)
    failures = sum(1 for item in recent if not item.get('ok'))
    slow = sum(
        1
        for item in recent
        if item.get('ok')
        and isinstance(item.get('elapsed_ms'), int)
        and latency_threshold_ms > 0
        and item['elapsed_ms'] > latency_threshold_ms
    )
    if latest.get('ok') is False or state.get('alert_active'):
        color = 'red'
        label = 'Down'
    elif state.get('latency_alert_active') or (
        latest.get('ok') and latency_threshold_ms > 0 and (latest.get('elapsed_ms') or 0) > latency_threshold_ms
    ):
        color = 'yellow'
        label = 'Slow'
    elif latest:
        color = 'green'
        label = 'Healthy'
    else:
        color = 'gray'
        label = 'Waiting for first check'
    uptime = None
    if checks:
        uptime = round(((checks - failures) / checks) * 100, 2)
    return {
        'name': 'Paceline Pulse',
        'status_color': color,
        'status_label': label,
        'latest': latest,
        'checks_recorded': checks,
        'failures_recorded': failures,
        'slow_checks_recorded': slow,
        'uptime_percent': uptime,
        'avg_latency_ms': round(sum(latencies) / len(latencies)) if latencies else None,
        'p95_latency_ms': _percentile(latencies, 0.95),
        'max_latency_ms': max(latencies) if latencies else None,
        'latency_threshold_ms': latency_threshold_ms,
        'state': state,
        'history': recent[-180:],
    }


def render_dashboard(summary: dict[str, Any], monitored_url: str, interval_seconds: int) -> str:
    history = summary['history']
    max_latency = max(
        [summary.get('latency_threshold_ms') or 0]
        + [item.get('elapsed_ms') or 0 for item in history if item.get('ok')]
        + [100]
    )
    bars = []
    for item in history[-90:]:
        elapsed = item.get('elapsed_ms') or 0
        height = max(5, min(100, round((elapsed / max_latency) * 100))) if item.get('ok') else 100
        if not item.get('ok'):
            css = 'bar red'
        elif summary['latency_threshold_ms'] > 0 and elapsed > summary['latency_threshold_ms']:
            css = 'bar yellow'
        else:
            css = 'bar green'
        title = f"{item.get('checked_at')} - {item.get('status_code') or 'error'} - {elapsed} ms"
        bars.append(f'<span class="{css}" title="{_html_escape(title)}" style="height:{height}%"></span>')
    latest = summary.get('latest') or {}
    state = summary.get('state') or {}
    status_class = summary['status_color']
    days_left = _days_until_sunset()
    cards = [
        ('Current status', summary['status_label']),
        ('Latest latency', _format_ms(latest.get('elapsed_ms'))),
        ('24h uptime', _format_percent(summary.get('uptime_percent'))),
        ('Average latency', _format_ms(summary.get('avg_latency_ms'))),
        ('P95 latency', _format_ms(summary.get('p95_latency_ms'))),
        ('Slow checks', str(summary.get('slow_checks_recorded') or 0)),
        ('Failures', str(summary.get('failures_recorded') or 0)),
        ('Last success', state.get('last_success_at') or 'unknown'),
        ('Days to 1 Jun 2027', str(days_left)),
    ]
    card_html = ''.join(
        f'<section class="card"><div class="label">{_html_escape(label)}</div>'
        f'<div class="value">{_html_escape(value)}</div></section>'
        for label, value in cards
    )
    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="30">
  <title>Paceline Pulse</title>
  <style>
    :root {{ color-scheme: light; --ink:#17211b; --muted:#607064; --line:#dfe7e1; --bg:#f6f8f5; --card:#fff; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background:var(--bg); color:var(--ink); }}
    main {{ max-width:1180px; margin:0 auto; padding:32px 20px 48px; }}
    header {{ display:flex; align-items:flex-start; justify-content:space-between; gap:24px; margin-bottom:28px; }}
    h1 {{ margin:0; font-size:2rem; letter-spacing:0; }}
    .subtle {{ color:var(--muted); margin-top:6px; }}
    .pill {{ display:inline-flex; align-items:center; gap:10px; border:1px solid var(--line); border-radius:999px; padding:10px 14px; background:#fff; font-weight:700; }}
    .dot {{ width:14px; height:14px; border-radius:50%; display:inline-block; }}
    .green .dot, .bar.green {{ background:#16803c; }}
    .yellow .dot, .bar.yellow {{ background:#d89a00; }}
    .red .dot, .bar.red {{ background:#b42318; }}
    .gray .dot {{ background:#8b9490; }}
    .grid {{ display:grid; grid-template-columns:repeat(4, minmax(0, 1fr)); gap:14px; }}
    .card {{ background:var(--card); border:1px solid var(--line); border-radius:8px; padding:18px; min-height:104px; }}
    .label {{ color:var(--muted); font-size:.86rem; margin-bottom:10px; }}
    .value {{ font-size:1.35rem; font-weight:750; overflow-wrap:anywhere; }}
    .panel {{ margin-top:18px; background:#fff; border:1px solid var(--line); border-radius:8px; padding:20px; }}
    .panel h2 {{ margin:0 0 14px; font-size:1.05rem; }}
    .bars {{ height:180px; display:flex; align-items:flex-end; gap:3px; border-bottom:1px solid var(--line); padding-top:16px; }}
    .bar {{ flex:1; min-width:3px; border-radius:3px 3px 0 0; opacity:.9; }}
    .details {{ display:grid; grid-template-columns:180px 1fr; gap:10px 18px; margin:0; }}
    .details dt {{ color:var(--muted); }}
    .details dd {{ margin:0; overflow-wrap:anywhere; }}
    @media (max-width: 820px) {{ header {{ flex-direction:column; }} .grid {{ grid-template-columns:repeat(2, minmax(0, 1fr)); }} .details {{ grid-template-columns:1fr; }} }}
    @media (max-width: 520px) {{ main {{ padding:22px 12px 36px; }} .grid {{ grid-template-columns:1fr; }} h1 {{ font-size:1.55rem; }} }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>Paceline Pulse</h1>
        <div class="subtle">Monitoring {_html_escape(monitored_url)} every {_html_escape(interval_seconds)} seconds</div>
      </div>
      <div class="pill {status_class}"><span class="dot"></span>{_html_escape(summary['status_label'])}</div>
    </header>
    <div class="grid">{card_html}</div>
    <section class="panel">
      <h2>Latency trend</h2>
      <div class="bars">{''.join(bars) or '<div class="subtle">Waiting for check history.</div>'}</div>
      <p class="subtle">Last 90 checks. Green is healthy, yellow is above threshold, red is failed.</p>
    </section>
    <section class="panel">
      <h2>Latest check</h2>
      <dl class="details">
        <dt>Checked at</dt><dd>{_html_escape(latest.get('checked_at') or 'unknown')}</dd>
        <dt>Status code</dt><dd>{_html_escape(latest.get('status_code') or 'none')}</dd>
        <dt>Error</dt><dd>{_html_escape(latest.get('error') or 'none')}</dd>
        <dt>Consecutive failures</dt><dd>{_html_escape(state.get('consecutive_failures') or 0)}</dd>
        <dt>Consecutive slow checks</dt><dd>{_html_escape(state.get('consecutive_slow_checks') or 0)}</dd>
        <dt>Last failure</dt><dd>{_html_escape(state.get('last_failure_at') or 'none')}</dd>
        <dt>Last slow check</dt><dd>{_html_escape(state.get('last_slow_at') or 'none')}</dd>
      </dl>
    </section>
    <p class="subtle" style="margin-top:24px;font-size:.82rem">
      Paceline runs until 1 June 2027. If no clubs have joined by then, the project shuts down.
      {_html_escape(days_left)} days remaining.
    </p>
  </main>
</body>
</html>'''


def _format_ms(value: Any) -> str:
    return f'{value} ms' if value is not None else 'unknown'


def _format_percent(value: Any) -> str:
    return f'{value}%' if value is not None else 'unknown'


def _days_until_sunset() -> int:
    return max(0, (_SUNSET_DATE - _utc_now()).days)


def make_dashboard_handler(state_path: str, history_path: str, monitored_url: str, interval_seconds: int):
    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if not self._authorized():
                self.send_response(HTTPStatus.UNAUTHORIZED)
                self.send_header('WWW-Authenticate', 'Basic realm="Paceline Pulse"')
                self.end_headers()
                return
            latency_threshold_ms = _env_int('MONITOR_LATENCY_ALERT_MS', 3000)
            state = load_state(state_path)
            history = load_history(history_path)
            summary = summarize_monitor(state, history, latency_threshold_ms)
            if self.path == '/api/status':
                body = json.dumps(summary, sort_keys=True).encode('utf-8')
                self.send_response(HTTPStatus.OK)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path not in ('/', '/dashboard'):
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            body = render_dashboard(summary, monitored_url, interval_seconds).encode('utf-8')
            self.send_response(HTTPStatus.OK)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args: Any) -> None:
            print(f'{_iso()} Dashboard {self.address_string()} {fmt % args}', flush=True)

        def _authorized(self) -> bool:
            username = os.environ.get('MONITOR_DASHBOARD_USERNAME', '').strip()
            password = os.environ.get('MONITOR_DASHBOARD_PASSWORD', '').strip()
            if not username and not password:
                return True
            import base64
            header = self.headers.get('Authorization', '')
            if not header.startswith('Basic '):
                return False
            try:
                decoded = base64.b64decode(header.removeprefix('Basic ').strip()).decode('utf-8')
            except Exception:
                return False
            return decoded == f'{username}:{password}'

    return DashboardHandler


def start_dashboard_server(state_path: str, history_path: str, monitored_url: str, interval_seconds: int) -> None:
    if os.environ.get('MONITOR_DASHBOARD_ENABLED', 'true').lower() in ('0', 'false', 'no'):
        return
    host = os.environ.get('MONITOR_DASHBOARD_HOST', '0.0.0.0').strip()
    port = _env_int('MONITOR_DASHBOARD_PORT', 8080)
    handler = make_dashboard_handler(state_path, history_path, monitored_url, interval_seconds)
    server = ThreadingHTTPServer((host, port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f'{_iso()} Paceline Pulse dashboard listening on http://{host}:{port}', flush=True)


def run_once(url: str, state_path: str, history_path: str | None = None) -> CheckResult:
    timeout = _env_int('MONITOR_TIMEOUT_SECONDS', 10)
    failures_before_alert = _env_int('MONITOR_FAILURES_BEFORE_ALERT', 3)
    latency_threshold_ms = _env_int('MONITOR_LATENCY_ALERT_MS', 3000)
    slow_before_alert = _env_int('MONITOR_LATENCY_FAILURES_BEFORE_ALERT', 3)
    cooldown_seconds = _env_int('MONITOR_ALERT_COOLDOWN_SECONDS', 1800)
    expected_text = os.environ.get('MONITOR_EXPECTED_TEXT', '').strip()
    history_path = history_path or os.environ.get('MONITOR_HISTORY_PATH', DEFAULT_HISTORY_PATH).strip()

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
            record_history(history_path, state, result)
            return result

        if state.get('latency_alert_active'):
            subject, html, text = build_latency_recovery_email(url, state, result, latency_threshold_ms)
            send_resend(subject, html, text)
        state['consecutive_slow_checks'] = 0
        state['latency_alert_active'] = False
        state['last_success_at'] = _iso()
        save_state(state_path, state)
        record_history(history_path, state, result)
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
    record_history(history_path, state, result)
    return result


def main() -> int:
    url = os.environ.get('MONITOR_URL', 'https://paceline.club/health').strip()
    interval = _env_int('MONITOR_INTERVAL_SECONDS', 60)
    state_path = os.environ.get('MONITOR_STATE_PATH', DEFAULT_STATE_PATH).strip()
    history_path = os.environ.get('MONITOR_HISTORY_PATH', DEFAULT_HISTORY_PATH).strip()
    print(f'{_iso()} Starting Paceline Pulse url={url} interval={interval}s', flush=True)
    start_dashboard_server(state_path, history_path, url, interval)
    while True:
        try:
            run_once(url, state_path, history_path)
        except Exception as exc:
            print(f'{_iso()} Monitor internal error: {type(exc).__name__}: {exc}', flush=True)
            traceback.print_exc()
        time.sleep(interval)


if __name__ == '__main__':
    raise SystemExit(main())
