"""Unit tests for the ops AI setting bounds and cache invalidation (#772/#798)."""

from __future__ import annotations

import pytest

from modules.ops.domain.settings import (
    EDITABLE_AI_KEYS,
    READ_ONLY_SENSITIVE_KEYS,
    EffectiveSetting,
    OpsSettingsCache,
    validate_ai_setting,
    validate_cache_redis_setting,
)

_MOCK_CATALOG: list[dict] = [
    {
        "id": "mock",
        "provider": "mock",
        "chat_models": ["mock-model"],
        "asr_models": [],
    },
    {
        "id": "openai_compatible",
        "provider": "openai_compatible",
        "chat_models": ["openai/gpt-oss-120b", "gemini-3.6-flash", "mock-model"],
        "asr_models": ["whisper-large-v3-turbo", "whisper-large-v3"],
    },
]

_VALID_PRICING_TABLE: dict[str, tuple] = {
    "mock-model": (0, 0),
    "openai/gpt-oss-120b": (1, 2),
    "custom-model-x": (5, 10),
}


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


class TestAiSettingAllowlistClassification:
    def test_provider_and_model_are_no_longer_read_only_sensitive(self) -> None:
        assert "ai.provider" not in READ_ONLY_SENSITIVE_KEYS
        assert "ai.model" not in READ_ONLY_SENSITIVE_KEYS

    def test_new_ai_keys_are_editable(self) -> None:
        for key in (
            "ai.provider",
            "ai.model",
            "ai.fallback_provider",
            "ai.fallback_model",
            "ai.asr_model",
            "ai.pricing_table",
        ):
            assert key in EDITABLE_AI_KEYS


class TestValidateAiSettingWithCatalog:
    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("ai.provider", "mock"),
            ("ai.provider", "openai_compatible"),
            ("ai.model", "mock-model"),
            ("ai.model", "openai/gpt-oss-120b"),
            ("ai.model", "gemini-3.6-flash"),
            ("ai.fallback_provider", "mock"),
            ("ai.fallback_provider", "openai_compatible"),
            ("ai.fallback_provider", ""),
            ("ai.fallback_model", "mock-model"),
            ("ai.asr_model", "whisper-large-v3-turbo"),
            ("ai.asr_model", "whisper-large-v3"),
            ("ai.pricing_table", "mock-model:0:0"),
            ("ai.pricing_table", "openai/gpt-oss-120b:1.5:2.5"),
            ("ai.pricing_table", ""),
        ],
    )
    def test_accepts_valid_ai_values(self, key: str, value: object) -> None:
        validate_ai_setting(key, value, catalog=_MOCK_CATALOG, pricing_table=_VALID_PRICING_TABLE)

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("ai.provider", "unknown_provider"),
            ("ai.provider", ""),
            ("ai.provider", None),
            ("ai.model", "totally-custom-model"),
            ("ai.fallback_provider", "unknown_provider"),
            ("ai.fallback_model", "totally-custom-model"),
            ("ai.asr_model", "unknown-asr"),
            ("ai.asr_model", ""),
        ],
    )
    def test_rejects_invalid_ai_values(self, key: str, value: object) -> None:
        with pytest.raises(ValueError):
            validate_ai_setting(
                key, value, catalog=_MOCK_CATALOG, pricing_table=_VALID_PRICING_TABLE
            )

    def test_custom_model_accepted_with_pricing_entry(self) -> None:
        # custom-model-x is not in the catalog but has a pricing entry
        validate_ai_setting(
            "ai.model",
            "custom-model-x",
            catalog=_MOCK_CATALOG,
            pricing_table=_VALID_PRICING_TABLE,
        )
        validate_ai_setting(
            "ai.fallback_model",
            "custom-model-x",
            catalog=_MOCK_CATALOG,
            pricing_table=_VALID_PRICING_TABLE,
        )

    def test_custom_model_rejected_without_pricing_entry(self) -> None:
        with pytest.raises(ValueError):
            validate_ai_setting(
                "ai.model",
                "totally-custom-model",
                catalog=_MOCK_CATALOG,
                pricing_table={},
            )

    @pytest.mark.parametrize(
        ("value",),
        [
            ("bad-entry",),
            ("model:not-a-number:1",),
            ("model:1:not-a-number",),
            ("model:-1:1",),
            ("model:1:-1",),
            (":1:1",),
        ],
    )
    def test_rejects_malformed_or_negative_pricing_table(self, value: str) -> None:
        with pytest.raises(ValueError):
            validate_ai_setting(
                "ai.pricing_table",
                value,
                catalog=_MOCK_CATALOG,
                pricing_table={},
            )

    def test_rejects_non_string_pricing_table(self) -> None:
        with pytest.raises(ValueError):
            validate_ai_setting(
                "ai.pricing_table",
                {"model": "1:1"},
                catalog=_MOCK_CATALOG,
                pricing_table={},
            )

    def test_unknown_key_still_rejected(self) -> None:
        with pytest.raises(ValueError, match="Unknown AI setting key"):
            validate_ai_setting("ai.unknown_key", 1, catalog=_MOCK_CATALOG)
