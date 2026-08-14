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
        if self.gateway_access_token_ttl_seconds <= 0:
            raise ValueError("gateway_access_token_ttl_seconds must be positive")
        if self.gateway_refresh_token_ttl_seconds <= 0:
            raise ValueError("gateway_refresh_token_ttl_seconds must be positive")
        if self.sms_circuit_breaker_threshold <= 0:
            raise ValueError("sms_circuit_breaker_threshold must be positive")
        if self.sms_circuit_breaker_cooldown_seconds <= 0:
            raise ValueError("sms_circuit_breaker_cooldown_seconds must be positive")


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
    )
