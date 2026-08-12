"""Shared application settings (PHASE-1 T7a, #28).

Env-driven configuration consumed by the app shell now and by the worker (#30)
and gateway (#29) next. Plain frozen dataclass over ``os.environ`` - no extra
dependency beyond the declared stack (cost floor ``NFR-001``).
"""

import os
from dataclasses import dataclass

DEFAULT_DATABASE_URL = "postgresql+asyncpg://caresetu:caresetu@localhost:5432/caresetu"
DEFAULT_TEST_PRINCIPAL_HEADER = "X-CareSetu-Test-Principal"
DEFAULT_APP_ENVIRONMENT = "production"
DEFAULT_SMS_PROVIDER = "mock"
DEFAULT_SMS_TIMEOUT_SECONDS = 10.0
DEFAULT_SMS_MAX_RETRIES = 3

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_DEV_TEST_ENVIRONMENTS = frozenset({"dev", "test"})


@dataclass(frozen=True)
class Settings:
    """Runtime settings resolved from the environment at load time."""

    database_url: str = DEFAULT_DATABASE_URL
    app_environment: str = DEFAULT_APP_ENVIRONMENT
    gateway_jwt_verify_enabled: bool = False
    gateway_jwt_test_header: str = DEFAULT_TEST_PRINCIPAL_HEADER
    gateway_rate_limit_enabled: bool = False
    sms_provider: str = DEFAULT_SMS_PROVIDER
    sms_api_key: str = ""
    sms_base_url: str = ""
    sms_timeout_seconds: float = DEFAULT_SMS_TIMEOUT_SECONDS
    sms_max_retries: int = DEFAULT_SMS_MAX_RETRIES

    def __post_init__(self) -> None:
        if (
            self.gateway_jwt_verify_enabled
            and self.app_environment.strip().lower() not in _DEV_TEST_ENVIRONMENTS
        ):
            raise ValueError(
                "gateway_jwt_verify_enabled=True requires a dev/test marker: set "
                "APP_ENVIRONMENT to 'dev' or 'test'. Refusing to enable the "
                "test-header auth backdoor outside a dev/test deployment."
            )
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
    rather than re-reading the environment. Both gateway stubs default to
    disabled (PHASE-1 T7b, #29). Enabling the ``jwt_verify`` test-header stub
    additionally requires ``APP_ENVIRONMENT`` set to ``dev`` or ``test``
    (ticket #48) - ``Settings`` refuses the flag otherwise.
    """
    return Settings(
        database_url=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
        app_environment=os.environ.get("APP_ENVIRONMENT", DEFAULT_APP_ENVIRONMENT),
        gateway_jwt_verify_enabled=_env_bool("GATEWAY_JWT_VERIFY_ENABLED", False),
        gateway_jwt_test_header=os.environ.get(
            "GATEWAY_JWT_TEST_HEADER", DEFAULT_TEST_PRINCIPAL_HEADER
        ),
        gateway_rate_limit_enabled=_env_bool("GATEWAY_RATE_LIMIT_ENABLED", False),
        sms_provider=os.environ.get("SMS_PROVIDER", DEFAULT_SMS_PROVIDER),
        sms_api_key=os.environ.get("SMS_API_KEY", ""),
        sms_base_url=os.environ.get("SMS_BASE_URL", ""),
        sms_timeout_seconds=_env_float("SMS_TIMEOUT_SECONDS", DEFAULT_SMS_TIMEOUT_SECONDS),
        sms_max_retries=_env_int("SMS_MAX_RETRIES", DEFAULT_SMS_MAX_RETRIES),
    )
