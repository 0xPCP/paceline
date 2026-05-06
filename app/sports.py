SUPPORTED_SPORTS = ('cycling', 'running')
DEFAULT_SPORT = 'cycling'


def normalize_sport(value):
    value = (value or '').strip().lower()
    if value in SUPPORTED_SPORTS:
        return value
    return DEFAULT_SPORT


def normalize_sport_preferences(values):
    if not values:
        return [DEFAULT_SPORT]
    if isinstance(values, str):
        values = [values]
    normalized = []
    for value in values:
        sport = normalize_sport(value)
        if sport not in normalized:
            normalized.append(sport)
    return normalized or [DEFAULT_SPORT]
