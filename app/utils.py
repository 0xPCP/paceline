"""Shared utility helpers."""
import re
from urllib.parse import urlparse, urljoin
from flask import request as flask_request

_MENTION_RE = re.compile(r'@([A-Za-z0-9_]{2,50})')


def mentionify(text):
    """Jinja2 filter: linkify @username mentions while keeping body HTML-escaped."""
    from markupsafe import escape, Markup
    escaped = str(escape(text))
    def _replace(m):
        uname = m.group(1)
        return f'<a href="/users/{uname}" class="board-mention">@{uname}</a>'
    return Markup(_MENTION_RE.sub(_replace, escaped))


def is_safe_url(target):
    """Return True if *target* is a same-host relative URL, False otherwise.

    Prevents open-redirect attacks on `next` parameters and Referer-based
    redirects by ensuring the destination shares the request's host.
    """
    if not target:
        return False
    ref_url = urlparse(flask_request.host_url)
    test_url = urlparse(urljoin(flask_request.host_url, target))
    return (test_url.scheme in ('http', 'https') and
            ref_url.netloc == test_url.netloc)

_HEX_RE = re.compile(r'^#[0-9a-fA-F]{6}$')


def is_valid_hex(color):
    return bool(color and _HEX_RE.match(color))


def _clamp(v):
    return max(0, min(255, int(v)))


def _hex_to_rgb(h):
    h = h.lstrip('#')
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(r, g, b):
    return '#{:02x}{:02x}{:02x}'.format(_clamp(r), _clamp(g), _clamp(b))


def _mix_white(hex_color, amount):
    """Blend toward white. amount 0.0 = original, 1.0 = white."""
    r, g, b = _hex_to_rgb(hex_color)
    return _rgb_to_hex(r + (255 - r) * amount, g + (255 - g) * amount, b + (255 - b) * amount)


def _mix_black(hex_color, amount):
    """Blend toward black. amount 0.0 = original, 1.0 = black."""
    r, g, b = _hex_to_rgb(hex_color)
    return _rgb_to_hex(r * (1 - amount), g * (1 - amount), b * (1 - amount))


def club_theme_vars(club):
    """
    Return a dict of CSS custom property overrides for a club's theme.
    Keys are CSS variable names (e.g. '--paceline-green-dark'), values are hex strings.
    Returns an empty dict when no theme is set.
    """
    result = {}

    if club.theme_primary and is_valid_hex(club.theme_primary):
        p = club.theme_primary.lower()
        result['--paceline-primary']      = p
        result['--paceline-primary-pale'] = _mix_white(p, 0.90)   # nav, strips, tab bar
        result['--paceline-club-bg']      = _mix_white(p, 0.96)   # page background tint
        result['--paceline-green-dark']   = _mix_black(p, 0.30)
        result['--paceline-green']        = p
        result['--paceline-green-light']  = _mix_white(p, 0.38)
        result['--paceline-green-pale']   = _mix_white(p, 0.82)

    if club.theme_accent and is_valid_hex(club.theme_accent):
        a = club.theme_accent.lower()
        result['--paceline-orange']      = a
        result['--paceline-orange-dark'] = _mix_black(a, 0.15)

    return result
