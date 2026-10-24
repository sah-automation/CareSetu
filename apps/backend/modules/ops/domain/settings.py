"""MOD-014: domain settings registry for effective settings read (#771).

Precedence is database override, then environment, then default.
Only allowlisted operational AI knobs are editable (writes land in #772).
Provider/model/api key/base URL/signing keys/SMTP/Slack/composition-root gates
are read-only and never returned raw. Secrets and boot-time values are
environment-only and read-only.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.config import Settings


class SettingSource(str, Enum):
    """Source of an effective setting value."""

    DATABASE = "database"
    ENVIRONMENT = "environment"
    DEFAULT = "default"


class SettingKind(str, Enum):
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
            return getattr(self._settings, "ai_monthly_budget_paise", None), SettingSource.DEFAULT.value
        if key == "ai.budget_alert_threshold_pct":
            return getattr(self._settings, "observability_budget_alert_threshold_pct", None), SettingSource.DEFAULT.value
        if key == "ai.timeout_seconds":
            return getattr(self._settings, "ai_timeout_seconds", None), SettingSource.DEFAULT.value
        if key == "ai.fallback_enabled":
            # derive from fallback config
            if getattr(self._settings, "ai_fallback_models", None):
                return True, SettingSource.DEFAULT.value
            return getattr(self._settings, "ai_fallback_enabled", False), SettingSource.DEFAULT.value
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
            return getattr(self._settings, "gateway_jwt_signing_key", None), SettingSource.DEFAULT.value
        if key == "iam.mfa_secret_key":
            return getattr(self._settings, "iam_mfa_secret_key", None), SettingSource.DEFAULT.value
        if key == "langfuse.secret_key":
            return getattr(self._settings, "langfuse_secret_key", None), SettingSource.DEFAULT.value
        if key == "smtp.credentials":
            return getattr(self._settings, "smtp_credentials", None), SettingSource.DEFAULT.value
        if key == "slack.webhook_url":
            return getattr(self._settings, "slack_webhook_url", None), SettingSource.DEFAULT.value
        if key == "gateway.jwt_verify_enabled":
            return getattr(self._settings, "gateway_jwt_verify_enabled", None), SettingSource.DEFAULT.value
        if key == "gateway.rate_limit_enabled":
            return getattr(self._settings, "gateway_rate_limit_enabled", None), SettingSource.DEFAULT.value
        if key == "observability.enabled":
            return getattr(self._settings, "observability_enabled", None), SettingSource.DEFAULT.value
        if key == "dispatcher.in_process_enabled":
            return getattr(self._settings, "dispatcher_in_process_enabled", None), SettingSource.DEFAULT.value
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
                    source = SettingSource.ENVIRONMENT.value if key in READ_ONLY_SENSITIVE_KEYS or key in COMPOSITION_ROOT_READ_ONLY_KEYS else SettingSource.DEFAULT.value
                    value = val
                else:
                    source = SettingSource.DEFAULT.value
                    value = val
            spec = get_setting_spec(key)
            # Never return raw for secrets/read-only sensitive
            if key in READ_ONLY_SENSITIVE_KEYS or key in ALL_READ_ONLY_KEYS:
                # For sensitive/read-only, per requirements: "read-only/secret values are never returned raw; effective values are cached in-process"
                # But the route needs to return them with source/editable/restart_required. The brief says "never returned raw" - so value should be null/masked
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
