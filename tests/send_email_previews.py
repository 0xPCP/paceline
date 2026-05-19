"""
Sends one example of every email template to a specified address.

Usage:
    python tests/send_email_previews.py phil@pcp.dev
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Load .env
from dotenv import load_dotenv
load_dotenv(ROOT / '.env')

RECIPIENT = sys.argv[1] if len(sys.argv) > 1 else 'phil@pcp.dev'

# Re-use fake data factory from screenshot script
sys.path.insert(0, str(ROOT / 'tests'))
from screenshot_emails import (
    _club, _user, _ride, _post, _invite, _transfer, _feedback, _signup,
    screenshots as _template_list,
)

# ── Flask app with real Resend config ─────────────────────────────────────────
from app import create_app
from app.email import _send

class _Cfg:
    TESTING           = False
    WTF_CSRF_ENABLED  = False
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY        = os.environ['SECRET_KEY']
    EMAIL_PROVIDER    = os.environ.get('EMAIL_PROVIDER', 'resend')
    RESEND_API_KEY    = os.environ['RESEND_API_KEY']
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', 'Paceline <noreply@paceline.club>')
    SERVER_NAME       = 'localhost'
    PREFERRED_URL_SCHEME = 'http'
    SPACES_PUBLIC_BASE_URL = ''

app = create_app(_Cfg)

# ── Send ───────────────────────────────────────────────────────────────────────
def main():
    print(f'Sending {17} email previews to {RECIPIENT}...\n')
    from flask import render_template

    with app.test_request_context('/'):
        for _filename, slug, render_fn in _template_list():
            try:
                html = render_fn()
                subject = f'[Preview] {slug.replace("_", " ").title()} — Paceline email template'
                ok = _send(subject, [RECIPIENT], html)
                status = '✓ sent' if ok else '✗ failed (check logs)'
                print(f'  {status}  {slug}')
            except Exception as exc:
                print(f'  ✗ error  {slug}: {exc}')

    print(f'\nDone. Check {RECIPIENT}')

if __name__ == '__main__':
    main()
