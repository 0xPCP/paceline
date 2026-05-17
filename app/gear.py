"""
Cycling gear recommendations based on current weather conditions.
Ported from weatherapp — uses the same gear catalog, pickFirst() logic,
and two-temperature model.

Two-temperature model
---------------------
Extremities (hands, feet, head) feel the START temperature — they warm up
slowly and are often exposed to wind.  The core warms quickly during effort,
so we offset the ambient feels-like by the rider's heat output.  The offset
scales with pace category, because a 300-watt A-pace effort generates roughly
twice the body heat of an easy D-pace spin.

owned_ids: set of gear item IDs the user owns. If None, returns ideal items
           regardless of inventory (used when no inventory is configured).
"""

_RAIN_CODES = {51, 53, 55, 61, 63, 65, 80, 81, 82, 85, 86, 95, 96, 99}
_SNOW_CODES = {71, 73, 75, 77, 85, 86}

# Body-heat offset by pace category.
# Based on approximate watt output: A ≈ 300W, B ≈ 200W, C ≈ 140W, D ≈ 100W.
# Each ~50W above resting raises perceived core temp by roughly 3-4°F.
_PACE_HEAT_OFFSET = {
    'A': 20,   # 22+ mph / threshold — lots of heat, very wind-exposed
    'B': 15,   # 18–22 mph / moderate aerobic effort
    'C': 10,   # 14–18 mph / conversational
    'D':  8,   # <14 mph / easy/beginner
}
_DEFAULT_HEAT_OFFSET = 12   # fallback when pace unknown

# Estimated average moving speed for duration calculation
_PACE_MPH = {'A': 24, 'B': 20, 'C': 16, 'D': 13}

# Pace-specific cold thresholds.  Fit riders in proper kit tolerate more cold;
# beginners in recreational gear genuinely cannot and should stay home.
_COLD_SKIP =     {'A': 18, 'B': 22, 'C': 28, 'D': 32}
_COLD_MARGINAL = {'A': 26, 'B': 30, 'C': 36, 'D': 40}
_WIND_SKIP =     {'A': 38, 'B': 33, 'C': 28, 'D': 24}
_WIND_MARGINAL = {'A': 26, 'B': 22, 'C': 18, 'D': 15}

# ── Gear catalog ──────────────────────────────────────────────────────────────
# Ordered warm→cold within each category.

GEAR_CATALOG = {
    'Bottoms': [
        {'id': 'bib-shorts',         'label': 'Bib shorts'},
        {'id': 'bib-knickers',       'label': 'Bib knickers'},
        {'id': 'bib-tights',         'label': 'Bib tights'},
        {'id': 'thermal-bib-tights', 'label': 'Thermal bib tights'},
    ],
    'Base Layers': [
        {'id': 'base-light',   'label': 'Light base layer'},
        {'id': 'base-mid',     'label': 'Mid-weight base layer'},
        {'id': 'base-thermal', 'label': 'Thermal base layer'},
        {'id': 'base-heavy',   'label': 'Heavy base layer'},
    ],
    'Jersey': [
        {'id': 'jersey-light',   'label': 'Lightweight jersey'},
        {'id': 'jersey',         'label': 'Regular jersey'},
        {'id': 'jersey-ls',      'label': 'Long-sleeve jersey'},
        {'id': 'jersey-thermal', 'label': 'Thermal long-sleeve jersey'},
    ],
    'Warmers': [
        {'id': 'sun-sleeves',  'label': 'Sun sleeves'},
        {'id': 'arm-warmers',  'label': 'Arm warmers'},
        {'id': 'knee-warmers', 'label': 'Knee warmers'},
        {'id': 'leg-warmers',  'label': 'Leg warmers'},
    ],
    'Outerwear': [
        {'id': 'wind-vest',        'label': 'Wind vest'},
        {'id': 'wind-jacket',      'label': 'Wind jacket'},
        {'id': 'rain-jacket',      'label': 'Rain jacket'},
        {'id': 'jacket',           'label': 'Cycling jacket'},
        {'id': 'insulated-jacket', 'label': 'Insulated jacket'},
    ],
    'Gloves': [
        {'id': 'gloves-fingerless', 'label': 'Fingerless gloves'},
        {'id': 'gloves-light',      'label': 'Light gloves'},
        {'id': 'gloves-medium',     'label': 'Medium gloves'},
        {'id': 'gloves-full',       'label': 'Full-finger gloves'},
        {'id': 'gloves-warm',       'label': 'Warm winter gloves'},
    ],
    'Head & Neck': [
        {'id': 'cycling-cap',  'label': 'Cycling cap'},
        {'id': 'ear-covers',   'label': 'Ear covers'},
        {'id': 'skull-cap',    'label': 'Skull cap'},
        {'id': 'neck-gaiter',  'label': 'Neck gaiter'},
        {'id': 'helmet-cover', 'label': 'Helmet cover'},
        {'id': 'balaclava',    'label': 'Balaclava'},
    ],
    'Feet': [
        {'id': 'shoe-covers',       'label': 'Shoe covers'},
        {'id': 'booties',           'label': 'Booties'},
        {'id': 'insulated-booties', 'label': 'Insulated booties'},
    ],
    'Eyewear': [
        {'id': 'sunglasses',   'label': 'Sunglasses'},
        {'id': 'clear-lenses', 'label': 'Clear lenses'},
    ],
}

# Flat id→label lookup
_LABEL = {item['id']: item['label']
          for items in GEAR_CATALOG.values() for item in items}

ALL_ITEM_IDS = list(_LABEL.keys())


def _pick(owned, *ids):
    """
    Return the label of the first item from `ids` that the user owns.
    If owned is None (no inventory configured) return the first item unconditionally.
    Returns None if the user owns none of the listed items.
    """
    for item_id in ids:
        if owned is None or item_id in owned:
            return _LABEL[item_id]
    return None


def estimate_duration(distance_miles, pace_category):
    """Estimate ride duration in hours from distance and pace category."""
    if not distance_miles or distance_miles <= 0:
        return None
    mph = _PACE_MPH.get((pace_category or '').upper(), 18)
    return round(distance_miles / mph, 2)


# ── Main recommendation function ──────────────────────────────────────────────

def cycling_gear(temp_f: float, feels_like_f: float, wind_mph: float,
                 precip_prob: int, weather_code: int,
                 owned_ids=None,
                 pace_category: str | None = None,
                 duration_hours: float | None = None,
                 end_temp_f: float | None = None) -> dict:
    """
    Return gear recommendations filtered to items the user owns.

    owned_ids:      collection of gear item IDs the user owns, or None to
                    ignore inventory and always return the ideal item.
    pace_category:  'A'|'B'|'C'|'D' — adjusts core-temp offset and verdict
                    thresholds.  None uses a neutral default.
    duration_hours: estimated ride length — drives long-ride notes and
                    temperature-arc warnings.
    end_temp_f:     forecast temperature at ride end — used for arc notes.
    """
    owned = set(owned_ids) if owned_ids is not None else None
    pace  = (pace_category or '').upper() or None

    heat_offset = _PACE_HEAT_OFFSET.get(pace, _DEFAULT_HEAT_OFFSET)
    core_fl  = feels_like_f + heat_offset  # body temp during sustained effort
    start_fl = feels_like_f                 # extremities feel the ambient temp

    raining  = weather_code in _RAIN_CODES and precip_prob >= 30
    snow     = weather_code in _SNOW_CODES
    long_ride = duration_hours is not None and duration_hours >= 2.5

    # ── Verdict ───────────────────────────────────────────────────────────────
    cold_skip     = _COLD_SKIP.get(pace, 25)
    cold_marginal = _COLD_MARGINAL.get(pace, 33)
    wind_skip     = _WIND_SKIP.get(pace, 33)
    wind_marginal = _WIND_MARGINAL.get(pace, 22)

    if snow or temp_f < cold_skip or precip_prob >= 70 or wind_mph >= wind_skip:
        verdict = 'skip'
    elif (temp_f < cold_marginal or precip_prob >= 45
          or wind_mph >= wind_marginal or raining):
        verdict = 'marginal'
    elif (precip_prob <= 10 and wind_mph <= 12
          and 58 <= feels_like_f <= 82):
        verdict = 'great'
    else:
        verdict = 'go'

    # ── Bottoms ───────────────────────────────────────────────────────────────
    if core_fl >= 68:
        bottoms = _pick(owned, 'bib-shorts', 'bib-knickers', 'bib-tights', 'thermal-bib-tights')
    elif core_fl >= 55:
        bottoms = _pick(owned, 'bib-knickers', 'bib-tights', 'bib-shorts', 'thermal-bib-tights')
    elif core_fl >= 42:
        bottoms = _pick(owned, 'bib-tights', 'thermal-bib-tights', 'bib-knickers')
    else:
        bottoms = _pick(owned, 'thermal-bib-tights', 'bib-tights', 'bib-knickers')

    # ── Jersey ────────────────────────────────────────────────────────────────
    if core_fl >= 75:
        jersey = _pick(owned, 'jersey-light', 'jersey', 'jersey-ls', 'jersey-thermal')
    elif core_fl >= 62:
        jersey = _pick(owned, 'jersey', 'jersey-light', 'jersey-ls', 'jersey-thermal')
    elif core_fl >= 48:
        jersey = _pick(owned, 'jersey-ls', 'jersey-thermal', 'jersey', 'jersey-light')
    else:
        jersey = _pick(owned, 'jersey-thermal', 'jersey-ls', 'jersey', 'jersey-light')

    # ── Base layer ────────────────────────────────────────────────────────────
    if core_fl < 38:
        base_layer = _pick(owned, 'base-heavy', 'base-thermal', 'base-mid', 'base-light')
    elif core_fl < 50:
        base_layer = _pick(owned, 'base-thermal', 'base-mid', 'base-heavy', 'base-light')
    elif core_fl < 62:
        base_layer = _pick(owned, 'base-mid', 'base-light', 'base-thermal')
    else:
        base_layer = None

    # ── Warmers (arm/knee/leg) ────────────────────────────────────────────────
    warmers = []
    if 50 <= core_fl < 65:
        w = _pick(owned, 'arm-warmers')
        if w:
            warmers.append(w)
    if 45 <= core_fl < 55:
        w = _pick(owned, 'knee-warmers', 'leg-warmers')
        if w:
            warmers.append(w)
    if core_fl < 45:
        w = _pick(owned, 'leg-warmers', 'knee-warmers')
        if w:
            warmers.append(w)

    # Sun sleeves — hot, sunny, long rides: UV protection without adding heat
    sun_sleeves = None
    if temp_f >= 75 and weather_code <= 2 and long_ride:
        sun_sleeves = _pick(owned, 'sun-sleeves')

    # ── Outerwear ─────────────────────────────────────────────────────────────
    if raining:
        outer = _pick(owned, 'rain-jacket', 'jacket', 'wind-jacket', 'insulated-jacket')
    elif start_fl < 28:
        outer = _pick(owned, 'insulated-jacket', 'jacket', 'wind-jacket')
    elif start_fl < 45:
        outer = _pick(owned, 'jacket', 'wind-jacket', 'insulated-jacket')
    elif wind_mph >= 20 and start_fl < 62:
        outer = _pick(owned, 'wind-vest', 'wind-jacket', 'jacket')
    elif start_fl < 58:
        outer = _pick(owned, 'wind-vest', 'wind-jacket')
    else:
        outer = None

    # ── Gloves ────────────────────────────────────────────────────────────────
    if start_fl < 25:
        gloves = _pick(owned, 'gloves-warm', 'gloves-full', 'gloves-medium')
    elif start_fl < 38:
        gloves = _pick(owned, 'gloves-full', 'gloves-warm', 'gloves-medium', 'gloves-light')
    elif start_fl < 50:
        gloves = _pick(owned, 'gloves-medium', 'gloves-full', 'gloves-light', 'gloves-fingerless')
    elif start_fl < 62:
        gloves = _pick(owned, 'gloves-light', 'gloves-medium', 'gloves-fingerless')
    elif start_fl < 72:
        gloves = _pick(owned, 'gloves-fingerless', 'gloves-light')
    else:
        gloves = None

    # ── Head & neck ───────────────────────────────────────────────────────────
    if start_fl < 22:
        head = _pick(owned, 'balaclava', 'neck-gaiter', 'skull-cap', 'helmet-cover')
    elif start_fl < 35:
        head = _pick(owned, 'skull-cap', 'balaclava', 'ear-covers', 'helmet-cover')
    elif start_fl < 48:
        head = _pick(owned, 'ear-covers', 'skull-cap', 'cycling-cap', 'helmet-cover')
    elif start_fl < 60:
        # Cool enough at the start that a cap helps; ears don't need full covers
        head = _pick(owned, 'cycling-cap', 'ear-covers')
    elif weather_code in {51, 53}:
        # Light drizzle — cap bill keeps rain off the face and glasses
        head = _pick(owned, 'cycling-cap')
    elif temp_f >= 75 and weather_code <= 2 and long_ride:
        # Hot and sunny long ride — cap as a sun visor
        head = _pick(owned, 'cycling-cap')
    else:
        head = None

    # ── Feet ──────────────────────────────────────────────────────────────────
    if start_fl < 22:
        feet = _pick(owned, 'insulated-booties', 'booties', 'shoe-covers')
    elif start_fl < 38:
        feet = _pick(owned, 'booties', 'insulated-booties', 'shoe-covers')
    elif start_fl < 56:
        feet = _pick(owned, 'shoe-covers', 'booties', 'insulated-booties')
    else:
        feet = None

    # ── Eyewear ───────────────────────────────────────────────────────────────
    if weather_code <= 1 and temp_f >= 55:
        eyewear = _pick(owned, 'sunglasses', 'clear-lenses')
    elif weather_code >= 61 or weather_code == 45:
        eyewear = _pick(owned, 'clear-lenses', 'sunglasses')
    else:
        eyewear = None

    # ── Notes — long-ride and temperature-arc warnings ────────────────────────
    notes = []

    if duration_hours is not None and duration_hours >= 3:
        if end_temp_f is not None:
            delta = end_temp_f - temp_f
            if delta >= 15:
                notes.append(
                    f'Temperature rises ~{int(delta)}°F during the ride — '
                    'start with a layer you can remove and stash in a pocket.'
                )
            elif delta <= -12:
                notes.append(
                    f'Temperature drops ~{int(abs(delta))}°F during the ride — '
                    'pack an extra layer for the last hour.'
                )
        if 25 <= precip_prob < 45 and not raining:
            notes.append(
                'Long ride with some rain chance — stuff a rain jacket in your '
                'back pocket just in case.'
            )

    elif 30 <= precip_prob < 45 and not raining:
        notes.append(
            f'{precip_prob}% chance of rain — consider tucking a rain jacket '
            'into your jersey pocket.'
        )

    return {
        'verdict':       verdict,
        'bottoms':       bottoms,
        'jersey':        jersey,
        'base_layer':    base_layer,
        'warmers':       warmers,
        'sun_sleeves':   sun_sleeves,
        'outer':         outer,
        'gloves':        gloves,
        'head':          head,
        'feet':          feet,
        'eyewear':       eyewear,
        'notes':         notes,
        'pace_category': pace,
        'duration_hours': duration_hours,
        'end_temp_f':    end_temp_f,
    }


VERDICT_LABEL = {
    'great':    ('Great day to ride!',      'success'),
    'go':       ('Good to go.',             'primary'),
    'marginal': ('Rideable — dress right.', 'warning'),
    'skip':     ('Consider skipping.',      'danger'),
}

# Gear item → display icon (for the widget)
ITEM_ICONS = {
    'Bottoms':    '🩳',
    'Jersey':     '👕',
    'Base Layers':'🧥',
    'Warmers':    '💪',
    'Outerwear':  '🧥',
    'Gloves':     '🧤',
    'Head & Neck':'🧢',
    'Feet':       '👟',
    'Eyewear':    '🕶️',
}
