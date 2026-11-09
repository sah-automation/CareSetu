"""Unit tests for the ops AI setting bounds and cache invalidation (#772/#798)."""

from __future__ import annotations

import pytest

from modules.ops.domain.settings import (
    EffectiveSetting,
    OpsSettingsCache,
    validate_ai_setting,
    validate_cache_redis_setting,
)


class TestValidateAiSetting:
    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("ai.monthly_budget_paise", 1),
            ("ai.monthly_budget_paise", 200_000),
            ("ai.budget_alert_threshold_pct", 1),
            ("ai.budget_alert_threshold_pct", 100),
            ("ai.timeout_seconds", 0.5),
            ("ai.timeout_seconds", 30),
            ("ai.fallback_enabled", True),
            ("ai.fallback_enabled", False),
        ],
    )
    def test_accepts_in_bounds_values(self, key: str, value: object) -> None:
        validate_ai_setting(key, value)

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("ai.monthly_budget_paise", 0),
            ("ai.monthly_budget_paise", -1),
            ("ai.monthly_budget_paise", 1.5),
            ("ai.monthly_budget_paise", True),
            ("ai.budget_alert_threshold_pct", 0),
            ("ai.budget_alert_threshold_pct", 101),
            ("ai.timeout_seconds", 0),
            ("ai.timeout_seconds", -1),
            ("ai.timeout_seconds", 30.1),
            ("ai.fallback_enabled", "true"),
            ("ai.fallback_enabled", 1),
            ("ai.unknown", 1),
        ],
    )
    def test_rejects_out_of_bounds_values(self, key: str, value: object) -> None:
        with pytest.raises(ValueError):
            validate_ai_setting(key, value)


class TestValidateCacheRedisSetting:
    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("cache.enabled", True),
            ("cache.enabled", False),
            ("redis.enabled", True),
            ("redis.enabled", False),
        ],
    )
    def test_accepts_boolean_values(self, key: str, value: object) -> None:
        validate_cache_redis_setting(key, value)

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("cache.enabled", "true"),
            ("cache.enabled", "false"),
            ("cache.enabled", 1),
            ("cache.enabled", 0),
            ("cache.enabled", None),
            ("cache.enabled", {}),
            ("redis.enabled", "true"),
            ("redis.enabled", "false"),
            ("redis.enabled", 1),
            ("redis.enabled", 0),
            ("redis.enabled", None),
            ("redis.enabled", {}),
        ],
    )
    def test_rejects_non_boolean_values(self, key: str, value: object) -> None:
        with pytest.raises(ValueError):
            validate_cache_redis_setting(key, value)

    def test_rejects_unknown_key(self) -> None:
        with pytest.raises(ValueError, match="Unknown cache/redis setting key"):
            validate_cache_redis_setting("cache.unknown", True)


class TestOpsSettingsCache:
    def test_invalidate_drops_the_cached_payload(self) -> None:
        cache = OpsSettingsCache(ttl_seconds=30)
        cache.set(
            [
                EffectiveSetting(
                    key="ai.timeout_seconds",
                    value=30,
                    source="default",
                    editable=True,
                    restart_required=False,
                )
            ]
        )
        assert cache.get() is not None

        cache.invalidate()

        assert cache.get() is None
