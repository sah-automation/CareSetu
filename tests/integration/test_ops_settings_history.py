"""Integration tests for ops settings writes, history and cache refresh (#772/#798)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from modules.intake.ai_config import AiConfigResolver
from modules.ops.domain.exceptions import InvalidSettingWriteError
from modules.ops.domain.settings import EffectiveSetting, SettingHistoryEntry
from modules.ops.facade import OpsFacade
from modules.ops.schema.models import ops_outbox


@pytest.fixture(autouse=True)
async def _reset_ops_settings(engine: AsyncEngine) -> AsyncIterator[None]:
    """Truncate the ops setting tables; ``clean_tables`` only clears outboxes."""
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE TABLE ops.ops_setting_history, ops.ops_settings RESTART IDENTITY CASCADE"
            )
        )
    yield


@pytest.fixture
def facade(engine: AsyncEngine) -> OpsFacade:
    return OpsFacade(engine=engine, settings=Settings())


def _setting_value(settings: list[EffectiveSetting], key: str) -> object | None:
    for setting in settings:
        if setting.key == key:
            return setting.value
    raise AssertionError(f"{key} missing from effective settings")


class TestSettingsWriteHistory:
    async def test_good_write_records_history_and_audit(
        self, facade: OpsFacade, engine: AsyncEngine
    ) -> None:
        result = await facade.write_setting(
            setting_key="ai.timeout_seconds",
            value=15,
            updated_by=7,
        )

        assert result == {
            "setting_key": "ai.timeout_seconds",
            "value": 15,
            "version": 1,
        }

        history = await facade.get_setting_history("ai.timeout_seconds")
        assert len(history) == 1
        assert isinstance(history[0], SettingHistoryEntry)
        assert history[0].setting_key == "ai.timeout_seconds"
        assert history[0].value == 15
        assert history[0].version == 1
        assert history[0].changed_by == 7
        assert history[0].changed_at

        async with engine.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        select(ops_outbox).where(ops_outbox.c.event_type == "audit.event")
                    )
                )
                .mappings()
                .all()
            )
        assert len(rows) == 1
        assert rows[0]["payload"]["action"] == "setting.write"
        assert rows[0]["payload"]["setting_key"] == "ai.timeout_seconds"

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("ai.monthly_budget_paise", 0),
            ("ai.monthly_budget_paise", -5),
            ("ai.budget_alert_threshold_pct", 101),
            ("ai.budget_alert_threshold_pct", 0),
            ("ai.timeout_seconds", 0),
            ("ai.timeout_seconds", 31),
            ("ai.fallback_enabled", "yes"),
        ],
    )
    async def test_invalid_ai_value_is_refused_without_history(
        self, facade: OpsFacade, key: str, value: object
    ) -> None:
        with pytest.raises(InvalidSettingWriteError):
            await facade.write_setting(setting_key=key, value=value, updated_by=7)

        assert await facade.get_setting_history(key) == []

    async def test_read_only_key_is_refused(self, facade: OpsFacade) -> None:
        with pytest.raises(InvalidSettingWriteError):
            await facade.write_setting(
                setting_key="ai.provider",
                value="openai",
                updated_by=7,
            )

    async def test_history_is_newest_first_and_filterable(self, facade: OpsFacade) -> None:
        await facade.write_setting("ai.timeout_seconds", 10, updated_by=1)
        await facade.write_setting("ai.timeout_seconds", 20, updated_by=2)
        await facade.write_setting("ai.monthly_budget_paise", 1000, updated_by=3)

        everything = await facade.get_setting_history()
        assert everything[0].setting_key == "ai.monthly_budget_paise"

        timeout_history = await facade.get_setting_history("ai.timeout_seconds")
        assert [entry.version for entry in timeout_history] == [2, 1]
        assert [entry.value for entry in timeout_history] == [20, 10]

    async def test_write_invalidates_cache_and_refreshes_effective_value(
        self, facade: OpsFacade
    ) -> None:
        before = await facade.get_effective_settings()
        assert _setting_value(before, "ai.timeout_seconds") == Settings().ai_timeout_seconds

        await facade.write_setting("ai.timeout_seconds", 12, updated_by=7)

        after = await facade.get_effective_settings()
        assert _setting_value(after, "ai.timeout_seconds") == 12
        row = next(setting for setting in after if setting.key == "ai.timeout_seconds")
        assert row.source == "database"

    async def test_history_table_rows_are_append_only(
        self, facade: OpsFacade, engine: AsyncEngine
    ) -> None:
        await facade.write_setting("ai.timeout_seconds", 10, updated_by=1)
        await facade.write_setting("ai.timeout_seconds", 20, updated_by=2)

        async with engine.connect() as connection:
            count = (
                await connection.execute(text("SELECT count(*) FROM ops.ops_setting_history"))
            ).scalar_one()
        assert count == 2


class TestAiSettingsWrite:
    """Valid AI settings writes: version bump, history row, audit event, cache invalidated."""

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("ai.provider", "openai_compatible"),
            ("ai.model", "gemini-3.6-flash"),
            ("ai.fallback_provider", "openai_compatible"),
            ("ai.fallback_model", "openai/gpt-oss-120b"),
            ("ai.asr_model", "whisper-large-v3"),
            ("ai.pricing_table", "custom-model:1:2"),
        ],
    )
    async def test_valid_ai_write_records_history_and_audit(
        self, facade: OpsFacade, engine: AsyncEngine, key: str, value: object
    ) -> None:
        result = await facade.write_setting(setting_key=key, value=value, updated_by=7)

        assert result["setting_key"] == key
        assert result["value"] == value
        assert result["version"] == 1

        history = await facade.get_setting_history(key)
        assert len(history) == 1
        assert history[0].version == 1
        assert history[0].changed_by == 7

        async with engine.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        select(ops_outbox).where(ops_outbox.c.event_type == "audit.event")
                    )
                )
                .mappings()
                .all()
            )
        assert len(rows) == 1
        assert rows[0]["payload"]["action"] == "setting.write"
        assert rows[0]["payload"]["setting_key"] == key

    async def test_valid_write_bumps_version_on_rewrite(self, facade: OpsFacade) -> None:
        await facade.write_setting("ai.model", "mock-model", updated_by=1)
        result = await facade.write_setting("ai.model", "gemini-3.6-flash", updated_by=2)
        assert result["version"] == 2

    async def test_write_invalidates_cache_and_refreshes(self, facade: OpsFacade) -> None:
        await facade.write_setting("ai.model", "gemini-3.6-flash", updated_by=7)
        after = await facade.get_effective_settings()
        row = next(s for s in after if s.key == "ai.model")
        assert row.value == "gemini-3.6-flash"
        assert row.source == "database"
        assert row.editable is True


class TestAiSettingsInvalidWrites:
    """Invalid writes rejected per rule with the standard error envelope."""

    async def test_unknown_provider_rejected(self, facade: OpsFacade) -> None:
        with pytest.raises(InvalidSettingWriteError):
            await facade.write_setting(
                setting_key="ai.provider", value="unknown_provider", updated_by=7
            )
        assert await facade.get_setting_history("ai.provider") == []

    async def test_custom_model_without_pricing_rejected(self, facade: OpsFacade) -> None:
        with pytest.raises(InvalidSettingWriteError):
            await facade.write_setting(
                setting_key="ai.model", value="totally-custom-model", updated_by=7
            )
        assert await facade.get_setting_history("ai.model") == []

    async def test_unparseable_pricing_table_rejected(self, facade: OpsFacade) -> None:
        with pytest.raises(InvalidSettingWriteError):
            await facade.write_setting(
                setting_key="ai.pricing_table", value="malformed-entry", updated_by=7
            )
        assert await facade.get_setting_history("ai.pricing_table") == []

    async def test_negative_price_rejected(self, facade: OpsFacade) -> None:
        with pytest.raises(InvalidSettingWriteError):
            await facade.write_setting(
                setting_key="ai.pricing_table",
                value="model:-1:1",
                updated_by=7,
            )
        assert await facade.get_setting_history("ai.pricing_table") == []


class TestAiResolverOverride:
    """Dashboard override takes precedence over env/default."""

    async def test_resolver_returns_dashboard_override(self, facade: OpsFacade) -> None:
        await facade.write_setting("ai.provider", "openai_compatible", updated_by=7)
        await facade.write_setting("ai.model", "gemini-3.6-flash", updated_by=7)

        config = await AiConfigResolver(Settings(), override_source=facade).aresolve()

        assert config.provider == "openai_compatible"
        assert config.model == "gemini-3.6-flash"

    async def test_resolver_override_ahead_of_env_default(self, facade: OpsFacade) -> None:
        # Default env provider is "mock"; dashboard override wins.
        await facade.write_setting("ai.provider", "openai_compatible", updated_by=7)
        config = await AiConfigResolver(Settings(), override_source=facade).aresolve()
        assert config.provider == "openai_compatible"

    async def test_pricing_computation_picks_up_dashboard_override(self, facade: OpsFacade) -> None:
        await facade.write_setting("ai.pricing_table", "custom-model:10:20", updated_by=7)

        config = await AiConfigResolver(Settings(), override_source=facade).aresolve()
        assert config.pricing_table_raw == "custom-model:10:20"
        price = config.pricing_table.get("custom-model")
        assert price is not None

        from modules.intake.pricing import compute_cost_paise

        cost = compute_cost_paise(
            "custom-model",
            input_tokens=100,
            output_tokens=50,
            table=config.pricing_table,
        )
        assert cost == 10 * 100 + 20 * 50  # 2000 paise
