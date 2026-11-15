"""Integration tests for issue #923: runtime-editable provider API key writes.

Covers: encrypted write stores ciphertext, dashboard key resolves ahead of env,
non-mock providers require a resolvable key, mock providers require no key, and
masked status reads reflect the new state (including the "set <date>" form).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import get_settings
from modules.ops.domain.exceptions import InvalidSettingWriteError
from modules.ops.domain.setting_encryption import is_encrypted_value
from modules.ops.facade import OpsFacade
from modules.ops.schema.models import ops_outbox, ops_setting_history, ops_settings

_ENCRYPTION_KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="


@pytest.fixture(autouse=True)
async def _reset_ops_settings(engine: AsyncEngine) -> AsyncIterator[None]:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE TABLE ops.ops_setting_history, ops.ops_settings RESTART IDENTITY CASCADE"
            )
        )
    yield


@pytest.fixture
def facade(engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch) -> OpsFacade:
    monkeypatch.setenv("OPS_SETTINGS_ENCRYPTION_KEY", _ENCRYPTION_KEY)
    monkeypatch.delenv("AI_API_KEY", raising=False)
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    return OpsFacade(engine=engine, settings=get_settings())


async def _read_db_value(engine: AsyncEngine, key: str):
    async with engine.connect() as connection:
        row = (
            (
                await connection.execute(
                    select(ops_settings).where(ops_settings.c.setting_key == key)
                )
            )
            .mappings()
            .first()
        )
    return None if row is None else row["value"]


async def _latest_history_ts(engine: AsyncEngine, key: str):
    async with engine.connect() as connection:
        row = (
            (
                await connection.execute(
                    select(ops_setting_history.c.changed_at)
                    .where(ops_setting_history.c.setting_key == key)
                    .order_by(
                        ops_setting_history.c.changed_at.desc(), ops_setting_history.c.id.desc()
                    )
                    .limit(1)
                )
            )
            .mappings()
            .first()
        )
    return None if row is None else row["changed_at"]


class TestProviderApiKeyWrite:
    async def test_valid_write_stores_encrypted_value_and_masks(
        self, facade: OpsFacade, engine: AsyncEngine
    ) -> None:
        result = await facade.write_setting(
            setting_key="ai.api_key", value="sk-live-dashboard-key-123", updated_by=7
        )
        assert result["setting_key"] == "ai.api_key"
        assert result["value"] == "sk-live-dashboard-key-123"
        assert result["version"] == 1

        stored = await _read_db_value(engine, "ai.api_key")
        assert stored is not None
        assert stored != "sk-live-dashboard-key-123"
        assert is_encrypted_value(stored) is True

        effective = await facade.get_effective_settings()
        item = next(s for s in effective if s.key == "ai.api_key")
        assert item.value.startswith("configured from dashboard")
        assert item.value != "sk-live-dashboard-key-123"
        assert "sk-live-dashboard-key-123" not in str(item.value)

        # History/audit redact plaintext.
        history = await facade.get_setting_history("ai.api_key")
        assert history[0].value == "[REDACTED]"

    async def test_dashboard_key_resolves_ahead_of_env(
        self, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPS_SETTINGS_ENCRYPTION_KEY", _ENCRYPTION_KEY)
        monkeypatch.setenv("AI_API_KEY", "sk-env-key-999")
        monkeypatch.delenv("AI_PROVIDER", raising=False)
        facade = OpsFacade(engine=engine, settings=get_settings())

        await facade.write_setting(setting_key="ai.api_key", value="sk-dashboard-key", updated_by=7)

        effective = await facade.get_effective_settings()
        item = next(s for s in effective if s.key == "ai.api_key")
        assert item.value.startswith("configured from dashboard")

        # The raw env key must never leak into the effective value.
        assert "sk-env-key-999" not in str(item.value)

    async def test_masked_status_includes_timestamp(
        self, facade: OpsFacade, engine: AsyncEngine
    ) -> None:
        await facade.write_setting(setting_key="ai.api_key", value="sk-ts-key", updated_by=7)

        ts = await _latest_history_ts(engine, "ai.api_key")
        assert ts is not None

        effective = await facade.get_effective_settings()
        item = next(s for s in effective if s.key == "ai.api_key")
        assert item.value.startswith("configured from dashboard, set ")
        assert "T" in item.value

    async def test_non_mock_provider_without_resolvable_key_is_rejected(
        self, facade: OpsFacade, engine: AsyncEngine
    ) -> None:
        # Select a non-mock provider; no env key, no dashboard key yet.
        await facade.write_setting(
            setting_key="ai.provider", value="openai_compatible", updated_by=7
        )

        with pytest.raises(InvalidSettingWriteError):
            await facade.write_setting(setting_key="ai.api_key", value="", updated_by=7)

        # Nothing was persisted for the key.
        assert await _read_db_value(engine, "ai.api_key") is None

    async def test_non_mock_provider_with_written_key_is_accepted(
        self, facade: OpsFacade, engine: AsyncEngine
    ) -> None:
        await facade.write_setting(
            setting_key="ai.provider", value="openai_compatible", updated_by=7
        )

        result = await facade.write_setting(
            setting_key="ai.api_key", value="sk-live-key-from-write", updated_by=7
        )
        assert result["version"] == 1
        assert is_encrypted_value(await _read_db_value(engine, "ai.api_key")) is True

    async def test_non_mock_provider_with_env_key_is_accepted_without_written_value(
        self, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPS_SETTINGS_ENCRYPTION_KEY", _ENCRYPTION_KEY)
        monkeypatch.setenv("AI_API_KEY", "sk-env-only-key")
        monkeypatch.delenv("AI_PROVIDER", raising=False)
        facade = OpsFacade(engine=engine, settings=get_settings())

        await facade.write_setting(
            setting_key="ai.provider", value="openai_compatible", updated_by=7
        )

        # Empty written value is fine because the environment resolves a key.
        result = await facade.write_setting(setting_key="ai.api_key", value="", updated_by=7)
        assert result["version"] == 1

    async def test_mock_provider_write_requires_no_key(
        self, facade: OpsFacade, engine: AsyncEngine
    ) -> None:
        # Mock provider (default): no env key, no dashboard key, empty value.
        result = await facade.write_setting(setting_key="ai.api_key", value="", updated_by=7)
        assert result["version"] == 1
        assert await _read_db_value(engine, "ai.api_key") == ""

    async def test_key_redacted_from_history_and_audit(
        self, facade: OpsFacade, engine: AsyncEngine
    ) -> None:
        await facade.write_setting(setting_key="ai.api_key", value="sk-secret-key", updated_by=7)

        history = await facade.get_setting_history("ai.api_key")
        assert history[0].value == "[REDACTED]"
        assert "sk-secret-key" not in str(history[0].value)

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
        payload = rows[0]["payload"]
        assert payload["old_value"] is None
        assert payload["new_value"] == "[REDACTED]"
        assert "sk-secret-key" not in str(payload)
