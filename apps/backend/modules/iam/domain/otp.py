"""MOD-001: OTP challenge primitives (PHASE-2 T3, ticket #54, FEAT-001).

The challenge contract from spec #51 §2.4: single-use, 5-minute TTL, values
hashed at rest and never logged (security-phii-standards). A 6-digit code is
low-entropy, so the stored hash uses the memory-hard scrypt KDF with a fresh
random salt per challenge - a fast hash would let a leaked ``otp_hash`` column
be brute-forced offline. Everything here is pure logic with no I/O so unit
tests can pin the whole contract without a database.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

OTP_LENGTH = 6
OTP_TTL_SECONDS = 300
RESEND_COOLDOWN_SECONDS = 60
MAX_ATTEMPTS = 5

_SCRYPT_N = 1 << 14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32
_SALT_BYTES = 16
_SCRYPT_MAXMEM = 128 * _SCRYPT_N * _SCRYPT_R * 4

_SCRYPT_ALGO = "scrypt"


def generate_otp() -> str:
    """A fresh 6-digit code from the CSPRNG (secrets, never ``random``)."""
    return f"{secrets.randbelow(10**OTP_LENGTH):0{OTP_LENGTH}d}"


def hash_otp(otp: str) -> str:
    """Memory-hard hash of ``otp`` with a fresh random salt, as stored text.

    The stored form is ``scrypt$<n>$<r>$<p>$<salthex>$<digesthex>`` so the
    parameters travel with the value and verification is self-describing.
    """
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = _scrypt(otp.encode("utf-8"), salt)
    return f"{_SCRYPT_ALGO}${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_otp(otp: str, stored: str) -> bool:
    """Constant-time check of ``otp`` against a value written by ``hash_otp``.

    Returns ``False`` (never raises) for malformed or foreign stored values so
    a corrupt row degrades to a failed attempt rather than a 500.
    """
    parsed = _parse_stored(stored)
    if parsed is None:
        return False
    n, r, p, salt, digest = parsed
    computed = _scrypt(otp.encode("utf-8"), salt, n=n, r=r, p=p)
    return hmac.compare_digest(computed, digest)


def _scrypt(
    password: bytes,
    salt: bytes,
    *,
    n: int = _SCRYPT_N,
    r: int = _SCRYPT_R,
    p: int = _SCRYPT_P,
) -> bytes:
    return hashlib.scrypt(
        password,
        salt=salt,
        n=n,
        r=r,
        p=p,
        dklen=_SCRYPT_DKLEN,
        maxmem=_SCRYPT_MAXMEM,
    )


def _parse_stored(stored: str) -> tuple[int, int, int, bytes, bytes] | None:
    parts = stored.split("$")
    if len(parts) != 6 or parts[0] != _SCRYPT_ALGO:
        return None
    try:
        return (
            int(parts[1]),
            int(parts[2]),
            int(parts[3]),
            bytes.fromhex(parts[4]),
            bytes.fromhex(parts[5]),
        )
    except ValueError:
        return None
