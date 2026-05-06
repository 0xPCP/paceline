import base64
import hmac
import secrets
import struct
import time
from hashlib import sha1
from urllib.parse import quote


TOTP_INTERVAL_SECONDS = 30
TOTP_DIGITS = 6
BACKUP_CODE_COUNT = 10


def generate_totp_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode('ascii').rstrip('=')


def totp_uri(secret, account_name, issuer='Paceline'):
    label = f'{issuer}:{account_name}'
    return (
        f'otpauth://totp/{quote(label)}'
        f'?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits={TOTP_DIGITS}'
        f'&period={TOTP_INTERVAL_SECONDS}'
    )


def verify_totp(secret, code, now=None, window=1):
    code = ''.join(ch for ch in str(code or '') if ch.isdigit())
    if len(code) != TOTP_DIGITS:
        return False
    if now is None:
        now = time.time()
    counter = int(now // TOTP_INTERVAL_SECONDS)
    for offset in range(-window, window + 1):
        if hmac.compare_digest(_totp_at(secret, counter + offset), code):
            return True
    return False


def generate_backup_codes(count=BACKUP_CODE_COUNT):
    return [f'{secrets.randbelow(10**8):08d}' for _ in range(count)]


def _totp_at(secret, counter):
    key = _decode_secret(secret)
    msg = struct.pack('>Q', counter)
    digest = hmac.new(key, msg, sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % (10 ** TOTP_DIGITS)).zfill(TOTP_DIGITS)


def _decode_secret(secret):
    padded = secret + '=' * ((8 - len(secret) % 8) % 8)
    return base64.b32decode(padded, casefold=True)
