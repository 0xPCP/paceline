import re
from urllib.parse import urlparse


STRAVA_ATHLETE_RE = re.compile(r'^/athletes/([0-9]+)/?$')


def canonical_strava_profile_url(value):
    value = (value or '').strip()
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in {'http', 'https'}:
        return None
    if parsed.netloc.lower() not in {'strava.com', 'www.strava.com'}:
        return None
    match = STRAVA_ATHLETE_RE.match(parsed.path)
    if not match:
        return None
    return f'https://www.strava.com/athletes/{match.group(1)}'


def strava_profile_athlete_id(value):
    canonical = canonical_strava_profile_url(value)
    if not canonical:
        return None
    return int(canonical.rsplit('/', 1)[1])
