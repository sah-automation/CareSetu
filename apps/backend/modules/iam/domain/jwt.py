"""MOD-001: access-token wire format and session policy (PHASE-2 T6, ticket #57).

The access JWT is HS256-signed with the stdlib only (``hmac``/``hashlib``/
``base64``) - the repo's dependency-light stance (``NFR-001``, no paid or
additional framework) covers this seam with zero new dependencies. Only the
JWS compact serialization is implemented, plus the strict checks the gateway
keys off: the ``alg`` must be exactly HS256 (no ``none`` or algorithm
confusion), the signature is compared constant-time (``hmac.compare_digest``),
``exp`` is enforced at ``exp <= now``, and every claim the gateway reads
(``jti``, ``sub``, ``scope``) must be present and well-typed. Everything here
is pure logic with no I/O so unit tests pin the whole contract without a
database, and ``verify_token`` stays stateless so the edge hot path never
touches PostgreSQL (MOD-001 §3.1: ``validate_token`` p95 < 100 ms).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import cast

from pydantic import BaseModel

from modules.iam.domain.exceptions import (
    AccessTokenExpiredError,
    AccessTokenMalformedError,
    AccessTokenSignatureError,
)

_ALGORITHM = "HS256"
_TOKEN_TYPE = "JWT"  # nosec B105 - the JWS ``typ`` header, not a credential

ACCESS_TOKEN_TTL_SECONDS = 900


class AccessTokenClaims(BaseModel):
    """Claims of a verified access JWT, typed for the gateway (spec #51 §2.5).

    ``subject_id`` is the identity id (the JWT ``sub``) that the gateway scopes
    a patient to their own record; ``scope`` is the resolved RBAC scope carried
    in the token claim; ``jti``/``issued_at``/``expires_at`` mirror the claims
    so revocation and rotation (T7) have an anchor.
    """

    jti: str
    subject_id: int
    scope: str
    issued_at: datetime
    expires_at: datetime


def issue_token(
    *,
    jti: str,
    subject_id: int,
    scope: str,
    signing_key: str,
    now: datetime,
    ttl_seconds: int = ACCESS_TOKEN_TTL_SECONDS,
) -> str:
    """Mint an HS256 access JWT carrying ``jti``, ``sub``, ``scope``, ``iat``, ``exp``.

    ``exp`` is ``now + ttl_seconds`` (~15 minutes at the default) so a stolen
    access token has limited value (spec #51 §2.5). An empty ``signing_key``
    fails closed - a misconfigured deployment refuses to mint rather than sign
    with a blank key.
    """
    if not signing_key:
        raise ValueError("access-token signing key is not configured; refusing to sign")
    header: dict[str, object] = {"alg": _ALGORITHM, "typ": _TOKEN_TYPE}
    payload: dict[str, object] = {
        "jti": jti,
        "sub": str(subject_id),
        "scope": scope,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
    }
    signing_input = f"{_b64url_encode(_json_bytes(header))}.{_b64url_encode(_json_bytes(payload))}"
    signature = _b64url_encode(_sign(signing_input, signing_key))
    return f"{signing_input}.{signature}"


def verify_token(token: str, signing_key: str, now: datetime) -> AccessTokenClaims:
    """Validate ``token`` and return its claims, or raise a typed rejection.

    The checks run signature-first so a tampered or wrong-key token is refused
    before any claim is trusted: envelope shape, ``alg`` must be exactly
    HS256, constant-time signature comparison, then well-typed claims and the
    ``exp`` window. Every rejection raises its own ``InvalidAccessTokenError``
    subclass (malformed / signature / expired) so the gateway answers one 401.
    The check is stateless - no database - so the edge path stays fast. An
    empty ``signing_key`` fails closed exactly like issuance: verifying with
    no key would accept tokens forged with the blank key.
    """
    if not signing_key:
        raise AccessTokenSignatureError(
            "access-token signing key is not configured; refusing to verify"
        )
    try:
        encoded_header, encoded_payload, signature = token.split(".")
    except ValueError as exc:
        raise AccessTokenMalformedError("access token is not a JWS compact value") from exc
    if not encoded_header or not encoded_payload or not signature:
        raise AccessTokenMalformedError("access token has an empty segment")

    header = _decode_json(encoded_header, "header")
    _require_algorithm(header)

    expected = _b64url_encode(_sign(f"{encoded_header}.{encoded_payload}", signing_key))
    if not hmac.compare_digest(signature, expected):
        raise AccessTokenSignatureError("access token signature does not verify")

    payload = _decode_json(encoded_payload, "payload")
    return _extract_claims(payload, now)


def _json_bytes(value: dict[str, object]) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(part: str) -> bytes:
    padding = "=" * (-len(part) % 4)
    return base64.urlsafe_b64decode(part + padding)


def _sign(signing_input: str, signing_key: str) -> bytes:
    return hmac.new(
        signing_key.encode("utf-8"),
        signing_input.encode("utf-8"),
        hashlib.sha256,
    ).digest()


def _decode_json(encoded: str, segment: str) -> dict[str, object]:
    try:
        raw = _b64url_decode(encoded)
    except (binascii.Error, ValueError) as exc:
        raise AccessTokenMalformedError(f"access token {segment} is not valid base64url") from exc
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AccessTokenMalformedError(f"access token {segment} is not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise AccessTokenMalformedError(f"access token {segment} is not a JSON object")
    return cast(dict[str, object], decoded)


def _require_algorithm(header: dict[str, object]) -> None:
    alg = header.get("alg")
    if alg == _ALGORITHM:
        return
    if alg in (None, "none"):
        raise AccessTokenMalformedError("access token is unsigned (alg=none)")
    raise AccessTokenSignatureError(f"unsupported signing algorithm {alg!r}")


def _extract_claims(payload: dict[str, object], now: datetime) -> AccessTokenClaims:
    jti = payload.get("jti")
    sub = payload.get("sub")
    scope = payload.get("scope")
    exp = payload.get("exp")
    iat = payload.get("iat")
    if not isinstance(jti, str) or not jti:
        raise AccessTokenMalformedError("access token has no jti claim")
    if not isinstance(sub, str) or not sub:
        raise AccessTokenMalformedError("access token has no sub claim")
    if not isinstance(scope, str) or not scope:
        raise AccessTokenMalformedError("access token has no scope claim")
    if not isinstance(exp, (int, float)) or not isinstance(iat, (int, float)):
        raise AccessTokenMalformedError("access token exp/iat claims must be numeric")
    try:
        subject_id = int(sub)
    except ValueError as exc:
        raise AccessTokenMalformedError("access token sub is not a numeric subject id") from exc
    expires_at = datetime.fromtimestamp(exp, tz=UTC)
    if now >= expires_at:
        raise AccessTokenExpiredError("access token has expired")
    return AccessTokenClaims(
        jti=jti,
        subject_id=subject_id,
        scope=scope,
        issued_at=datetime.fromtimestamp(iat, tz=UTC),
        expires_at=expires_at,
    )
