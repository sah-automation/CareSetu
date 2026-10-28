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


@dataclass(frozen=True)
class SettingHistoryEntry:
    """One append-only setting history row (#772/#798)."""

    setting_key: str
    value: object | None
    version: int
    changed_by: int | None
    changed_at: str


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


# Alert kinds from observability (rollup + consumer)
ALERT_KINDS: frozenset[str] = frozenset(
    {
        "ai_budget",
        "provider_health_drop",
        "breaker_open",
        "outbox_backlog",
        "outbox_dead_letter",
        "queue_age",
        "cost_outlier",
        "error_rate_high",
        "provider_rate_limited",
        "latency_objective_breach",
        "audit_tamper",
        "ai_egress",
        # Security detector (#779): five threshold kinds and four irreversible
        # incident kinds, including the reserved webhook-signature kind (#781).
        "auth_failure_high",
        "operator_mfa_failure_high",
        "record_denial_high",
        "rate_limit_high",
        "prompt_injection_high",
        "otp_lockout",
        "operator_mfa_lockout",
        "consent_revocation",
        "webhook_signature_failure",
    }
)


# Valid routing targets for notification routing
NOTIFICATION_ROUTING_TARGETS: frozenset[str] = frozenset({"slack", "email", "none"})


# Allowlisted operational AI knobs that are editable (writes in #772)
EDITABLE_AI_KEYS: frozenset[str] = frozenset(
    {
        "ai.monthly_budget_paise",
        "ai.budget_alert_threshold_pct",
        "ai.timeout_seconds",
        "ai.fallback_enabled",
    }
)


# Allowlisted notification routing settings that are editable (writes in #774)
EDITABLE_NOTIFICATION_KEYS: frozenset[str] = frozenset(
    {
        "notification.email.recipients",
        "notification.channels.slack.enabled",
        "notification.channels.email.enabled",
    }
    | {f"notification.routing.{kind}" for kind in ALERT_KINDS}
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
ALL_EDITABLE_KEYS: frozenset[str] = EDITABLE_AI_KEYS | EDITABLE_NOTIFICATION_KEYS


def is_editable(key: str) -> bool:
    return key in ALL_EDITABLE_KEYS


def is_read_only(key: str) -> bool:
    return key in ALL_READ_ONLY_KEYS


def requires_restart(key: str) -> bool:
    if key in READ_ONLY_SENSITIVE_KEYS:
        return True
    if key in COMPOSITION_ROOT_READ_ONLY_KEYS:
        return True
    if key in EDITABLE_AI_KEYS or key in EDITABLE_NOTIFICATION_KEYS:
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

    def invalidate(self) -> None:
        """Drop the cached effective values so the next read resolves fresh.

        A write must invalidate to *nothing*, not to an empty list: an empty
        list is a valid cached payload and would make the next effective read
        answer "no settings" for the whole TTL window.
        """
        self._cached = None
        self._cached_at = None


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

    def _get_notification_default(self, key: str) -> tuple[object | None, str]:
        """Get default values for notification settings (no env config)."""
        if key.startswith("notification.routing."):
            return "none", SettingSource.DEFAULT.value
        if key == "notification.email.recipients":
            return [], SettingSource.DEFAULT.value
        if key == "notification.channels.slack.enabled":
            return False, SettingSource.DEFAULT.value
        if key == "notification.channels.email.enabled":
            return False, SettingSource.DEFAULT.value
        return None, SettingSource.DEFAULT.value

    def resolve_all(self, db_overrides: dict[str, Any]) -> list[EffectiveSetting]:
        results: list[EffectiveSetting] = []
        # Collect all keys we care about
        all_keys = (
            list(EDITABLE_AI_KEYS)
            + list(EDITABLE_NOTIFICATION_KEYS)
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
                    # Check notification defaults only for notification keys
                    if key.startswith("notification."):
                        val, src = self._get_notification_default(key)
                        if val is not None:
                            source = src
                            value = val
                        else:
                            source = SettingSource.DEFAULT.value
                            value = None
                    else:
                        source = SettingSource.DEFAULT.value
                        value = None
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


def validate_ai_setting(key: str, value: object) -> None:
    """Validate an allowlisted operational AI knob write (#772).

    The knobs mirror the boot-time config validation so a database override can
    never carry a value the process would have refused from the environment.

    Raises:
        ValueError: If the value is invalid for the given key.
    """
    if key == "ai.monthly_budget_paise":
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError("AI monthly budget must be a positive integer (paise)")
    elif key == "ai.budget_alert_threshold_pct":
        if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= 100:
            raise ValueError("AI budget alert threshold must be an integer in (0, 100]")
    elif key == "ai.timeout_seconds":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= 30:
            raise ValueError("AI timeout must be a number of seconds in (0, 30]")
    elif key == "ai.fallback_enabled":
        if not isinstance(value, bool):
            raise ValueError("AI fallback enabled must be a boolean")
    else:
        raise ValueError(f"Unknown AI setting key: {key}")


def validate_notification_routing_value(value: str) -> None:
    """Validate a notification routing value.

    Args:
        value: The routing value to validate ("slack", "email", or "none").

    Raises:
        ValueError: If the value is not a valid routing target.
    """
    if value not in NOTIFICATION_ROUTING_TARGETS:
        valid = ", ".join(sorted(NOTIFICATION_ROUTING_TARGETS))
        raise ValueError(f"Invalid routing target '{value}'. Must be one of: {valid}")


def validate_email_recipients(value: list[str]) -> None:
    """Validate email recipients list.

    Args:
        value: List of email addresses.

    Raises:
        ValueError: If the value is not a valid list of email addresses.
    """
    if not isinstance(value, list):
        raise ValueError("Email recipients must be a list")
    for email in value:
        if not isinstance(email, str) or "@" not in email:
            raise ValueError(f"Invalid email address: {email}")


def validate_channel_enabled(value: bool) -> None:
    """Validate channel enabled value.

    Args:
        value: Boolean value.

    Raises:
        ValueError: If the value is not a boolean.
    """
    if not isinstance(value, bool):
        raise ValueError("Channel enabled must be a boolean")


def validate_notification_setting(key: str, value: object) -> None:
    """Validate a notification setting write.

    Args:
        key: The setting key.
        value: The value to validate.

    Raises:
        ValueError: If the value is invalid for the given key.
    """
    if key.startswith("notification.routing."):
        if not isinstance(value, str):
            raise ValueError(f"Routing value for '{key}' must be a string")
        validate_notification_routing_value(value)
    elif key == "notification.email.recipients":
        if not isinstance(value, list):
            raise ValueError("Email recipients must be a list")
        validate_email_recipients(value)
    elif key in ("notification.channels.slack.enabled", "notification.channels.email.enabled"):
        if not isinstance(value, bool):
            raise ValueError("Channel enabled must be a boolean")
        validate_channel_enabled(value)
    else:
        raise ValueError(f"Unknown notification setting key: {key}")
