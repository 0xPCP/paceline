"""
Seed extra demo data on production: bikes and profile photos for demo riders.
Run locally against production DB. Reads credentials from .env or environment.

Usage:
    python seed_demo_extras.py
"""
import io
import os
import urllib.request
from PIL import Image
import boto3
import psycopg2

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DB_URL = os.environ['DATABASE_URL']

SPACES_BUCKET   = os.environ.get('SPACES_BUCKET', 'paceline-media')
SPACES_REGION   = os.environ.get('SPACES_REGION', 'nyc3')
SPACES_ENDPOINT = os.environ.get('SPACES_ENDPOINT', 'https://nyc3.digitaloceanspaces.com')
SPACES_KEY      = os.environ['SPACES_ACCESS_KEY']
SPACES_SECRET   = os.environ['SPACES_SECRET_KEY']

# pravatar.cc images for each demo rider (distinct, cycling-plausible)
DEMO_PHOTOS = {
    'alex_demo':   'https://i.pravatar.cc/400?img=11',   # male, athletic look
    'jordan_demo': 'https://i.pravatar.cc/400?img=15',   # male, casual
    'casey_demo':  'https://i.pravatar.cc/400?img=47',   # female, friendly
    'riley_demo':  'https://i.pravatar.cc/400?img=49',   # female, outdoorsy
}

# Bikes for each demo rider
DEMO_BIKES = {
    'alex_demo': [
        dict(make_model='Trek Domane SL 6', nickname='The Commuter', bike_type='road', is_primary=True,  display_order=0),
        dict(make_model='Salsa Warbird', nickname=None,               bike_type='gravel', is_primary=False, display_order=1),
    ],
    'jordan_demo': [
        dict(make_model='Specialized Diverge Comp', nickname='Gravelicious', bike_type='gravel', is_primary=True,  display_order=0),
        dict(make_model='Giant Propel Advanced',    nickname='Race Day',     bike_type='road',   is_primary=False, display_order=1),
    ],
    'casey_demo': [
        dict(make_model='Cannondale Synapse 105', nickname=None,       bike_type='road',    is_primary=True,  display_order=0),
        dict(make_model='Trek Marlin 6',          nickname='The Beast', bike_type='mtb',    is_primary=False, display_order=1),
    ],
    'riley_demo': [
        dict(make_model='Giant Revolt 2', nickname='Mud Season', bike_type='gravel', is_primary=True, display_order=0),
    ],
}


def compress_photo(data: bytes) -> bytes:
    img = Image.open(io.BytesIO(data)).convert('RGB')
    img.thumbnail((400, 400), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=82, optimize=True)
    return buf.getvalue()


def upload_to_spaces(key: str, data: bytes) -> None:
    client = boto3.client(
        's3',
        region_name=SPACES_REGION,
        endpoint_url=SPACES_ENDPOINT,
        aws_access_key_id=SPACES_KEY,
        aws_secret_access_key=SPACES_SECRET,
    )
    client.put_object(
        Bucket=SPACES_BUCKET,
        Key=key,
        Body=data,
        ContentType='image/jpeg',
        ACL='public-read',
    )
    print(f"  Uploaded {key} ({len(data)} bytes)")


conn = psycopg2.connect(DB_URL)
conn.autocommit = False
cur = conn.cursor()

# Get demo rider user IDs
cur.execute("SELECT id, username FROM users WHERE username = ANY(%s)",
            (['alex_demo', 'jordan_demo', 'casey_demo', 'riley_demo'],))
riders = {row[1]: row[0] for row in cur.fetchall()}
print("Found demo riders:", riders)

for username, user_id in riders.items():
    print(f"\n--- {username} (id={user_id}) ---")

    # ── Profile photo ──────────────────────────────────────────────────────
    photo_url = DEMO_PHOTOS.get(username)
    if photo_url:
        print(f"  Fetching photo from {photo_url}")
        req = urllib.request.Request(photo_url, headers={'User-Agent': 'Paceline/1.0'})
        raw = urllib.request.urlopen(req, timeout=10).read()
        compressed = compress_photo(raw)
        key = f'avatars/{user_id}.jpg'
        upload_to_spaces(key, compressed)
        cur.execute("UPDATE users SET profile_photo_key = %s WHERE id = %s", (key, user_id))
        print(f"  Set profile_photo_key = {key}")

    # ── Bikes ──────────────────────────────────────────────────────────────
    # Remove any existing bikes for this user first
    cur.execute("DELETE FROM user_bikes WHERE user_id = %s", (user_id,))
    bikes = DEMO_BIKES.get(username, [])
    for b in bikes:
        cur.execute("""
            INSERT INTO user_bikes (user_id, make_model, nickname, bike_type, is_primary, display_order, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
        """, (user_id, b['make_model'], b.get('nickname'), b['bike_type'],
              b['is_primary'], b['display_order']))
        print(f"  Added bike: {b['make_model']} ({b['bike_type']})")

conn.commit()
conn.close()
print("\nDone — demo rider profiles updated with photos and bikes.")
