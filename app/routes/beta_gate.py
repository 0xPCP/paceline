"""
Beta-access password gate — wraps the entire site behind a single password.

To enable:  set BETA_PASSWORD=<secret> in .env
To disable: remove BETA_PASSWORD from .env  (no code change needed)
To remove permanently: delete this file and the register_beta_gate() call in app/__init__.py
"""
import os
from flask import request, session, redirect, url_for, render_template_string

_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Paceline — Beta Access</title>
  <link rel="stylesheet"
        href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"
        crossorigin="anonymous">
  <style>
    body { background: #f0f4f1; }
    .gate-card { max-width: 380px; margin: 20vh auto 0; }
  </style>
</head>
<body>
<div class="gate-card card shadow-sm p-4 border-0">
  <h5 class="fw-semibold mb-1">Paceline Beta</h5>
  <p class="text-muted small mb-3">Enter the beta access password to continue.</p>
  {% if error %}
  <div class="alert alert-danger py-2 small mb-3">{{ error }}</div>
  {% endif %}
  <form method="post" action="/_beta">
    <input type="hidden" name="next" value="{{ next_url }}">
    <div class="mb-3">
      <input type="password" name="password" class="form-control"
             placeholder="Password" autofocus autocomplete="current-password">
    </div>
    <button type="submit" class="btn btn-success w-100">Enter</button>
  </form>
</div>
</body>
</html>"""


def register_beta_gate(app):
    if app.config.get('TESTING'):
        return  # never gate during test runs
    password = os.environ.get('BETA_PASSWORD', '').strip()
    if not password:
        return  # gate is disabled — nothing registered

    from ..extensions import csrf

    @app.before_request
    def _beta_gate():
        if request.endpoint in (None, '_beta_login', 'static', 'main.health'):
            return
        if session.get('_beta_ok'):
            return
        return redirect(url_for('_beta_login', next=request.path))

    @app.route('/_beta', methods=['GET', 'POST'], endpoint='_beta_login')
    @csrf.exempt
    def _beta_login():
        next_url = request.args.get('next') or request.form.get('next') or '/'
        if request.method == 'POST':
            if request.form.get('password') == password:
                session['_beta_ok'] = True
                session.permanent = True
                return redirect(next_url)
            return render_template_string(_PAGE, error='Wrong password — try again.', next_url=next_url)
        return render_template_string(_PAGE, error=None, next_url=next_url)
