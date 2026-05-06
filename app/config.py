import os
from datetime import timedelta


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        'postgresql://paceline:paceline@db:5432/paceline'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = True
    AUTH_REAUTH_SECONDS = int(os.environ.get('AUTH_REAUTH_HOURS', 6)) * 60 * 60
    PERMANENT_SESSION_LIFETIME = timedelta(seconds=AUTH_REAUTH_SECONDS)
    REMEMBER_COOKIE_DURATION = timedelta(days=int(os.environ.get('TRUSTED_BROWSER_DAYS', 30)))
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_SECURE = os.environ.get('COOKIE_SECURE', 'true').lower() == 'true'
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = os.environ.get('COOKIE_SECURE', 'true').lower() == 'true'

    # Strava
    STRAVA_CLIENT_ID = os.environ.get('STRAVA_CLIENT_ID')
    STRAVA_CLIENT_SECRET = os.environ.get('STRAVA_CLIENT_SECRET')
    STRAVA_CLUB_ID = os.environ.get('STRAVA_CLUB_ID')
    STRAVA_CLUB_REFRESH_TOKEN = os.environ.get('STRAVA_CLUB_REFRESH_TOKEN')

    # Email (Flask-Mail / SMTP)
    EMAIL_PROVIDER = os.environ.get('EMAIL_PROVIDER', '').strip().lower()
    RESEND_API_KEY = os.environ.get('RESEND_API_KEY', '').strip()
    RESEND_API_URL = os.environ.get('RESEND_API_URL', 'https://api.resend.com/emails').strip()
    RESEND_TIMEOUT_SECONDS = int(os.environ.get('RESEND_TIMEOUT_SECONDS', 10))
    RESEND_MAX_ATTEMPTS = int(os.environ.get('RESEND_MAX_ATTEMPTS', 3))
    RESEND_RETRY_BACKOFF_SECONDS = tuple(
        int(value.strip())
        for value in os.environ.get('RESEND_RETRY_BACKOFF_SECONDS', '2,5,15').split(',')
        if value.strip()
    )
    EMAIL_RECIPIENT_OVERRIDE = os.environ.get('EMAIL_RECIPIENT_OVERRIDE', '').strip()
    MAIL_SERVER   = os.environ.get('MAIL_SERVER', '')
    MAIL_PORT     = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS  = os.environ.get('MAIL_USE_TLS', 'true').lower() == 'true'
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME', '')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD', '')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', 'Paceline <noreply@paceline.club>')
    MAIL_SUPPRESS_SEND = not bool(RESEND_API_KEY or os.environ.get('MAIL_SERVER', ''))

    # Internationalisation
    BABEL_DEFAULT_LOCALE = 'en'
    BABEL_DEFAULT_TIMEZONE = 'UTC'

    # Hosted donation page. Set DONATE_URL='' in tests/local config to show the
    # coming-soon stub instead.
    DONATE_URL = (
        os.environ.get('DONATE_URL')
        or 'https://buy.stripe.com/dRm7sFgkK2yb8VwgrZ9AA00'
    ).strip()

    # Comma-separated email allowlist for platform superadmins. These accounts
    # are promoted on startup and cannot have superadmin access revoked in-app.
    SUPERADMIN_EMAILS = os.environ.get('SUPERADMIN_EMAILS', 'phil@pcp.dev')

    # Dormant multi-sport support. Keep false until running-club UI/filtering ships.
    MULTISPORT_UI_ENABLED = os.environ.get('MULTISPORT_UI_ENABLED', 'false').lower() == 'true'

    # Media uploads — see docs/media_strategy.md for rationale and update guidance
    UPLOAD_FOLDER = os.environ.get(
        'UPLOAD_FOLDER',
        os.path.join(os.path.dirname(__file__), '..', 'uploads'),
    )
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024          # 5 MB hard Flask limit (pre-Pillow)
    MEDIA_EXPIRY_DAYS = int(os.environ.get('MEDIA_EXPIRY_DAYS', 90))
    MEDIA_MAX_PHOTOS_PER_USER_RIDE = int(os.environ.get('MEDIA_MAX_PHOTOS_PER_USER_RIDE', 5))
    MEDIA_MAX_PHOTOS_PER_RIDE = int(os.environ.get('MEDIA_MAX_PHOTOS_PER_RIDE', 30))
    MEDIA_MAX_WIDTH_PX = int(os.environ.get('MEDIA_MAX_WIDTH_PX', 1200))
    STORAGE_WARNING_PERCENT = int(os.environ.get('STORAGE_WARNING_PERCENT', 80))
    STORAGE_CRITICAL_PERCENT = int(os.environ.get('STORAGE_CRITICAL_PERCENT', 90))
    MEDIA_STORAGE_WARNING_MB = int(os.environ.get('MEDIA_STORAGE_WARNING_MB', 1024))
    ADMIN_DASHBOARD_SLOW_MS = int(os.environ.get('ADMIN_DASHBOARD_SLOW_MS', 1500))
