import pytest

from app import create_app
from app.config import Config

pytestmark = pytest.mark.skip(reason='Beta password gate was removed for public launch.')


class BetaGateConfig(Config):
    TESTING = False
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_ENGINE_OPTIONS = {}
    WTF_CSRF_ENABLED = False
    COOKIE_SECURE = False
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False
    SECRET_KEY = 'beta-gate-test-secret'


def _beta_app(monkeypatch):
    monkeypatch.setenv('BETA_PASSWORD', 'letmein')
    monkeypatch.setenv('FLASK_SKIP_SCHEDULER', '1')
    return create_app(BetaGateConfig)


def test_beta_gate_preserves_safe_relative_next(monkeypatch):
    app = _beta_app(monkeypatch)
    client = app.test_client()

    resp = client.post('/_beta', data={'password': 'letmein', 'next': '/clubs/'})

    assert resp.status_code == 302
    assert resp.headers['Location'] == '/clubs/'


def test_beta_gate_rejects_external_next_redirect(monkeypatch):
    app = _beta_app(monkeypatch)
    client = app.test_client()

    resp = client.post('/_beta', data={'password': 'letmein', 'next': 'https://evil.example/phish'})

    assert resp.status_code == 302
    assert resp.headers['Location'] == '/'
