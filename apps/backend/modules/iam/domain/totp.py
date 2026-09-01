"""MOD-001: pure-logic TOTP verification for the operator MFA second factor (S8, #261).

RFC-6238 TOTP code check with an injectable clock and a configurable drift
window.  Pure logic (no SQL, no I/O - coding-standards S2) so it is
unit-testable without a database.  The adapter layer (session_facade) owns
the DB read and decryption; this module only verifies the code against the
secret.

The drift window follows the RFC recommendation: by default 1 step (30 s) in
either direction, so the caller sees at most a 90 s acceptance window.  This
is small enough to reject TOCTOU replays while tolerating minor clock skew
between the authenticator app and the server.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime

import pyotp

logger = logging.getLogger(__name__)

#: Default TOTP step in seconds (RFC-6238 default).
TOTP_INTERVAL = 30

#: Default drift window: 1 step in either direction (30 s * 3 = 90 s acceptance).
DEFAULT_DRIFT_WINDOW = 1


class TotpVerificationError(Exception):
    """The presented TOTP code is invalid, expired, or replayed."""


class TotpSecretEmptyError(Exception):
    """No TOTP secret is enrolled for this identity (fail-closed)."""


def _default_clock() -> datetime:
    return datetime.now(UTC)


def verify_totp(
    secret: str,
    code: str,
    *,
    clock: Callable[[], datetime] = _default_clock,
    drift_window: int = DEFAULT_DRIFT_WINDOW,
) -> None:
    """Verify a TOTP code against a decrypted secret.

    Uses pyotp's ``verify`` with ``for_time`` to inject the clock, so tests can
    walk the window without sleeping.  The ``valid_window`` parameter maps to
    RFC-6238 drift: ``valid_window=1`` accepts codes from t-1, t, and t+1
    (30 s each, 90 s total).

    Raises
    ------
    TotpSecretEmptyError
        If the secret is blank or empty (no enrollment).
    TotpVerificationError
        If the code is wrong, expired, or outside the drift window.
    """
    if not secret or not secret.strip():
        raise TotpSecretEmptyError(
            "no TOTP secret enrolled; complete MFA enrollment before issuing a session"
        )

    totp = pyotp.TOTP(secret)
    now = clock()
    valid = totp.verify(code, for_time=now, valid_window=drift_window)

    if not valid:
        logger.info("TOTP verification failed (code rejected by pyotp)")
        raise TotpVerificationError("invalid or expired TOTP code")


def generate_secret() -> str:
    """Generate a new base32 TOTP secret for enrollment."""
    return pyotp.random_base32()
