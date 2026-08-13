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
import logging
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

_TRACE_ID = "unit-trace-1234abcd"

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
    """Facade stand-in so auth routes answer without a database.

    ``access_denials`` records the identities whose 403 the gateway asked the
    facade to audit (PHASE-2 REM T7, #87), so tests can pin the emission and
    its absence.
    """

    def __init__(self) -> None:
        self.access_denials: list[int] = []

    async def register_patient(self, phone: str) -> RegisterPatientResult:
        return _RESULT

    async def emit_access_denied(self, identity_id: int) -> None:
        self.access_denials.append(identity_id)


class FailingEmitFacade(StubFacade):
    """A facade whose access-denial emission fails, to prove the 403 survives."""

    async def emit_access_denied(self, identity_id: int) -> None:
        raise RuntimeError("outbox unavailable")


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


def _protected_client(
    settings: Settings | None = None, facade: StubFacade | None = None
) -> TestClient:
    """The real app: the ``/v1/me`` protected route proves admit/deny.

    ``facade`` (when given) replaces ``app.state.iam_facade`` after the app is
    built so the 403 path answers without a database; the middleware's
    ``validate_token`` is stateless (signature + expiry only) and keeps working
    off the real facade it was bound to at build time.
    """
    if settings is None:
        settings = Settings(gateway_jwt_verify_enabled=True, gateway_jwt_signing_key=_SIGNING_KEY)
    app = create_app(settings=settings)
    if facade is not None:
        app.state.iam_facade = facade
    return TestClient(app)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _with_trace(headers: dict[str, str] | None = None) -> dict[str, str]:
    return {**(headers or {}), "X-Request-Id": _TRACE_ID}


def _assert_gateway_rejection_logged(caplog: pytest.LogCaptureFixture, trace_id: str) -> None:
    """One ``gateway_rejection`` line carries the same id as the envelope."""
    assert any(
        "gateway_rejection" in record.getMessage() and f"trace_id={trace_id}" in record.getMessage()
        for record in caplog.records
    )


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


def test_jwt_verify_denies_presented_malformed_token(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    client = _protected_client()

    response = client.get("/v1/me", headers=_with_trace(_bearer("not-a-jws")))

    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "AUTH_UNAUTHENTICATED"
    assert body["trace_id"] == _TRACE_ID
    assert body["details"] == {}
    _assert_gateway_rejection_logged(caplog, _TRACE_ID)


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


def test_anonymous_denied_on_protected_route_with_401_envelope(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    client = _protected_client()

    response = client.get("/v1/me", headers={"X-Request-Id": _TRACE_ID})

    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "AUTH_UNAUTHENTICATED"
    assert body["message"]
    assert body["details"] == {}
    assert body["trace_id"] == _TRACE_ID
    _assert_gateway_rejection_logged(caplog, _TRACE_ID)


def test_denial_without_client_request_id_mints_trace_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    client = _protected_client()

    response = client.get("/v1/me", headers=_bearer("not-a-jws"))

    assert response.status_code == 401
    trace_id = response.json()["trace_id"]
    assert trace_id
    _assert_gateway_rejection_logged(caplog, trace_id)


def test_blank_request_id_falls_back_to_minted_trace_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    client = _protected_client()

    response = client.get("/v1/me", headers={**_bearer("not-a-jws"), "X-Request-Id": "   "})

    assert response.status_code == 401
    trace_id = response.json()["trace_id"]
    assert trace_id
    _assert_gateway_rejection_logged(caplog, trace_id)


def test_request_id_guard_rejects_log_unsafe_tokens() -> None:
    from app.gateway.trace import _is_safe_trace_id

    assert _is_safe_trace_id("abc-123._:/~")
    assert not _is_safe_trace_id("")
    assert not _is_safe_trace_id("a b")
    assert not _is_safe_trace_id("a\nb")
    assert not _is_safe_trace_id("a" * 129)


# ---------------------------------------------------------------------------
# Protected route: RBAC scope resolution (patient = own record only)
# ---------------------------------------------------------------------------


def test_valid_patient_token_admitted_to_protected_route() -> None:
    client = _protected_client()

    response = client.get("/v1/me", headers=_bearer(_issue_access_token(subject_id=7)))

    assert response.status_code == 200
    assert response.json() == {"subject_id": "7", "roles": ["patient"]}


def test_authenticated_caller_without_patient_scope_denied_403(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    facade = StubFacade()
    client = _protected_client(facade=facade)
    token = _issue_access_token(scope="superadmin")

    response = client.get("/v1/me", headers=_with_trace(_bearer(token)))

    assert response.status_code == 403
    body = response.json()
    assert body["code"] == "AUTH_INSUFFICIENT_SCOPE"
    assert body["trace_id"] == _TRACE_ID
    assert body["details"] == {}
    _assert_gateway_rejection_logged(caplog, _TRACE_ID)


def test_authenticated_403_emits_access_denial_audit_for_the_named_identity() -> None:
    facade = StubFacade()
    client = _protected_client(facade=facade)

    response = client.get("/v1/me", headers=_bearer(_issue_access_token(scope="superadmin")))

    assert response.status_code == 403
    # The gateway passes the authenticated principal's subject - the same
    # identity the token names - to the iam facade, which resolves the phone.
    assert facade.access_denials == [7]


def test_anonymous_401_stays_log_only_no_access_denial_emission(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    facade = StubFacade()
    client = _protected_client(facade=facade)

    response = client.get("/v1/me", headers={"X-Request-Id": _TRACE_ID})

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_UNAUTHENTICATED"
    assert facade.access_denials == []
    _assert_gateway_rejection_logged(caplog, _TRACE_ID)


def test_presented_but_unusable_token_401_stays_log_only_no_access_denial_emission(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    facade = StubFacade()
    client = _protected_client(facade=facade)

    response = client.get("/v1/me", headers=_with_trace(_bearer("not-a-jws")))

    assert response.status_code == 401
    assert facade.access_denials == []
    _assert_gateway_rejection_logged(caplog, _TRACE_ID)


def test_403_survives_an_access_denial_emit_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR)
    client = _protected_client(facade=FailingEmitFacade())

    response = client.get("/v1/me", headers=_bearer(_issue_access_token(scope="superadmin")))

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"
    assert any("access_denial_emit_failed" in record.getMessage() for record in caplog.records)


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


def test_rate_limit_answers_429_with_retry_after_on_auth_route(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
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

    response = client.post(
        "/v1/auth/register",
        json={"phone": "9876543210"},
        headers={"X-Request-Id": _TRACE_ID},
    )

    assert response.status_code == 429
    body = response.json()
    assert body["code"] == "RATE_LIMIT_EXCEEDED"
    assert body["trace_id"] == _TRACE_ID
    assert body["details"] == {}
    assert response.headers["Retry-After"] == "60"
    _assert_gateway_rejection_logged(caplog, _TRACE_ID)


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
