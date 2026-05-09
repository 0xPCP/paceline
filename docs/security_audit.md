# Paceline — Security Audit

**Audited:** 2026-05-09  
**Auditor:** Claude Sonnet 4.6 (code review + live network tests against paceline.club)  
**Scope:** Full codebase + production deployment headers, TLS, and access control

---

## Live deployment findings

Tested via curl from the LAN (TrueNAS at 192.168.50.189) against https://paceline.club.

| Check | Result |
|---|---|
| HTTP → HTTPS redirect | PASS — 301 from Cloudflare |
| TLS version | PASS — TLSv1.3 / AES-256-GCM-SHA384 |
| Server fingerprint | PASS — header shows `cloudflare`, not gunicorn/Python |
| `/admin/` unauthenticated | PASS — 302 → `/auth/login?next=%2Fadmin%2F` |
| 404 error page | PASS — minimal Flask message, no stack trace |
| `X-Content-Type-Options` | PASS — `nosniff` |
| `X-Frame-Options` | PASS — `SAMEORIGIN` |
| `Referrer-Policy` | PASS — `strict-origin-when-cross-origin` |
| `Permissions-Policy` | PASS — camera/mic/geo blocked |
| `Content-Security-Policy` | PASS — nonce-gated scripts, RideWithGPS/YouTube/Vimeo frame allowlist |
| `Strict-Transport-Security` | PASS — `max-age=31536000; includeSubDomains` (added 2026-05-09) |
| Session cookie `Secure` flag | PASS — set via `COOKIE_SECURE=true` env var |
| Session cookie `HttpOnly` | PASS |
| Session cookie `SameSite` | PASS — `Lax` |

---

## Code audit findings

### Authentication & session management — PASS

- Passwords hashed with bcrypt (`app/routes/auth.py`)
- Session token versioning invalidates all sessions on password change or MFA toggle (`app/models.py:75-79`)
- 6-hour session freshness enforced on all admin operations (`app/__init__.py:124-178`)
- Google OAuth state validated with `secrets.compare_digest()` (`app/routes/auth.py:344`)
- TOTP MFA with bcrypt-hashed backup codes (`app/routes/auth.py:544-598`)
- `is_safe_url()` guards all `next=` redirect parameters

### CSRF — PASS

- `WTF_CSRF_ENABLED = True` globally (`app/config.py:12`)
- All POST forms use `FlaskForm` which includes the CSRF token
- Only `/_beta` is `@csrf.exempt` — acceptable (not session-modifying)

### Access control — PASS

- Four-level decorator stack: `@superadmin_required`, `@club_admin_required`, `@club_ride_admin_required`, `@club_content_required`
- All admin decorators call `_require_fresh_auth()` before proceeding
- Private club content gated at both the route and media proxy layers
- `is_active_member_of()` / `is_pending_member_of()` used consistently

### Input validation & XSS — PASS

- WTForms validators on all user inputs: email, length, regex, custom `SafeURL` validator
- `SafeURL` rejects `javascript:` and `data:` URIs (`app/security.py:12-27`)
- Video embeds whitelist-only: YouTube, Vimeo, Strava (`app/security.py:57-65`)
- Jinja2 autoescaping on all templates
- `mentionify` filter escapes text before linkifying `@mentions` (`app/utils.py:51-58`)
- File uploads: extension whitelist + Pillow `.verify()` as a second gate + UUID filenames

### SQL injection — PASS

- SQLAlchemy ORM used throughout; no raw string interpolation in queries
- `text()` wrapper used for DDL-only statements in `app/schema.py`

### File upload security — PASS

- Extensions: `{jpg, jpeg, png, webp}` only (`app/routes/media.py:38`)
- Pillow `.verify()` blocks polyglot attacks
- Max file size enforced via `MAX_CONTENT_LENGTH` (25 MB default)
- Images resized to 1200 px max width before storage
- Filenames are `uuid4().hex + ".jpg"` — no user input in path
- Upload count limits enforced per user per ride, and per ride total

### Secret management — PASS

- All secrets in environment variables, not committed to git
- App refuses to start with the dev-default `SECRET_KEY` when `SESSION_COOKIE_SECURE=true` (`app/__init__.py`) — added 2026-05-09
- `.env` is gitignored

### Cookie configuration — PASS

- `SESSION_COOKIE_SECURE`, `SESSION_COOKIE_HTTPONLY`, `SESSION_COOKIE_SAMESITE=Lax` all set
- `REMEMBER_COOKIE_*` mirrors the session cookie settings

---

## Issues found and fixed (2026-05-09)

### 1. No rate limiting on auth endpoints — FIXED

**Severity before fix:** HIGH  
**Affected routes:** `/auth/login`, `/auth/register`, `/auth/password-reset`  
**Fix:** Added Flask-Limiter 4.1.1 with per-IP limits:

| Endpoint | Limit |
|---|---|
| `/auth/login` | 20/min, 100/hr |
| `/auth/register` | 5/min, 20/hr |
| `/auth/password-reset` | 5/min, 10/hr |

Storage is in-memory per gunicorn worker. With 4 workers, effective burst before a block is up to 4× the per-worker limit. Acceptable for current scale. Upgrade to Redis-backed storage (`RATELIMIT_STORAGE_URI=redis://...`) if stricter enforcement is needed.

**Files changed:** `requirements.txt`, `app/extensions.py`, `app/routes/auth.py`

### 2. No startup guard on default SECRET_KEY — FIXED

**Severity before fix:** MEDIUM  
**Risk:** If `SECRET_KEY` env var was unset, the app would silently use the hardcoded dev default, making all session cookies forgeable.  
**Fix:** `create_app()` now raises `RuntimeError` if `SESSION_COOKIE_SECURE=true` and the key contains `dev` (`app/__init__.py`).

### 3. Missing HSTS header — FIXED

**Severity before fix:** LOW  
**Fix:** Added `Strict-Transport-Security: max-age=31536000; includeSubDomains` to `set_security_headers()` (`app/__init__.py`).  
**Note:** Cloudflare also enforces HTTPS, but defense-in-depth applies.

---

## Remaining low/info findings (accepted risks)

| Finding | Severity | Rationale for acceptance |
|---|---|---|
| `style-src 'unsafe-inline'` in CSP | LOW | Required for dynamic club themes (hex colors from DB, properly escaped) |
| Rate limits are per-worker, not global | LOW | Redis upgrade path documented above |
| `mentionify` doesn't validate `/users/` route exists | INFO | Dead links only, no security impact |
| Password reset token valid if same password re-set | INFO | Token TTL is 1 hour; low practical risk |

---

## Upgrade checklist for future Redis rate limiting

If brute-force protection needs exact cross-worker enforcement:

```bash
# Add to DO App Platform env vars:
RATELIMIT_STORAGE_URI=redis://:<password>@<host>:6379/0

# Add to requirements.txt:
redis==6.1.0

# No code changes needed — Flask-Limiter reads RATELIMIT_STORAGE_URI automatically
```

---

## Re-audit triggers

Run this audit again (or update this document) when:
- A new authentication flow is added
- File upload handling changes
- A new blueprint with admin-level routes is added
- Dependencies are upgraded (check CVEs)
- Infrastructure changes (proxy topology, new CDN layer)
