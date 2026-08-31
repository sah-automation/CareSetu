"""Shared application settings (PHASE-1 T7a, #28).

Env-driven configuration consumed by the app shell now and by the worker (#30)
and gateway (#29) next. Plain frozen dataclass over ``os.environ`` - no extra
dependency beyond the declared stack (cost floor ``NFR-001``).
"""

import os
from dataclasses import dataclass

DEFAULT_DATABASE_URL = "postgresql+asyncpg://caresetu:caresetu@localhost:5432/caresetu"
DEFAULT_APP_ENVIRONMENT = "production"
DEFAULT_SMS_PROVIDER = "mock"
DEFAULT_SMS_TIMEOUT_SECONDS = 10.0
DEFAULT_SMS_MAX_RETRIES = 3
DEFAULT_SMS_CIRCUIT_BREAKER_THRESHOLD = 5
DEFAULT_SMS_CIRCUIT_BREAKER_COOLDOWN_SECONDS = 30.0
DEFAULT_WHATSAPP_PROVIDER = "mock"
DEFAULT_WHATSAPP_TIMEOUT_SECONDS = 10.0
DEFAULT_WHATSAPP_MAX_RETRIES = 3
DEFAULT_WHATSAPP_CIRCUIT_BREAKER_THRESHOLD = 5
DEFAULT_WHATSAPP_CIRCUIT_BREAKER_COOLDOWN_SECONDS = 30.0
# Redis consent-status cache (PHASE-3 T4, #213): optional; SQL fallback when
# absent or unhealthy. p95 < 50 ms SLA on the hot path.
DEFAULT_REDIS_URL = ""
DEFAULT_REDIS_CONSENT_TTL_SECONDS = 300
# Auth-surface rate limit (``NFR-SEC-004``): the OTP/auth endpoints are the
# abuse target, so the gateway caps them per caller. 10 requests / 60 s per
# IP is a headroom-rich ceiling above the one-user flow (register + verify +
# resend) while still stopping bursts.
DEFAULT_AUTH_RATE_LIMIT_MAX_REQUESTS = 10
DEFAULT_AUTH_RATE_LIMIT_WINDOW_SECONDS = 60
# Mirrors ``modules.iam.domain.jwt.ACCESS_TOKEN_TTL_SECONDS``; config stays
# import-free so it reads as one plain dataclass over the environment.
DEFAULT_ACCESS_TOKEN_TTL_SECONDS = 900
# Mirrors ``modules.iam.domain.refresh.REFRESH_TOKEN_TTL_SECONDS`` (~30 days).
DEFAULT_REFRESH_TOKEN_TTL_SECONDS = 2_592_000
# Audit retention (PHASE-4, issue #234 storage item 21): 0 = no expiry, keep
# every regulated act indefinitely. A future compliance decision may raise this
# to 2555 (7 years) via AUDIT_RETENTION_DAYS without code changes; compaction/
# archive logic stays deferred (GAP-011).
DEFAULT_AUDIT_RETENTION_DAYS = 0
# Partner credential artifacts (PHASE-5 T06, #251): encrypted local filesystem
# store under the ``partner/`` object-storage prefix. ``PARTNER_ARTIFACT_KEY``
# is a base64 32-byte AES-256 key from the environment (never committed); the
# store refuses a blank/malformed key (fail-closed, security-phii-standards §4).
DEFAULT_PARTNER_ARTIFACT_ROOT = "var/partner-artifacts"

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_DEV_TEST_ENVIRONMENTS = frozenset({"dev", "test"})


@dataclass(frozen=True)
class Settings:
    """Runtime settings resolved from the environment at load time."""

    database_url: str = DEFAULT_DATABASE_URL
    app_environment: str = DEFAULT_APP_ENVIRONMENT
    gateway_jwt_verify_enabled: bool = False
    gateway_rate_limit_enabled: bool = False
    gateway_jwt_signing_key: str = ""
    gateway_access_token_ttl_seconds: int = DEFAULT_ACCESS_TOKEN_TTL_SECONDS
    gateway_refresh_token_ttl_seconds: int = DEFAULT_REFRESH_TOKEN_TTL_SECONDS
    gateway_rate_limit_auth_max_requests: int = DEFAULT_AUTH_RATE_LIMIT_MAX_REQUESTS
    gateway_rate_limit_auth_window_seconds: int = DEFAULT_AUTH_RATE_LIMIT_WINDOW_SECONDS
    sms_provider: str = DEFAULT_SMS_PROVIDER
    sms_api_key: str = ""
    sms_base_url: str = ""
    sms_timeout_seconds: float = DEFAULT_SMS_TIMEOUT_SECONDS
    sms_max_retries: int = DEFAULT_SMS_MAX_RETRIES
    sms_circuit_breaker_threshold: int = DEFAULT_SMS_CIRCUIT_BREAKER_THRESHOLD
    sms_circuit_breaker_cooldown_seconds: float = DEFAULT_SMS_CIRCUIT_BREAKER_COOLDOWN_SECONDS
    whatsapp_provider: str = DEFAULT_WHATSAPP_PROVIDER
    whatsapp_api_key: str = ""
    whatsapp_base_url: str = ""
    whatsapp_timeout_seconds: float = DEFAULT_WHATSAPP_TIMEOUT_SECONDS
    whatsapp_max_retries: int = DEFAULT_WHATSAPP_MAX_RETRIES
    whatsapp_circuit_breaker_threshold: int = DEFAULT_WHATSAPP_CIRCUIT_BREAKER_THRESHOLD
    whatsapp_circuit_breaker_cooldown_seconds: float = (
        DEFAULT_WHATSAPP_CIRCUIT_BREAKER_COOLDOWN_SECONDS
    )
    redis_url: str = DEFAULT_REDIS_URL
    redis_consent_ttl_seconds: int = DEFAULT_REDIS_CONSENT_TTL_SECONDS
    # The stub flag for audit retention (GAP-011): 0 means no expiry today; the
    # future 2555-day (7-year) policy is a one-line env change, never a code change.
    audit_retention_days: int = DEFAULT_AUDIT_RETENTION_DAYS
    # Extra browser origins allowed by the CORS middleware, e.g. the Vercel
    # origin of the public demo (deployment plan 4.1). Empty by default, which
    # preserves today's posture: only the localhost dev origin is allowed.
    cors_allowed_origins: tuple[str, ...] = ()
    # Explicit demo-flag: when set, the mock-OTP read-back route answers even
    # in production so the deployed portfolio demo can drive register -> verify
    # (deployment plan 4.3). Fail-closed: never valid with a real provider.
    demo_mode: bool = False
    # Encrypted credential-document store (PHASE-5 T06, #251): local root and
    # the base64 AES-256 key. Root defaults to a repo-local ``var/`` dir; the
    # key is empty unless supplied by the environment (the store derives an
    # ephemeral dev key, never committed).
    partner_artifact_root: str = DEFAULT_PARTNER_ARTIFACT_ROOT
    partner_artifact_key: str = ""

    def __post_init__(self) -> None:
        if self.gateway_jwt_verify_enabled and not self.gateway_jwt_signing_key:
            raise ValueError(
                "gateway_jwt_verify_enabled=True requires GATEWAY_JWT_SIGNING_KEY; "
                "refusing to verify tokens with a blank key."
            )
        if self.gateway_rate_limit_auth_max_requests <= 0:
            raise ValueError("gateway_rate_limit_auth_max_requests must be positive")
        if self.gateway_rate_limit_auth_window_seconds <= 0:
            raise ValueError("gateway_rate_limit_auth_window_seconds must be positive")
        provider = self.sms_provider.strip().lower()
        if provider not in {"mock", "provider"}:
            raise ValueError(
                f"unsupported sms_provider {self.sms_provider!r}; expected 'mock' or 'provider'"
            )
        if self.demo_mode and provider != "mock":
            raise ValueError(
                "demo_mode=True requires sms_provider='mock' (fail-closed): "
                "the demo flag must never ride a real provider"
            )
        if provider == "provider":
            if self.app_environment.strip().lower() in _DEV_TEST_ENVIRONMENTS:
                raise ValueError(
                    "sms_provider='provider' is gated to staging/production: set "
                    "APP_ENVIRONMENT to 'staging' or 'production' before using the "
                    "real EXT-001 path. Refusing it in dev/test."
                )
            if not self.sms_api_key:
                raise ValueError(
                    "sms_provider='provider' requires SMS_API_KEY from the environment"
                )
            if not self.sms_base_url:
                raise ValueError(
                    "sms_provider='provider' requires SMS_BASE_URL from the environment"
                )
        if not (0 < self.sms_timeout_seconds <= 10):
            raise ValueError(
                "sms_timeout_seconds must be in (0, 10] to honour the EXT-001 "
                "call discipline (third-party-integration-standards §1)"
            )
        whatsapp_provider = self.whatsapp_provider.strip().lower()
        if whatsapp_provider not in {"mock", "provider"}:
            raise ValueError(
                f"unsupported whatsapp_provider {self.whatsapp_provider!r}; "
                "expected 'mock' or 'provider'"
            )
        if whatsapp_provider == "provider":
            if self.app_environment.strip().lower() in _DEV_TEST_ENVIRONMENTS:
                raise ValueError(
                    "whatsapp_provider='provider' is gated to staging/production: set "
                    "APP_ENVIRONMENT to 'staging' or 'production' before using the "
                    "real EXT-003 path. Refusing it in dev/test."
                )
            if not self.whatsapp_api_key:
                raise ValueError(
                    "whatsapp_provider='provider' requires WHATSAPP_API_KEY from the environment"
                )
            if not self.whatsapp_base_url:
                raise ValueError(
                    "whatsapp_provider='provider' requires WHATSAPP_BASE_URL from the environment"
                )
        if not (0 < self.whatsapp_timeout_seconds <= 10):
            raise ValueError(
                "whatsapp_timeout_seconds must be in (0, 10] to honour the EXT-003 "
                "call discipline (third-party-integration-standards §1)"
            )
        if self.redis_consent_ttl_seconds <= 0:
            raise ValueError("redis_consent_ttl_seconds must be positive")
        if self.audit_retention_days < 0:
            raise ValueError("audit_retention_days must be zero or positive (0 = no expiry)")
        if self.gateway_access_token_ttl_seconds <= 0:
            raise ValueError("gateway_access_token_ttl_seconds must be positive")
        if self.gateway_refresh_token_ttl_seconds <= 0:
            raise ValueError("gateway_refresh_token_ttl_seconds must be positive")
        if self.sms_circuit_breaker_threshold <= 0:
            raise ValueError("sms_circuit_breaker_threshold must be positive")
        if self.sms_circuit_breaker_cooldown_seconds <= 0:
            raise ValueError("sms_circuit_breaker_cooldown_seconds must be positive")
        if self.whatsapp_circuit_breaker_threshold <= 0:
            raise ValueError("whatsapp_circuit_breaker_threshold must be positive")
        if self.whatsapp_circuit_breaker_cooldown_seconds <= 0:
            raise ValueError("whatsapp_circuit_breaker_cooldown_seconds must be positive")

    @property
    def mock_otp_readback_enabled(self) -> bool:
        """Whether the plaintext mock-OTP read-back surface may be exposed.

        True only for the mock provider in a dev/test environment, or under the
        explicit ``DEMO_MODE`` flag (deployment plan 4.3) - never for the real
        provider. One settled policy behind both the adapter-storage gate and
        the ``/v1/auth/dev/otp`` route gate in ``create_app``.
        """
        return self.sms_provider.strip().lower() == "mock" and (
            self.app_environment.strip().lower() in _DEV_TEST_ENVIRONMENTS or self.demo_mode
        )


def _env_bool(name: str, default: bool) -> bool:
    """Parse a boolean environment variable, falling back to ``default``."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE_VALUES


def _env_float(name: str, default: float) -> float:
    """Parse a float environment variable, falling back to ``default``."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return float(raw)


def _env_int(name: str, default: int) -> int:
    """Parse an integer environment variable, falling back to ``default``."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return int(raw)


def _env_csv(name: str) -> tuple[str, ...]:
    """Parse a comma-separated environment variable into trimmed entries.

    Splits on commas, strips whitespace, and drops empties; an unset or empty
    value yields ``()`` so the caller's default posture is untouched.
    """
    raw = os.environ.get(name)
    if raw is None:
        return ()
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def get_settings() -> Settings:
    """Build ``Settings`` from environment variables.

    ``create_app`` resolves this and stores it on ``app.state.settings`` once
    per process; the worker (#30) and gateway (#29) consume that resolved value
    rather than re-reading the environment. Both gateway middleware default to
    disabled (PHASE-1 T7b, #29); the Phase 2 real ``jwt_verify`` (ticket #59)
    additionally requires ``GATEWAY_JWT_SIGNING_KEY`` - ``Settings`` refuses
    the flag otherwise (fail-closed boot, never a blank-key verify).
    """
    return Settings(
        database_url=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
        app_environment=os.environ.get("APP_ENVIRONMENT", DEFAULT_APP_ENVIRONMENT),
        gateway_jwt_verify_enabled=_env_bool("GATEWAY_JWT_VERIFY_ENABLED", False),
        gateway_rate_limit_enabled=_env_bool("GATEWAY_RATE_LIMIT_ENABLED", False),
        gateway_jwt_signing_key=os.environ.get("GATEWAY_JWT_SIGNING_KEY", ""),
        gateway_access_token_ttl_seconds=_env_int(
            "GATEWAY_ACCESS_TOKEN_TTL_SECONDS", DEFAULT_ACCESS_TOKEN_TTL_SECONDS
        ),
        gateway_refresh_token_ttl_seconds=_env_int(
            "GATEWAY_REFRESH_TOKEN_TTL_SECONDS", DEFAULT_REFRESH_TOKEN_TTL_SECONDS
        ),
        gateway_rate_limit_auth_max_requests=_env_int(
            "GATEWAY_RATE_LIMIT_AUTH_MAX_REQUESTS", DEFAULT_AUTH_RATE_LIMIT_MAX_REQUESTS
        ),
        gateway_rate_limit_auth_window_seconds=_env_int(
            "GATEWAY_RATE_LIMIT_AUTH_WINDOW_SECONDS", DEFAULT_AUTH_RATE_LIMIT_WINDOW_SECONDS
        ),
        sms_provider=os.environ.get("SMS_PROVIDER", DEFAULT_SMS_PROVIDER),
        sms_api_key=os.environ.get("SMS_API_KEY", ""),
        sms_base_url=os.environ.get("SMS_BASE_URL", ""),
        sms_timeout_seconds=_env_float("SMS_TIMEOUT_SECONDS", DEFAULT_SMS_TIMEOUT_SECONDS),
        sms_max_retries=_env_int("SMS_MAX_RETRIES", DEFAULT_SMS_MAX_RETRIES),
        sms_circuit_breaker_threshold=_env_int(
            "SMS_CIRCUIT_BREAKER_THRESHOLD", DEFAULT_SMS_CIRCUIT_BREAKER_THRESHOLD
        ),
        sms_circuit_breaker_cooldown_seconds=_env_float(
            "SMS_CIRCUIT_BREAKER_COOLDOWN_SECONDS",
            DEFAULT_SMS_CIRCUIT_BREAKER_COOLDOWN_SECONDS,
        ),
        whatsapp_provider=os.environ.get("WHATSAPP_PROVIDER", DEFAULT_WHATSAPP_PROVIDER),
        whatsapp_api_key=os.environ.get("WHATSAPP_API_KEY", ""),
        whatsapp_base_url=os.environ.get("WHATSAPP_BASE_URL", ""),
        whatsapp_timeout_seconds=_env_float(
            "WHATSAPP_TIMEOUT_SECONDS", DEFAULT_WHATSAPP_TIMEOUT_SECONDS
        ),
        whatsapp_max_retries=_env_int("WHATSAPP_MAX_RETRIES", DEFAULT_WHATSAPP_MAX_RETRIES),
        whatsapp_circuit_breaker_threshold=_env_int(
            "WHATSAPP_CIRCUIT_BREAKER_THRESHOLD",
            DEFAULT_WHATSAPP_CIRCUIT_BREAKER_THRESHOLD,
        ),
        whatsapp_circuit_breaker_cooldown_seconds=_env_float(
            "WHATSAPP_CIRCUIT_BREAKER_COOLDOWN_SECONDS",
            DEFAULT_WHATSAPP_CIRCUIT_BREAKER_COOLDOWN_SECONDS,
        ),
        redis_url=os.environ.get("REDIS_URL", DEFAULT_REDIS_URL),
        redis_consent_ttl_seconds=_env_int(
            "REDIS_CONSENT_TTL_SECONDS", DEFAULT_REDIS_CONSENT_TTL_SECONDS
        ),
        audit_retention_days=_env_int("AUDIT_RETENTION_DAYS", DEFAULT_AUDIT_RETENTION_DAYS),
        cors_allowed_origins=_env_csv("CORS_ALLOWED_ORIGINS"),
        demo_mode=_env_bool("DEMO_MODE", False),
        partner_artifact_root=os.environ.get(
            "PARTNER_ARTIFACT_ROOT", DEFAULT_PARTNER_ARTIFACT_ROOT
        ),
        partner_artifact_key=os.environ.get("PARTNER_ARTIFACT_KEY", ""),
    )
