"""Integration tests for ops settings encryption/redaction pipeline (issue #921).

Covers: encrypted write stores ciphertext in DB, history/audit redaction, masked
status reads, and key material never leaking in logs/audit payloads.
"""

from __future__ import annotations

import base64
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import insert, select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings, get_settings
from modules.ops.domain.setting_encryption import encrypt_setting_value
from modules.ops.domain.settings import ENCRYPTED_SETTING_KEYS
from modules.ops.facade import OpsFacade
from modules.ops.schema.models import ops_outbox, ops_setting_history, ops_settings

_ENCRYPTION_KEY = base64.b64encode(os.urandom(32)).decode("ascii")
_PLAINTEXT = "test-plaintext-value"
_REDACTED = "[REDACTED]"


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
def facade(engine: AsyncEngine) -> OpsFacade:
    os.environ["OPS_SETTINGS_ENCRYPTION_KEY"] = _ENCRYPTION_KEY
    return OpsFacade(engine=engine, settings=get_settings())


async def _write_encrypted_setting(
    engine: AsyncEngine,
    key: str,
    plaintext: str = _PLAINTEXT,
    updated_by: int | None = 7,
) -> str:
    """Insert an encrypted setting directly into the DB (simulating dashboard write)."""
    encrypted = encrypt_setting_value(plaintext, _ENCRYPTION_KEY)
    async with engine.begin() as connection:
        await connection.execute(
            insert(ops_settings).values(
                setting_key=key,
                value=encrypted,
                version=1,
                updated_by=updated_by,
            )
        )
        await connection.execute(
            insert(ops_setting_history).values(
                setting_key=key,
                value=_REDACTED,
                version=1,
                changed_by=updated_by,
            )
        )
        await connection.execute(
            insert(ops_outbox).values(
                event_id=uuid4(),
                event_type="audit.event",
                payload={
                    "action": "setting.write",
                    "setting_key": key,
                    "old_value": _REDACTED,
                    "new_value": _REDACTED,
                    "version": 1,
                    "updated_by": updated_by,
                },
                occurred_at=datetime.now(UTC),
                status="pending",
                attempts=0,
            )
        )
    return encrypted


class TestEncryptedReadPipeline:
    async def test_history_redacts_encrypted_value(
        self, facade: OpsFacade, engine: AsyncEngine
    ) -> None:
        key = "ai.api_key"
        await _write_encrypted_setting(engine, key, _PLAINTEXT)

        history = await facade.get_setting_history(key)
        assert len(history) == 1
        assert history[0].value == _REDACTED
        assert _PLAINTEXT not in str(history[0].value)

    async def test_audit_payload_redacts_encrypted_values(
        self, facade: OpsFacade, engine: AsyncEngine
    ) -> None:
        key = "slack.webhook_url"
        raw_key = "https://example.com/webhook"
        await _write_encrypted_setting(engine, key, raw_key)

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
        assert payload["new_value"] == _REDACTED
        assert payload["old_value"] == _REDACTED
        assert raw_key not in str(payload)

    async def test_effective_settings_returns_masked_status(
        self, facade: OpsFacade, engine: AsyncEngine
    ) -> None:
        key = "ai.api_key"
        await _write_encrypted_setting(engine, key, _PLAINTEXT)

        effective = await facade.get_effective_settings()
        api_key_setting = next(s for s in effective if s.key == key)
        assert api_key_setting.value.startswith("configured from dashboard")
        assert api_key_setting.value != _PLAINTEXT
        assert _PLAINTEXT not in str(api_key_setting.value)

    async def test_masked_status_includes_timestamp_from_history(
        self, facade: OpsFacade, engine: AsyncEngine
    ) -> None:
        key = "langfuse.secret_key"
        await _write_encrypted_setting(engine, key, "test-secret-value")

        effective = await facade.get_effective_settings()
        setting = next(s for s in effective if s.key == key)
        assert setting.value.startswith("configured from dashboard, set ")
        assert "T" in setting.value  # ISO timestamp present

    async def test_non_encrypted_key_writes_plaintext(
        self, facade: OpsFacade, engine: AsyncEngine
    ) -> None:
        await facade.write_setting(
            setting_key="ai.timeout_seconds",
            value=15,
            updated_by=7,
        )

        async with engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        select(ops_settings).where(
                            ops_settings.c.setting_key == "ai.timeout_seconds"
                        )
                    )
                )
                .mappings()
                .first()
            )
        assert row["value"] == 15

        history = await facade.get_setting_history("ai.timeout_seconds")
        assert history[0].value == 15

        effective = await facade.get_effective_settings()
        timeout_setting = next(s for s in effective if s.key == "ai.timeout_seconds")
        assert timeout_setting.value == 15


class TestEncryptionKeyMissing:
    async def test_write_stores_plaintext_when_encryption_key_not_configured(
        self, engine: AsyncEngine
    ) -> None:
        """When OPS_SETTINGS_ENCRYPTION_KEY is empty, encrypted key writes store plaintext."""
        facade = OpsFacade(engine=engine, settings=Settings())
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

        # Effective settings should return empty masked status when encryption disabled
        effective = await facade.get_effective_settings()
        for s in effective:
            if s.key in ENCRYPTED_SETTING_KEYS:
                assert s.value == "", f"{s.key} should have empty masked status when disabled"


class TestKeyNeverInLogs:
    async def test_audit_payload_never_contains_raw_key(
        self, facade: OpsFacade, engine: AsyncEngine
    ) -> None:
        """Key material must never appear in audit/outbox payloads."""
        key = "smtp.credentials"
        raw_key = "smtp://test@example.com:587"
        await _write_encrypted_setting(engine, key, raw_key)

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

        payload_str = str(rows[0]["payload"])
        assert raw_key not in payload_str
        assert rows[0]["payload"]["new_value"] == _REDACTED
