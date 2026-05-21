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
    save_state,
    should_send_down_alert,
    should_send_latency_alert,
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
