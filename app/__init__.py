import sys
import secrets
from datetime import datetime, timezone
from flask import Flask, request, session, redirect, url_for, flash, g
from flask_login import current_user, logout_user, login_fresh
from .config import Config
from .extensions import db, login_manager, bcrypt, csrf, mail, babel


SUPPORTED_LANGUAGES = ['en', 'fr', 'es', 'it', 'nl', 'de', 'pt']

LANGUAGE_NAMES = {
    'en': 'English',
    'fr': 'Français',
    'es': 'Español',
    'it': 'Italiano',
    'nl': 'Nederlands',
    'de': 'Deutsch',
    'pt': 'Português',
}


def get_locale():
    if current_user.is_authenticated and current_user.language:
        return current_user.language
    if current_user.is_authenticated:
        try:
            raw_id, _ = str(session.get('_user_id', '')).split(':', 1)
            from .models import User
            user = db.session.get(User, int(raw_id), populate_existing=True)
        except (TypeError, ValueError):
            user = None
        if user and user.language in SUPPORTED_LANGUAGES:
            return user.language
    return request.accept_languages.best_match(SUPPORTED_LANGUAGES, default='en')


def _strftime_filter(value, fmt):
    """Cross-platform strftime: replaces %-d/%-I (Linux) with %#d/%#I on Windows."""
    if sys.platform == 'win32':
        fmt = fmt.replace('%-', '%#')
    return value.strftime(fmt)


def _is_auth_timeout_exempt(endpoint):
    if not endpoint:
        return False
    return endpoint == 'static' or endpoint in {
        'auth.login',
        'auth.logout',
        'auth.register',
        'auth.setup_account',
    }


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    bcrypt.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    mail.init_app(app)
    babel.init_app(app, locale_selector=get_locale)

    from .routes.main import main_bp
    from .routes.auth import auth_bp
    from .routes.clubs import clubs_bp
    from .routes.admin import admin_bp
    from .routes.strava import strava_bp
    from .routes.api import api_bp
    from .routes.media import media_bp
    from .routes.user_rides import user_rides_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(clubs_bp, url_prefix='/clubs')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(strava_bp, url_prefix='/strava')
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(media_bp)
    app.register_blueprint(user_rides_bp, url_prefix='/my-rides')

    from .version import __version__
    from .utils import club_theme_vars

    app.jinja_env.globals['club_theme_vars'] = club_theme_vars
    app.jinja_env.filters['strftime'] = _strftime_filter

    @app.context_processor
    def inject_globals():
        from flask_babel import get_locale as _get_locale
        return {
            'now': datetime.now(timezone.utc),
            'version': __version__,
            'current_locale': str(_get_locale() or 'en'),
            'languages': LANGUAGE_NAMES,
            'google_oauth_enabled': bool(
                app.config.get('GOOGLE_OAUTH_CLIENT_ID')
                and app.config.get('GOOGLE_OAUTH_CLIENT_SECRET')
            ),
        }

    @app.before_request
    def set_csp_nonce():
        g.csp_nonce = secrets.token_urlsafe(16)

    @app.before_request
    def enforce_auth_age():
        if current_user.is_authenticated:
            raw_user_id = session.get('_user_id', '')
            try:
                raw_id, raw_version = str(raw_user_id).split(':', 1)
                user_id_int = int(raw_id)
                token_version = int(raw_version)
            except (TypeError, ValueError):
                token_version = None
                user_id_int = None

            if user_id_int is None:
                logout_user()
                return redirect(url_for('auth.login', next=request.full_path.rstrip('?')))

            from .models import User
            user = db.session.get(User, user_id_int, populate_existing=True)
            if user is None or user.session_token_version != token_version:
                logout_user()
                session.pop('_paceline_auth_started_at', None)
                session.pop('_paceline_trusted_browser', None)
                flash('Please sign in again to continue.', 'info')
                return redirect(url_for('auth.login', next=request.full_path.rstrip('?')))

        if (
            not current_user.is_authenticated
            or _is_auth_timeout_exempt(request.endpoint)
            or session.get('_paceline_trusted_browser')
            or not login_fresh()
        ):
            return None

        now_ts = datetime.now(timezone.utc).timestamp()
        started_at = session.get('_paceline_auth_started_at')
        if started_at is None:
            session['_paceline_auth_started_at'] = now_ts
            session.permanent = True
            return None

        max_age = app.config.get('AUTH_REAUTH_SECONDS', 6 * 60 * 60)
        try:
            expired = now_ts - float(started_at) > max_age
        except (TypeError, ValueError):
            expired = True

        if expired:
            logout_user()
            session.pop('_paceline_auth_started_at', None)
            session.pop('_paceline_trusted_browser', None)
            flash('Your session expired. Please sign in again.', 'info')
            return redirect(url_for('auth.login', next=request.full_path.rstrip('?')))
        return None

    @app.after_request
    def set_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = 'geolocation=(self), microphone=(), camera=()'
        # CSP: allow same-origin + Bootstrap/Google Fonts CDNs already in use
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            f"script-src 'self' 'nonce-{g.get('csp_nonce', '')}' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            "frame-src https://ridewithgps.com https://www.youtube.com https://player.vimeo.com; "
            "connect-src 'self';"
        )
        return response

    # Start weather auto-cancel scheduler (skipped in testing)
    if not app.config.get('TESTING'):
        from .scheduler import init_scheduler
        init_scheduler(app)

    return app
