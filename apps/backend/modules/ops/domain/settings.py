"""MOD-014: domain settings registry for effective settings read (#771) and feature flags (#773).

Precedence is database override, then environment, then default.
Only allowlisted operational AI knobs are editable (writes land in #772).
Provider/model/api key/base URL/signing keys/SMTP/Slack/composition-root gates
are read-only and never returned raw. Secrets and boot-time values are
environment-only and read-only.

Feature flags carry a runtime or restart-required type. Runtime flags are
admin-editable; restart-required flags are read-only with an explanation.
Flag reads are operator-visible.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.config import Settings


class SettingSource(StrEnum):
    """Source of an effective setting value."""

    DATABASE = "database"
    ENVIRONMENT = "environment"
    DEFAULT = "default"


class SettingKind(StrEnum):
    """How a setting is classified."""

    AI_EDITABLE = "ai_editable"
    READ_ONLY = "read_only"


@dataclass(frozen=True)
class SettingSpec:
    """Metadata describing a single effective setting."""

    key: str
    kind: SettingKind
    restart_required: bool
    editable: bool
    sensitive: bool = False
    description: str | None = None


@dataclass(frozen=True)
class EffectiveSetting:
    """Resolved effective setting with source metadata."""

    key: str
    value: object | None
    source: str
    editable: bool
    restart_required: bool


class FeatureFlagKind(StrEnum):
    """Type of feature flag."""

    RUNTIME = "runtime"
    RESTART_REQUIRED = "restart_required"


@dataclass(frozen=True)
class FeatureFlag:
    """Feature flag with type and metadata."""

    flag_key: str
    enabled: bool
    flag_kind: FeatureFlagKind
    description: str | None
    updated_by: int | None
    created_at: str
    updated_at: str

    @property
    def editable(self) -> bool:
        """Only runtime flags are editable."""
        return self.flag_kind == FeatureFlagKind.RUNTIME


@dataclass(frozen=True)
class FeatureFlagRead:
    """Feature flag read response."""

    flag_key: str
    enabled: bool
    flag_kind: str
    description: str | None
    editable: bool
    updated_at: str


@dataclass(frozen=True)
class FeatureFlagWriteRequest:
    """Feature flag write request."""

    flag_key: str
    enabled: bool


@dataclass(frozen=True)
class FeatureFlagWriteResponse:
    """Feature flag write response."""

    flag_key: str
    enabled: bool
    flag_kind: str
    version: int


# Allowlisted operational AI knobs that are editable (writes in #772)
EDITABLE_AI_KEYS: frozenset[str] = frozenset(
    {
        "ai.monthly_budget_paise",
        "ai.budget_alert_threshold_pct",
        "ai.timeout_seconds",
        "ai.fallback_enabled",
    }
)


# Read-only keys that are never returned raw
READ_ONLY_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "ai.provider",
        "ai.model",
        "ai.api_key",
        "ai.base_url",
        "gateway.jwt_signing_key",
        "iam.mfa_secret_key",
        "langfuse.secret_key",
        "smtp.credentials",
        "slack.webhook_url",
    }
)


# Composition-root gates / boot-time values are read-only
COMPOSITION_ROOT_READ_ONLY_KEYS: frozenset[str] = frozenset(
    {
        "gateway.jwt_verify_enabled",
        "gateway.rate_limit_enabled",
        "observability.enabled",
        "dispatcher.in_process_enabled",
    }
)


ALL_READ_ONLY_KEYS: frozenset[str] = READ_ONLY_SENSITIVE_KEYS | COMPOSITION_ROOT_READ_ONLY_KEYS


def is_editable(key: str) -> bool:
    return key in EDITABLE_AI_KEYS


def is_read_only(key: str) -> bool:
    return key in ALL_READ_ONLY_KEYS


def requires_restart(key: str) -> bool:
    if key in READ_ONLY_SENSITIVE_KEYS:
        return True
    if key in COMPOSITION_ROOT_READ_ONLY_KEYS:
        return True
    if key in EDITABLE_AI_KEYS:
        return False
    return False


def get_setting_spec(key: str) -> SettingSpec:
    sensitive = key in READ_ONLY_SENSITIVE_KEYS
    editable = is_editable(key)
    return SettingSpec(
        key=key,
        kind=SettingKind.AI_EDITABLE if editable else SettingKind.READ_ONLY,
        restart_required=requires_restart(key),
        editable=editable,
        sensitive=sensitive,
    )


class OpsSettingsCache:
    """In-process TTL cache for effective settings."""

    def __init__(self, ttl_seconds: int = 30) -> None:
        self._ttl_seconds = ttl_seconds
        self._cached_at: float | None = None
        self._cached: list[EffectiveSetting] | None = None

    @property
    def ttl_seconds(self) -> int:
        return self._ttl_seconds

    def get(self) -> list[EffectiveSetting] | None:
        if self._cached is None or self._cached_at is None:
            return None
        if time.monotonic() - self._cached_at > self._ttl_seconds:
            self._cached = None
            self._cached_at = None
            return None
        return self._cached

    def set(self, value: list[EffectiveSetting]) -> None:
        self._cached = value
        self._cached_at = time.monotonic()


class EffectiveSettingsResolver:
    """Resolve effective settings with precedence: database override → environment → default."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _get_from_env_or_default(self, key: str) -> tuple[object | None, str]:
        # For editable AI knobs - check settings attributes
        if key == "ai.monthly_budget_paise":
            return getattr(
                self._settings, "ai_monthly_budget_paise", None
            ), SettingSource.DEFAULT.value
        if key == "ai.budget_alert_threshold_pct":
            return getattr(
                self._settings, "observability_budget_alert_threshold_pct", None
            ), SettingSource.DEFAULT.value
        if key == "ai.timeout_seconds":
            return getattr(self._settings, "ai_timeout_seconds", None), SettingSource.DEFAULT.value
        if key == "ai.fallback_enabled":
            # derive from fallback config
            if getattr(self._settings, "ai_fallback_models", None):
                return True, SettingSource.DEFAULT.value
            return getattr(
                self._settings, "ai_fallback_enabled", False
            ), SettingSource.DEFAULT.value
        # Read-only keys
        if key == "ai.provider":
            return getattr(self._settings, "ai_provider", None), SettingSource.DEFAULT.value
        if key == "ai.model":
            return getattr(self._settings, "ai_model", None), SettingSource.DEFAULT.value
        if key == "ai.api_key":
            return getattr(self._settings, "ai_api_key", None), SettingSource.DEFAULT.value
        if key == "ai.base_url":
            return getattr(self._settings, "ai_base_url", None), SettingSource.DEFAULT.value
        if key == "gateway.jwt_signing_key":
            return getattr(
                self._settings, "gateway_jwt_signing_key", None
            ), SettingSource.DEFAULT.value
        if key == "iam.mfa_secret_key":
            return getattr(self._settings, "iam_mfa_secret_key", None), SettingSource.DEFAULT.value
        if key == "langfuse.secret_key":
            return getattr(self._settings, "langfuse_secret_key", None), SettingSource.DEFAULT.value
        if key == "smtp.credentials":
            return getattr(self._settings, "smtp_credentials", None), SettingSource.DEFAULT.value
        if key == "slack.webhook_url":
            return getattr(self._settings, "slack_webhook_url", None), SettingSource.DEFAULT.value
        if key == "gateway.jwt_verify_enabled":
            return getattr(
                self._settings, "gateway_jwt_verify_enabled", None
            ), SettingSource.DEFAULT.value
        if key == "gateway.rate_limit_enabled":
            return getattr(
                self._settings, "gateway_rate_limit_enabled", None
            ), SettingSource.DEFAULT.value
        if key == "observability.enabled":
            return getattr(
                self._settings, "observability_enabled", None
            ), SettingSource.DEFAULT.value
        if key == "dispatcher.in_process_enabled":
            return getattr(
                self._settings, "dispatcher_in_process_enabled", None
            ), SettingSource.DEFAULT.value
        return None, SettingSource.DEFAULT.value

    def resolve_all(self, db_overrides: dict[str, Any]) -> list[EffectiveSetting]:
        results: list[EffectiveSetting] = []
        # Collect all keys we care about
        all_keys = (
            list(EDITABLE_AI_KEYS)
            + list(READ_ONLY_SENSITIVE_KEYS)
            + list(COMPOSITION_ROOT_READ_ONLY_KEYS)
        )
        for key in sorted(set(all_keys)):
            source = SettingSource.DEFAULT.value
            value: object | None = None
            # Check DB override first (precedence 1)
            if key in db_overrides and db_overrides[key] is not None:
                value = db_overrides[key]
                source = SettingSource.DATABASE.value
            else:
                # Check env/default via settings
                val, _ = self._get_from_env_or_default(key)
                if val is not None and not (isinstance(val, str) and val == ""):
                    # If it came from env, mark as environment; otherwise default
                    # For simplicity in this context, treat as environment or default
                    source = (
                        SettingSource.ENVIRONMENT.value
                        if key in READ_ONLY_SENSITIVE_KEYS or key in COMPOSITION_ROOT_READ_ONLY_KEYS
                        else SettingSource.DEFAULT.value
                    )
                    value = val
                else:
                    source = SettingSource.DEFAULT.value
                    value = val
            spec = get_setting_spec(key)
            # Never return raw for secrets/read-only sensitive
            if key in READ_ONLY_SENSITIVE_KEYS or key in ALL_READ_ONLY_KEYS:
                # For sensitive/read-only: "read-only/secret values are never returned raw;
                # effective values are cached in-process". Route returns them with
                # source/editable/restart_required; value should be null/masked.
                value = None
            results.append(
                EffectiveSetting(
                    key=key,
                    value=value,
                    source=source,
                    editable=spec.editable,
                    restart_required=spec.restart_required,
                )
            )
        return results


def validate_feature_flag_write(flag: FeatureFlag, enabled: bool) -> None:
    """Validate a feature flag write request.

    Raises:
        InvalidFeatureFlagWriteError: If the flag is restart-required (not editable).
    """
    from modules.ops.domain.exceptions import InvalidFeatureFlagWriteError

    if not flag.editable:
        raise InvalidFeatureFlagWriteError(
            flag.flag_key,
            "flag is restart-required and cannot be edited at runtime; "
            "restart the service to change",
        )
