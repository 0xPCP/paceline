import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from scripts.health_monitor import (
    CheckResult,
    build_down_email,
    build_latency_email,
    build_latency_recovery_email,
    build_recovery_email,
    load_state,
    load_history,
    record_history,
    render_dashboard,
    save_state,
    should_send_down_alert,
    should_send_latency_alert,
    summarize_monitor,
)


def test_state_round_trip(tmp_path):
    path = tmp_path / 'state.json'
    state = {'consecutive_failures': 2, 'alert_active': True}

    save_state(str(path), state)

    assert load_state(str(path)) == state


def test_missing_state_defaults(tmp_path):
    state = load_state(str(tmp_path / 'missing.json'))

    assert state['consecutive_failures'] == 0
    assert state['alert_active'] is False


def test_down_alert_subject_is_scary_and_detailed():
    state = {
        'consecutive_failures': 3,
        'last_success_at': '2026-05-21T10:00:00+00:00',
    }
    result = CheckResult(
        ok=False,
        status_code=503,
        elapsed_ms=1200,
        body_excerpt='database unavailable',
        error='HTTPError: 503 Service Unavailable',
    )

    subject, html, text = build_down_email('https://paceline.club/health', state, result)

    assert '[CRITICAL]' in subject
    assert 'IMMEDIATE ATTENTION REQUIRED' in subject
    assert 'database unavailable' in text
    assert 'DigitalOcean App Platform' in text
    assert 'HTTPError: 503' in html


def test_recovery_email_includes_previous_failure():
    state = {'last_failure_at': '2026-05-21T10:05:00+00:00'}
    result = CheckResult(ok=True, status_code=200, elapsed_ms=100)

    subject, html, text = build_recovery_email('https://paceline.club/health', state, result)

    assert '[RECOVERED]' in subject
    assert '2026-05-21T10:05:00+00:00' in text
    assert '200' in html


def test_latency_alert_subject_and_details():
    state = {
        'consecutive_slow_checks': 3,
        'last_success_at': '2026-05-21T10:00:00+00:00',
    }
    result = CheckResult(ok=True, status_code=200, elapsed_ms=4500)

    subject, html, text = build_latency_email('https://paceline.club/health', state, result, 3000)

    assert '[WARNING]' in subject
    assert 'LATENCY DEGRADED' in subject
    assert '4500 ms' in text
    assert 'DigitalOcean App Platform' in text
    assert 'Paceline Pulse' in html


def test_latency_recovery_email():
    state = {'last_slow_at': '2026-05-21T10:10:00+00:00'}
    result = CheckResult(ok=True, status_code=200, elapsed_ms=250)

    subject, html, text = build_latency_recovery_email('https://paceline.club/health', state, result, 3000)

    assert '[RECOVERED]' in subject
    assert '250 ms' in text
    assert '3000' in html


def test_should_send_down_alert_after_threshold():
    state = {
        'consecutive_failures': 3,
        'alert_active': False,
        'last_alert_at': None,
    }

    assert should_send_down_alert(state, failures_before_alert=3, cooldown_seconds=1800)


def test_should_not_send_before_threshold():
    state = {
        'consecutive_failures': 2,
        'alert_active': False,
        'last_alert_at': None,
    }

    assert not should_send_down_alert(state, failures_before_alert=3, cooldown_seconds=1800)


def test_alert_cooldown_is_respected():
    last_alert = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
    state = {
        'consecutive_failures': 10,
        'alert_active': True,
        'last_alert_at': last_alert,
    }

    assert not should_send_down_alert(state, failures_before_alert=3, cooldown_seconds=1800)


def test_should_send_latency_alert_after_threshold():
    state = {
        'consecutive_slow_checks': 3,
        'latency_alert_active': False,
        'last_latency_alert_at': None,
    }

    assert should_send_latency_alert(state, slow_before_alert=3, cooldown_seconds=1800)


def test_latency_alert_cooldown_is_respected():
    last_alert = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
    state = {
        'consecutive_slow_checks': 10,
        'latency_alert_active': True,
        'last_latency_alert_at': last_alert,
    }

    assert not should_send_latency_alert(state, slow_before_alert=3, cooldown_seconds=1800)


def test_record_history_keeps_recent_checks(tmp_path):
    path = tmp_path / 'history.json'
    state = {'alert_active': False, 'latency_alert_active': False}

    for i in range(5):
        record_history(str(path), state, CheckResult(ok=True, status_code=200, elapsed_ms=100 + i), limit=3)

    history = load_history(str(path))

    assert len(history) == 3
    assert history[0]['elapsed_ms'] == 102
    assert history[-1]['elapsed_ms'] == 104


def test_dashboard_summary_status_colors():
    state = {'alert_active': False, 'latency_alert_active': False}
    history = [
        {'ok': True, 'status_code': 200, 'elapsed_ms': 200, 'checked_at': '2026-05-21T10:00:00+00:00'},
        {'ok': True, 'status_code': 200, 'elapsed_ms': 4500, 'checked_at': '2026-05-21T10:01:00+00:00'},
    ]

    summary = summarize_monitor(state, history, latency_threshold_ms=3000)

    assert summary['status_color'] == 'yellow'
    assert summary['status_label'] == 'Slow'
    assert summary['checks_recorded'] == 2
    assert summary['slow_checks_recorded'] == 1
    assert summary['avg_latency_ms'] == 2350


def test_dashboard_summary_red_when_down():
    state = {'alert_active': True, 'latency_alert_active': False}
    history = [
        {'ok': False, 'status_code': 503, 'elapsed_ms': 120, 'checked_at': '2026-05-21T10:00:00+00:00'},
    ]

    summary = summarize_monitor(state, history, latency_threshold_ms=3000)

    assert summary['status_color'] == 'red'
    assert summary['status_label'] == 'Down'
    assert summary['failures_recorded'] == 1


def test_render_dashboard_contains_status_and_trend():
    summary = summarize_monitor(
        {'alert_active': False, 'latency_alert_active': False, 'last_success_at': '2026-05-21T10:00:00+00:00'},
        [{'ok': True, 'status_code': 200, 'elapsed_ms': 180, 'checked_at': '2026-05-21T10:00:00+00:00'}],
        latency_threshold_ms=3000,
    )

    html = render_dashboard(summary, 'https://paceline.club/health', 60)

    assert 'Paceline Pulse' in html
    assert 'Healthy' in html
    assert 'Latency trend' in html
    assert 'https://paceline.club/health' in html
