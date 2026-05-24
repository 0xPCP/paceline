import re
import sys
import os
import logging
import secrets
import warnings
from datetime import datetime, timezone
from flask import Flask, request, session, redirect, url_for, flash, g, has_request_context
from flask_login import current_user, logout_user, login_fresh
from markupsafe import Markup, escape
from werkzeug.middleware.proxy_fix import ProxyFix
from .config import Config
from .extensions import db, migrate, login_manager, bcrypt, csrf, mail, babel, limiter


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
    if not has_request_context():
        return 'en'
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


def _markdown_filter(text):
    """Render markdown text to safe HTML. HTML tags in the source are escaped."""
    if not text:
        return Markup('')
    try:
        import mistune
    except ModuleNotFoundError:
        return Markup('<br>'.join(str(escape(text)).splitlines()))
    md = mistune.create_markdown(escape=True)
    return Markup(md(text))


_STRIP_MD = re.compile(
    r'#{1,6}\s*'        # ATX headings: ## Heading
    r'|[*_]{1,3}'       # bold/italic: ** __ * _
    r'|~~'              # strikethrough
    r'|`{1,3}'          # inline/fenced code
    r'|\[([^\]]*)\]\([^)]*\)'  # [link text](url) → link text
    r'|!\[[^\]]*\]\([^)]*\)'   # images
    r'|^[-*+]\s+'       # unordered list bullets
    r'|^\d+\.\s+'       # ordered list bullets
    r'|^>\s*',          # blockquotes
    re.MULTILINE,
)


def _strip_markdown_filter(text):
    """Strip common markdown syntax for use in plain-text previews."""
    if not text:
        return ''
    cleaned = _STRIP_MD.sub(r'\1', text)
    return re.sub(r'\n+', ' ', cleaned).strip()


def _dist_filter(miles, precision=1):
    """Convert a distance in miles to the user-preferred unit string (e.g. '42.5 mi' or '68.4 km')."""
    from flask import g, has_request_context
    if miles is None:
        return ''
    unit = g.get('distance_unit', 'km') if has_request_context() else 'mi'
    if unit == 'mi':
        val = float(miles)
        suffix = 'mi'
    else:
        val = float(miles) * 1.60934
        suffix = 'km'
    if precision == 0:
        return f'{val:,.0f} {suffix}'
    return f'{round(val, precision)} {suffix}'


def _elev_filter(feet):
    """Convert an elevation in feet to the user-preferred unit string (e.g. '2,500 ft' or '762 m')."""
    from flask import g, has_request_context
    if feet is None:
        return ''
    unit = g.get('distance_unit', 'km') if has_request_context() else 'mi'
    if unit == 'mi':
        return f'{int(feet):,} ft'
    meters = round(float(feet) * 0.3048)
    return f'{meters:,} m'


_PACE_LABELS_KM = {
    'A': 'A — Fast (35+ km/h)',
    'B': 'B — Moderate (29–35 km/h)',
    'C': 'C — Casual (22–29 km/h)',
    'D': 'D — Beginner (<22 km/h)',
}


def _pace_filter(pace_label):
    """Return the pace label in the user-preferred speed unit (mph or km/h)."""
    from flask import g, has_request_context
    if not pace_label:
        return pace_label
    if not has_request_context() or g.get('distance_unit', 'km') != 'km':
        return pace_label
    cat = pace_label[0]
    return _PACE_LABELS_KM.get(cat, pace_label)


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
        'auth.password_reset_request',
        'auth.password_reset',
    }


def _is_username_setup_exempt(endpoint):
    return endpoint == 'static' or endpoint in {
        'auth.username_setup',
        'auth.logout',
    }


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # Route Python logging to stdout so gunicorn/DO captures it alongside access logs
    if not app.debug:
        logging.basicConfig(
            stream=sys.stdout,
            level=logging.INFO,
            format='%(asctime)s %(levelname)s %(name)s: %(message)s',
        )

    # Refuse to start with the dev fallback key when cookies are in secure
    # mode — that combination means we're running in a production-like env.
    if app.config.get('SESSION_COOKIE_SECURE') and 'dev' in app.config['SECRET_KEY'].lower():
        raise RuntimeError(
            'SECRET_KEY is set to the development default but SESSION_COOKIE_SECURE '
            'is True. Set a strong SECRET_KEY environment variable before deploying.'
        )

    db.init_app(app)
    migrate.init_app(app, db)
    bcrypt.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    mail.init_app(app)
    babel.init_app(app, locale_selector=get_locale)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        limiter.init_app(app)

    from .routes.main import main_bp
    from .routes.auth import auth_bp
    from .routes.clubs import clubs_bp
    from .routes.admin import admin_bp
    from .routes.strava import strava_bp
    from .routes.api import api_bp
    from .routes.media import media_bp
    from .routes.user_rides import user_rides_bp
    from .routes.board import board_bp
    from .routes.stripe_connect import stripe_connect_bp
    from .routes.virtual import virtual_bp
    from .routes.friends import friends_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(clubs_bp, url_prefix='/clubs')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(strava_bp, url_prefix='/strava')
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(media_bp)
    app.register_blueprint(user_rides_bp, url_prefix='/my-rides')
    app.register_blueprint(board_bp)
    app.register_blueprint(stripe_connect_bp, url_prefix='/stripe')
    app.register_blueprint(virtual_bp, url_prefix='/virtual')
    app.register_blueprint(friends_bp)

    from .version import __version__
    from .utils import club_theme_vars, mentionify

    app.jinja_env.globals['club_theme_vars'] = club_theme_vars
    app.jinja_env.filters['strftime'] = _strftime_filter
    app.jinja_env.filters['mentionify'] = mentionify
    app.jinja_env.filters['markdown'] = _markdown_filter
    app.jinja_env.filters['strip_markdown'] = _strip_markdown_filter
    app.jinja_env.filters['dist'] = _dist_filter
    app.jinja_env.filters['elev'] = _elev_filter
    app.jinja_env.filters['pace'] = _pace_filter

    @app.context_processor
    def inject_globals():
        from flask_babel import get_locale as _get_locale
        return {
            'now': datetime.now(timezone.utc),
            'version': __version__,
            'current_locale': str(_get_locale() or 'en'),
            'languages': LANGUAGE_NAMES,
            'distance_unit': g.get('distance_unit', 'km'),
            'google_oauth_enabled': bool(
                app.config.get('GOOGLE_OAUTH_CLIENT_ID')
                and app.config.get('GOOGLE_OAUTH_CLIENT_SECRET')
            ),
        }

    @app.before_request
    def set_distance_unit():
        unit = current_user.distance_unit if current_user.is_authenticated else None
        if unit not in ('mi', 'km'):
            # Auto-detect: 5-digit numeric zip → US → miles, everything else → km
            zip_code = current_user.zip_code if current_user.is_authenticated else None
            unit = 'mi' if (zip_code and zip_code.isdigit() and len(zip_code) == 5) else 'km'
        g.distance_unit = unit

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
            if not user.username_finalized and not _is_username_setup_exempt(request.endpoint):
                return redirect(url_for('auth.username_setup'))

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
        if request.endpoint == 'clubs.embed':
            # Embed widget must be iframeable by any external site
            response.headers.pop('X-Frame-Options', None)
        else:
            response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = 'geolocation=(self), microphone=(), camera=()'
        # CSP: allow same-origin + Bootstrap/Google Fonts CDNs already in use
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            f"script-src 'self' 'nonce-{g.get('csp_nonce', '')}' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            "frame-src 'self' https://ridewithgps.com https://www.youtube.com https://player.vimeo.com; "
            "connect-src 'self';"
        )
        return response

    # Start weather auto-cancel scheduler (skipped in testing)
    if not app.config.get('TESTING') and not os.environ.get('FLASK_SKIP_SCHEDULER'):
        from .scheduler import init_scheduler
        init_scheduler(app)

    from flask import render_template as _render_template
    from werkzeug.exceptions import HTTPException
    import traceback as _traceback

    def _log_error(status_code, exc=None):
        """Write an error record to app_error_logs. Never raises."""
        try:
            from .models import AppErrorLog
            tb = _traceback.format_exc() if exc else None
            if tb and tb.strip() == 'NoneType: None':
                tb = None
            user_id = None
            try:
                from flask_login import current_user as _cu
                if _cu.is_authenticated:
                    user_id = _cu.id
            except Exception:
                pass
            entry = AppErrorLog(
                status_code=status_code,
                method=request.method if has_request_context() else None,
                path=request.path if has_request_context() else None,
                error_type=type(exc).__name__ if exc else None,
                error_message=str(exc) if exc else None,
                traceback=tb,
                user_id=user_id,
            )
            db.session.add(entry)
            db.session.commit()
        except Exception:
            pass

    @app.errorhandler(404)
    def not_found(e):
        _log_error(404, e)
        return _render_template('404.html'), 404

    @app.errorhandler(500)
    def internal_error(e):
        _log_error(500, e)
        try:
            return _render_template('500.html'), 500
        except Exception:
            return '<h1>500 Internal Server Error</h1>', 500

    @app.errorhandler(Exception)
    def unhandled_exception(e):
        if isinstance(e, HTTPException):
            return e
        app.logger.exception('Unhandled exception on %s %s', request.method, request.path)
        _log_error(500, e)
        try:
            return _render_template('500.html'), 500
        except Exception:
            return '<h1>500 Internal Server Error</h1>', 500

    return app
