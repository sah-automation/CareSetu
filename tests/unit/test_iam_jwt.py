"""PHASE-2 T6: access JWT wire format + session policy (ticket #57, spec #51 §2.5).

The token seam is pure logic with no I/O - stdlib HS256, dependency-light per
``NFR-001`` - so unit tests pin the whole contract without a database: issued
tokens carry the expected claims and a ~15-minute ``exp``, expiry is enforced
at ``exp <= now``, and tampered, malformed, wrong-key, unsigned, and
algorithm-confusion tokens each raise the typed rejection the gateway maps to
a single 401.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import pytest

from modules.iam.domain.exceptions import (
    AccessTokenExpiredError,
    AccessTokenMalformedError,
    AccessTokenSignatureError,
)
from modules.iam.domain.jwt import (
    ACCESS_TOKEN_TTL_SECONDS,
    AccessTokenClaims,
    issue_token,
    verify_token,
)

_NOW = datetime(2026, 8, 13, 12, 0, 0, tzinfo=UTC)
_KEY = "unit-test-signing-key"
_OTHER_KEY = "unit-test-other-key"
_JTI = "0123456789abcdef0123456789abcdef"
_SCOPE = "patient"


def _token(
    *,
    jti: str = _JTI,
    subject_id: int = 42,
    scope: str = _SCOPE,
    ttl_seconds: int = ACCESS_TOKEN_TTL_SECONDS,
) -> str:
    return issue_token(
        jti=jti,
        subject_id=subject_id,
        scope=scope,
        signing_key=_KEY,
        now=_NOW,
        ttl_seconds=ttl_seconds,
    )


def _jws(header: dict[str, object], payload: object, *, key: str = _KEY) -> str:
    """Sign an arbitrary header/payload pair so tests can forge valid tokens."""

    def enc(value: object) -> str:
        raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    signing_input = f"{enc(header)}.{enc(payload)}"
    signature = (
        base64.urlsafe_b64encode(
            hmac.new(
                key.encode("utf-8"), signing_input.encode("utf-8"), hashlib.sha256
            ).digest()
        )
        .decode("ascii")
        .rstrip("=")
    )
    return f"{signing_input}.{signature}"


def _valid_forged_payload() -> dict[str, object]:
    return {
        "jti": _JTI,
        "sub": "42",
        "scope": _SCOPE,
        "iat": 1,
        "exp": int((_NOW + timedelta(hours=1)).timestamp()),
    }


def test_issued_token_carries_the_expected_claims() -> None:
    token = _token()

    claims = verify_token(token, _KEY, _NOW)

    assert claims == AccessTokenClaims(
        jti=_JTI,
        subject_id=42,
        scope=_SCOPE,
        issued_at=_NOW,
        expires_at=_NOW + timedelta(seconds=ACCESS_TOKEN_TTL_SECONDS),
    )


def test_access_token_ttl_defaults_to_about_fifteen_minutes() -> None:
    assert ACCESS_TOKEN_TTL_SECONDS == 900


def test_issued_token_is_a_three_segment_jws() -> None:
    token = _token()

    assert token.count(".") == 2
    assert all(token.split("."))


def test_token_verifies_right_up_to_the_expiry_window() -> None:
    token = _token()
    just_before = _NOW + timedelta(seconds=ACCESS_TOKEN_TTL_SECONDS - 1)

    assert verify_token(token, _KEY, just_before).scope == _SCOPE


def test_token_at_the_exact_expiry_is_rejected() -> None:
    token = _token()
    at_expiry = _NOW + timedelta(seconds=ACCESS_TOKEN_TTL_SECONDS)

    with pytest.raises(AccessTokenExpiredError):
        verify_token(token, _KEY, at_expiry)


def test_expired_token_is_rejected() -> None:
    token = _token()

    with pytest.raises(AccessTokenExpiredError):
        verify_token(token, _KEY, _NOW + timedelta(minutes=20))


def test_custom_ttl_is_honoured() -> None:
    token = _token(ttl_seconds=120)

    claims = verify_token(token, _KEY, _NOW)

    assert claims.expires_at == _NOW + timedelta(seconds=120)
    assert claims.issued_at == _NOW


def test_tampered_payload_is_rejected() -> None:
    token = _token()
    header, payload, signature = token.split(".")

    with pytest.raises(AccessTokenSignatureError):
        verify_token(f"{header}.{payload}000.{signature}", _KEY, _NOW)


def test_tampered_signature_is_rejected() -> None:
    token = _token()
    header, payload, _signature = token.split(".")

    with pytest.raises(AccessTokenSignatureError):
        verify_token(f"{header}.{payload}.AAAA", _KEY, _NOW)


def test_token_signed_with_another_key_is_rejected() -> None:
    token = _token()

    with pytest.raises(AccessTokenSignatureError):
        verify_token(token, _OTHER_KEY, _NOW)


def test_token_without_segments_is_rejected() -> None:
    with pytest.raises(AccessTokenMalformedError):
        verify_token("not-a-jwt", _KEY, _NOW)


def test_token_with_extra_segment_is_rejected() -> None:
    token = _token()

    with pytest.raises(AccessTokenMalformedError):
        verify_token(f"{token}.extra", _KEY, _NOW)


def test_token_with_empty_segment_is_rejected() -> None:
    with pytest.raises(AccessTokenMalformedError):
        verify_token("..", _KEY, _NOW)


def test_token_with_invalid_base64_segment_is_rejected() -> None:
    token = _token()
    _header, payload, signature = token.split(".")

    with pytest.raises(AccessTokenMalformedError):
        verify_token(f"!!!.{payload}.{signature}", _KEY, _NOW)


def test_unsigned_alg_none_token_is_rejected() -> None:
    forged = _jws({"alg": "none", "typ": "JWT"}, _valid_forged_payload())

    with pytest.raises(AccessTokenMalformedError):
        verify_token(forged, _KEY, _NOW)


def test_algorithm_confusion_token_is_rejected() -> None:
    forged = _jws({"alg": "RS256", "typ": "JWT"}, _valid_forged_payload())

    with pytest.raises(AccessTokenSignatureError):
        verify_token(forged, _KEY, _NOW)


def test_payload_that_is_not_an_object_is_rejected() -> None:
    forged = _jws({"alg": "HS256", "typ": "JWT"}, "just a string")

    with pytest.raises(AccessTokenMalformedError):
        verify_token(forged, _KEY, _NOW)


def test_payload_without_jti_is_rejected() -> None:
    payload = _valid_forged_payload()
    del payload["jti"]

    with pytest.raises(AccessTokenMalformedError):
        verify_token(_jws({"alg": "HS256", "typ": "JWT"}, payload), _KEY, _NOW)


def test_payload_without_sub_is_rejected() -> None:
    payload = _valid_forged_payload()
    del payload["sub"]

    with pytest.raises(AccessTokenMalformedError):
        verify_token(_jws({"alg": "HS256", "typ": "JWT"}, payload), _KEY, _NOW)


def test_payload_with_non_numeric_sub_is_rejected() -> None:
    payload = _valid_forged_payload()
    payload["sub"] = "not-a-number"

    with pytest.raises(AccessTokenMalformedError):
        verify_token(_jws({"alg": "HS256", "typ": "JWT"}, payload), _KEY, _NOW)


def test_payload_without_scope_is_rejected() -> None:
    payload = _valid_forged_payload()
    del payload["scope"]

    with pytest.raises(AccessTokenMalformedError):
        verify_token(_jws({"alg": "HS256", "typ": "JWT"}, payload), _KEY, _NOW)


def test_payload_without_exp_is_rejected() -> None:
    payload = _valid_forged_payload()
    del payload["exp"]

    with pytest.raises(AccessTokenMalformedError):
        verify_token(_jws({"alg": "HS256", "typ": "JWT"}, payload), _KEY, _NOW)


def test_payload_without_iat_is_rejected() -> None:
    payload = _valid_forged_payload()
    del payload["iat"]

    with pytest.raises(AccessTokenMalformedError):
        verify_token(_jws({"alg": "HS256", "typ": "JWT"}, payload), _KEY, _NOW)


def test_empty_signing_key_fails_closed_at_issue() -> None:
    with pytest.raises(ValueError, match="signing key is not configured"):
        issue_token(
            jti=_JTI,
            subject_id=42,
            scope=_SCOPE,
            signing_key="",
            now=_NOW,
        )


def test_empty_signing_key_fails_closed_at_verify() -> None:
    token = _token()

    with pytest.raises(
        AccessTokenSignatureError, match="signing key is not configured"
    ):
        verify_token(token, "", _NOW)
