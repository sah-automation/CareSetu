"""PHASE-2 T8: gateway edge enforcement + RBAC + rate limiting (ticket #59).

Acceptance contract from the brief: ``jwt_verify`` verifies the access JWT and
attaches a ``Principal`` with the resolved RBAC scope; anonymous, malformed,
expired, unsigned, and wrong-signed requests are denied on protected routes
(no accept-all fallback); an authenticated patient resolves to own-record-only
scope; rate limiting applies to the OTP + auth endpoints; and the protected
route admits/denies at the app level.

Seam 2 from spec #51: the gateway middleware is tested at the app level with
real tokens minted by the module's own ``issue_token`` against the same signing
key the app resolves.
"""

from __future__ import annotations

import base64
import json
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.config import Settings, get_settings
from app.gateway.principal import Principal
from app.gateway.rate_limit import _MAX_TRACKED_BUCKETS, RateLimitMiddleware
from app.gateway.rbac import resolve_scope_roles
from app.main import create_app
from modules.iam.domain.jwt import issue_token
from modules.iam.facade import RegisterPatientResult

_SIGNING_KEY = "unit-test-gateway-signing-key"

_RESULT = RegisterPatientResult(
    outcome="sent",
    phone_e164="+919876543210",
    identity_id=7,
    challenge_id=42,
    is_existing=False,
    flow="register",
    expires_in_seconds=300,
    cooldown_remaining_seconds=60,
    attempts_left=5,
)


class StubFacade:
    """Facade stand-in so auth routes answer without a database."""

    async def register_patient(self, phone: str) -> RegisterPatientResult:
        return _RESULT


def _issue_access_token(
    *,
    subject_id: int = 7,
    scope: str = "patient",
    now: datetime | None = None,
    key: str = _SIGNING_KEY,
) -> str:
    """A valid HS256 access JWT minted exactly like ``issue_session`` does."""
    return issue_token(
        jti=uuid.uuid4().hex,
        subject_id=subject_id,
        scope=scope,
        signing_key=key,
        now=now or datetime.now(UTC),
    )


def _unsigned_token(subject_id: int = 7) -> str:
    """An ``alg: none`` JWT the gateway must refuse as unsigned."""

    def b64url(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    header = b64url(
        json.dumps({"alg": "none", "typ": "JWT"}, separators=(",", ":"), sort_keys=True).encode()
    )
    payload = b64url(
        json.dumps(
            {
                "jti": "unsigned-jti",
                "sub": str(subject_id),
                "scope": "patient",
                "iat": 1_000_000,
                "exp": 9_999_999_999,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    )
    return f"{header}.{payload}."


def _probe_client(settings: Settings) -> TestClient:
    """An app that reports the gateway's effect on request state (ticket #29 pattern)."""

    app = create_app(settings=settings)

    @app.get("/probe")
    def probe(request: Request) -> dict[str, object]:
        state = request.state
        principal: Principal | None = getattr(state, "principal", None)
        return {
            "principal_subject": principal.subject_id if principal else None,
            "principal_authenticated": principal.is_authenticated if principal else None,
            "principal_roles": list(principal.roles) if principal else None,
            "rate_limit_checked": getattr(state, "gateway_rate_limit_checked", False),
        }

    @app.get("/v1/auth/probe")
    def auth_probe(request: Request) -> dict[str, object]:
        return {"rate_limit_checked": getattr(request.state, "gateway_rate_limit_checked", False)}

    return TestClient(app)


def _protected_client(settings: Settings | None = None) -> TestClient:
    """The real app: the ``/v1/me`` protected route proves admit/deny."""
    if settings is None:
        settings = Settings(gateway_jwt_verify_enabled=True, gateway_jwt_signing_key=_SIGNING_KEY)
    return TestClient(create_app(settings=settings))


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# jwt_verify: real Bearer verification + Principal attachment
# ---------------------------------------------------------------------------


def test_jwt_verify_disabled_passes_through() -> None:
    client = _probe_client(Settings())

    response = client.get("/probe")

    assert response.status_code == 200
    body = response.json()
    assert body["principal_subject"] is None
    assert body["rate_limit_checked"] is False


def test_jwt_verify_missing_header_attaches_anonymous_principal() -> None:
    settings = Settings(gateway_jwt_verify_enabled=True, gateway_jwt_signing_key=_SIGNING_KEY)
    client = _probe_client(settings)

    response = client.get("/probe")

    assert response.status_code == 200
    body = response.json()
    assert body["principal_subject"] == "anonymous"
    assert body["principal_authenticated"] is False


def test_jwt_verify_attaches_scoped_principal_from_valid_bearer_token() -> None:
    settings = Settings(gateway_jwt_verify_enabled=True, gateway_jwt_signing_key=_SIGNING_KEY)
    client = _probe_client(settings)

    response = client.get("/probe", headers=_bearer(_issue_access_token(subject_id=7)))

    assert response.status_code == 200
    body = response.json()
    assert body["principal_subject"] == "7"
    assert body["principal_authenticated"] is True
    assert body["principal_roles"] == ["patient"]


def test_jwt_verify_denies_presented_malformed_token() -> None:
    client = _protected_client()

    response = client.get("/v1/me", headers=_bearer("not-a-jws"))

    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "AUTH_UNAUTHENTICATED"
    assert isinstance(body["trace_id"], str) and body["trace_id"]
    assert body["details"] == {}


def test_jwt_verify_denies_expired_token() -> None:
    client = _protected_client()
    expired = _issue_access_token(now=datetime.now(UTC) - timedelta(hours=1))

    response = client.get("/v1/me", headers=_bearer(expired))

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_UNAUTHENTICATED"


def test_jwt_verify_denies_unsigned_token() -> None:
    client = _protected_client()

    response = client.get("/v1/me", headers=_bearer(_unsigned_token()))

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_UNAUTHENTICATED"


def test_jwt_verify_denies_wrong_signing_key_token() -> None:
    client = _protected_client()
    wrong_key = _issue_access_token(key="a-different-key")

    response = client.get("/v1/me", headers=_bearer(wrong_key))

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_UNAUTHENTICATED"


def test_jwt_verify_denies_non_bearer_authorization_header() -> None:
    client = _protected_client()

    response = client.get("/v1/me", headers={"Authorization": "Basic dXNlcjpwYXNz"})

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_UNAUTHENTICATED"


def test_anonymous_denied_on_protected_route_with_401_envelope() -> None:
    client = _protected_client()

    response = client.get("/v1/me")

    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "AUTH_UNAUTHENTICATED"
    assert body["message"]
    assert body["details"] == {}


# ---------------------------------------------------------------------------
# Protected route: RBAC scope resolution (patient = own record only)
# ---------------------------------------------------------------------------


def test_valid_patient_token_admitted_to_protected_route() -> None:
    client = _protected_client()

    response = client.get("/v1/me", headers=_bearer(_issue_access_token(subject_id=7)))

    assert response.status_code == 200
    assert response.json() == {"subject_id": "7", "roles": ["patient"]}


def test_authenticated_caller_without_patient_scope_denied_403() -> None:
    client = _protected_client()
    token = _issue_access_token(scope="superadmin")

    response = client.get("/v1/me", headers=_bearer(token))

    assert response.status_code == 403
    body = response.json()
    assert body["code"] == "AUTH_INSUFFICIENT_SCOPE"
    assert body["details"] == {}


def test_resolve_scope_roles_maps_known_scopes_to_singleton_role() -> None:
    assert resolve_scope_roles("patient") == ("patient",)
    assert resolve_scope_roles("partner") == ("partner",)
    assert resolve_scope_roles("operator") == ("operator",)


def test_resolve_scope_roles_unknown_scope_fails_closed() -> None:
    assert resolve_scope_roles("superadmin") == ()


# ---------------------------------------------------------------------------
# rate_limit: per-caller cap on the OTP/auth surface (NFR-SEC-004)
# ---------------------------------------------------------------------------


def test_rate_limit_disabled_passes_through() -> None:
    client = _probe_client(Settings())

    response = client.get("/probe")

    assert response.status_code == 200
    assert response.json()["rate_limit_checked"] is False


def test_rate_limit_enabled_counts_only_auth_paths() -> None:
    settings = Settings(gateway_rate_limit_enabled=True)
    client = _probe_client(settings)

    assert client.get("/v1/auth/probe").json()["rate_limit_checked"] is True
    assert client.get("/probe").json()["rate_limit_checked"] is False


def test_rate_limit_answers_429_with_retry_after_on_auth_route() -> None:
    settings = Settings(
        gateway_rate_limit_enabled=True,
        gateway_rate_limit_auth_max_requests=2,
        gateway_rate_limit_auth_window_seconds=60,
    )
    app = create_app(settings=settings)
    app.state.iam_facade = StubFacade()
    client = TestClient(app)

    assert client.post("/v1/auth/register", json={"phone": "9876543210"}).status_code == 200
    assert client.post("/v1/auth/register", json={"phone": "9876543210"}).status_code == 200

    response = client.post("/v1/auth/register", json={"phone": "9876543210"})

    assert response.status_code == 429
    body = response.json()
    assert body["code"] == "RATE_LIMIT_EXCEEDED"
    assert body["details"] == {}
    assert response.headers["Retry-After"] == "60"


def test_rate_limit_does_not_limit_health_endpoint() -> None:
    settings = Settings(
        gateway_rate_limit_enabled=True,
        gateway_rate_limit_auth_max_requests=2,
    )
    client = _protected_client(settings)

    for _ in range(5):
        assert client.get("/health").status_code == 200


def test_rate_limit_is_per_identity_when_authenticated() -> None:
    settings = Settings(
        gateway_jwt_verify_enabled=True,
        gateway_jwt_signing_key=_SIGNING_KEY,
        gateway_rate_limit_enabled=True,
        gateway_rate_limit_auth_max_requests=1,
        gateway_rate_limit_auth_window_seconds=60,
    )
    client = _probe_client(settings)

    # Identity 7 exhausts its own bucket on the first request.
    assert (
        client.get("/v1/auth/probe", headers=_bearer(_issue_access_token(subject_id=7))).status_code
        == 200
    )
    # A different identity from the same client IP starts a fresh bucket...
    assert (
        client.get("/v1/auth/probe", headers=_bearer(_issue_access_token(subject_id=8))).status_code
        == 200
    )
    # ...while identity 7's exhausted bucket is now refused (api-standards §6).
    assert (
        client.get("/v1/auth/probe", headers=_bearer(_issue_access_token(subject_id=7))).status_code
        == 429
    )


def test_rate_limit_prune_keeps_bucket_dict_bounded() -> None:
    middleware = RateLimitMiddleware(app=None, enabled=True, max_requests=10, window_seconds=60)
    now = time.monotonic()
    for index in range(_MAX_TRACKED_BUCKETS + 50):
        middleware._buckets[f"ip:spray-{index}"] = (now + 60, 1)

    middleware._prune(now)

    assert len(middleware._buckets) <= _MAX_TRACKED_BUCKETS


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def test_settings_default_to_gateway_disabled() -> None:
    settings = Settings()

    assert settings.gateway_jwt_verify_enabled is False
    assert settings.gateway_rate_limit_enabled is False
    assert not hasattr(settings, "gateway_jwt_test_header")
    assert settings.gateway_rate_limit_auth_max_requests == 10
    assert settings.gateway_rate_limit_auth_window_seconds == 60


def test_settings_read_gateway_flags_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GATEWAY_JWT_VERIFY_ENABLED", "true")
    monkeypatch.setenv("GATEWAY_JWT_SIGNING_KEY", "env-signing-key")
    monkeypatch.setenv("GATEWAY_RATE_LIMIT_ENABLED", "1")
    monkeypatch.setenv("GATEWAY_RATE_LIMIT_AUTH_MAX_REQUESTS", "25")
    monkeypatch.setenv("GATEWAY_RATE_LIMIT_AUTH_WINDOW_SECONDS", "120")

    settings = get_settings()

    assert settings.gateway_jwt_verify_enabled is True
    assert settings.gateway_jwt_signing_key == "env-signing-key"
    assert settings.gateway_rate_limit_enabled is True
    assert settings.gateway_rate_limit_auth_max_requests == 25
    assert settings.gateway_rate_limit_auth_window_seconds == 120


_GUARD_ERROR = "requires GATEWAY_JWT_SIGNING_KEY"


def test_settings_guard_refuses_jwt_verify_without_signing_key() -> None:
    with pytest.raises(ValueError, match=_GUARD_ERROR):
        Settings(gateway_jwt_verify_enabled=True)


def test_settings_guard_allows_jwt_verify_with_signing_key() -> None:
    settings = Settings(gateway_jwt_verify_enabled=True, gateway_jwt_signing_key=_SIGNING_KEY)

    assert settings.gateway_jwt_verify_enabled is True


def test_settings_load_refuses_jwt_verify_without_signing_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GATEWAY_JWT_VERIFY_ENABLED", "true")
    monkeypatch.delenv("GATEWAY_JWT_SIGNING_KEY", raising=False)

    with pytest.raises(ValueError, match=_GUARD_ERROR):
        get_settings()


def test_settings_disabled_jwt_verify_needs_no_signing_key() -> None:
    settings = Settings(gateway_jwt_verify_enabled=False)

    assert settings.gateway_jwt_verify_enabled is False


def test_settings_guard_refuses_non_positive_rate_limit_settings() -> None:
    with pytest.raises(ValueError, match="gateway_rate_limit_auth_max_requests must be positive"):
        Settings(gateway_rate_limit_auth_max_requests=0)
    with pytest.raises(ValueError, match="gateway_rate_limit_auth_window_seconds must be positive"):
        Settings(gateway_rate_limit_auth_window_seconds=0)


# ---------------------------------------------------------------------------
# Principal contract (unchanged from PHASE-1 T7b, #29)
# ---------------------------------------------------------------------------


def test_principal_is_a_typed_model() -> None:
    principal = Principal.for_subject("7", "patient")

    assert isinstance(principal, Principal)
    assert principal.subject_id == "7"
    assert principal.roles == ("patient",)
    assert principal.is_authenticated is True


def test_anonymous_principal_is_unauthenticated() -> None:
    principal = Principal.anonymous()

    assert principal.subject_id == "anonymous"
    assert principal.roles == ()
    assert principal.is_authenticated is False
