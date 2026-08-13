"""MOD-001: opaque refresh-token primitives (PHASE-2 T7, ticket #58).

The refresh contract from spec #51 §2.5: an opaque refresh token stored
server-side in the ``sessions`` table with a ~30-day sliding lifetime, rotated
on every refresh so an old token is immediately unusable, and fully independent
of SMS (NFR-004 - an OTP provider outage never bricks an existing session). The
token is high-entropy CSPRNG output - never a JWT - and is hashed at rest with
SHA-256: unlike the 6-digit OTP (which needs the memory-hard scrypt KDF in
otp.py because it is low-entropy), there is no offline brute-force space, so a
fast digest is safe. Everything here is pure logic with no I/O so unit tests
pin the token shape, the hash round-trip, and the rotation/expiry/revoke gates
without a database.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

REFRESH_TOKEN_TTL_SECONDS = 2_592_000  # ~30 days

_REFRESH_TOKEN_BYTES = 32

RefreshOutcome = Literal["rotated", "rejected"]


@dataclass(frozen=True)
class RefreshDecision:
    """Outcome of evaluating one presented refresh token (ticket #58).

    Only ``rotated`` proceeds to mint a fresh access JWT and a new refresh
    token. ``rejected`` carries the reason the session service maps to its
    typed error - ``revoked`` (the token belongs to a rotated or
    operator-revoked session - a replay signal) or ``expired`` (the sliding
    window has closed). An unknown token never reaches this function: the
    facade rejects the lookup miss on the hash before the gate is consulted.
    """

    outcome: RefreshOutcome
    reason: Literal["revoked", "expired"] | None = None


def generate_refresh_token() -> str:
    """A fresh opaque refresh token from the CSPRNG (secrets, never ``random``)."""
    return secrets.token_urlsafe(_REFRESH_TOKEN_BYTES)


def hash_refresh_token(token: str) -> str:
    """SHA-256 digest of ``token`` as the value stored in the ``sessions`` table.

    The stored column never holds the token itself (security-phii-standards
    §1). The digest is one-way and the token space is too large to enumerate,
    so a leaked column is not exploitable - no salt needed.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def evaluate_refresh(
    *,
    revoked_at: datetime | None,
    refresh_expires_at: datetime | None,
    now: datetime,
) -> RefreshDecision:
    """Gate a known session row against revoked, then expired.

    Precedence is deliberate: a revoked session (rotated or operator-revoked)
    is refused even if its window is still open, because a replayed token is a
    compromise signal worth an audit event; an expired window is the ordinary
    end of life. The expiry boundary is inclusive - at ``now ==
    refresh_expires_at`` the window has closed. An unknown token never reaches
    this function - the facade rejects the lookup miss before it is called.
    """
    if revoked_at is not None:
        return RefreshDecision(outcome="rejected", reason="revoked")
    if refresh_expires_at is None or now >= refresh_expires_at:
        return RefreshDecision(outcome="rejected", reason="expired")
    return RefreshDecision(outcome="rotated")
