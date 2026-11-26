"""Integration tests for ops feature flags (#773)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from modules.ops.domain.settings import (
    FeatureFlagWriteResponse,
)
from modules.ops.facade import OpsFacade


@pytest.fixture(autouse=True)
async def _reset_ops_feature_flags(engine: AsyncEngine) -> AsyncIterator[None]:
    """Truncate the ops flag tables; ``clean_tables`` only clears outboxes."""
    from sqlalchemy import text

    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE TABLE ops.ops_feature_flag_history, "
                "ops.ops_feature_flags RESTART IDENTITY CASCADE"
            )
        )
    yield


class TestFeatureFlagFacade:
    """Tests for feature flag facade operations."""

    @pytest.fixture
    def facade(self, engine: AsyncEngine) -> OpsFacade:
        return OpsFacade(engine=engine, settings=Settings())

    async def test_get_feature_flags_empty(self, facade: OpsFacade) -> None:
        """Reading feature flags when none exist returns empty list."""
        flags = await facade.get_feature_flags()
        assert flags == []

    async def test_get_feature_flag_not_found(self, facade: OpsFacade) -> None:
        """Reading a non-existent flag returns None."""
        flag = await facade.get_feature_flag("nonexistent")
        assert flag is None

    async def test_write_runtime_feature_flag_succeeds(
        self, facade: OpsFacade, engine: AsyncEngine
    ) -> None:
        """Writing a runtime flag should succeed with history and audit."""
        from datetime import UTC, datetime

        from sqlalchemy import insert

        from modules.ops.schema.models import ops_feature_flags

        async with engine.begin() as conn:
            await conn.execute(
                insert(ops_feature_flags).values(
                    flag_key="test.runtime_flag",
                    enabled=False,
                    flag_kind="runtime",
                    description="Test runtime flag",
                    updated_by=None,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            )

        result = await facade.write_feature_flag(
            flag_key="test.runtime_flag",
            enabled=True,
            updated_by=123,
        )

        assert isinstance(result, FeatureFlagWriteResponse)
        assert result.flag_key == "test.runtime_flag"
        assert result.enabled is True
        assert result.flag_kind == "runtime"
        assert result.version == 2

        # Verify the flag was updated
        flag = await facade.get_feature_flag("test.runtime_flag")
        assert flag is not None
        assert flag.enabled is True

    async def test_write_restart_required_feature_flag_refused(
        self, facade: OpsFacade, engine: AsyncEngine
    ) -> None:
        """Writing a restart-required flag should be refused with clear error."""
        from datetime import UTC, datetime

        from sqlalchemy import insert

        from modules.ops.domain.exceptions import InvalidFeatureFlagWriteError
        from modules.ops.schema.models import ops_feature_flags

        async with engine.begin() as conn:
            await conn.execute(
                insert(ops_feature_flags).values(
                    flag_key="test.restart_flag",
                    enabled=False,
                    flag_kind="restart_required",
                    description="Test restart flag",
                    updated_by=None,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            )

        with pytest.raises(InvalidFeatureFlagWriteError) as exc_info:
            await facade.write_feature_flag(
                flag_key="test.restart_flag",
                enabled=True,
                updated_by=123,
            )

        assert "restart-required" in exc_info.value.reason.lower()
        assert "cannot be edited" in exc_info.value.reason.lower()

    async def test_write_nonexistent_flag_refused(self, facade: OpsFacade) -> None:
        """Writing a non-existent flag should be refused."""
        from modules.ops.domain.exceptions import InvalidFeatureFlagWriteError

        with pytest.raises(InvalidFeatureFlagWriteError) as exc_info:
            await facade.write_feature_flag(
                flag_key="nonexistent",
                enabled=True,
                updated_by=123,
            )

        assert "not found" in exc_info.value.reason.lower()


class TestFeatureFlagIntegration:
    """Integration tests for feature flag read/write via routes."""

    async def test_operator_can_read_feature_flags(self, engine: AsyncEngine) -> None:
        """Operators can read feature flags."""
        from datetime import UTC, datetime

        from sqlalchemy import insert

        from modules.ops.schema.models import ops_feature_flags

        async with engine.begin() as conn:
            await conn.execute(
                insert(ops_feature_flags).values(
                    flag_key="test.readable",
                    enabled=True,
                    flag_kind="runtime",
                    description="Readable flag",
                    updated_by=None,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            )

        facade = OpsFacade(engine=engine, settings=Settings())
        flags = await facade.get_feature_flags()

        assert len(flags) == 1
        assert flags[0].flag_key == "test.readable"
        assert flags[0].enabled is True
        assert flags[0].flag_kind == "runtime"
        assert flags[0].editable is True

    async def test_admin_can_write_runtime_flag(self, engine: AsyncEngine) -> None:
        """Admin can write a runtime flag."""
        from datetime import UTC, datetime

        from sqlalchemy import insert

        from modules.ops.schema.models import ops_feature_flags

        async with engine.begin() as conn:
            await conn.execute(
                insert(ops_feature_flags).values(
                    flag_key="test.admin_write",
                    enabled=False,
                    flag_kind="runtime",
                    description="Admin writable",
                    updated_by=None,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            )

        facade = OpsFacade(engine=engine, settings=Settings())
        result = await facade.write_feature_flag(
            flag_key="test.admin_write",
            enabled=True,
            updated_by=456,
        )

        assert result.flag_key == "test.admin_write"
        assert result.enabled is True
        assert result.flag_kind == "runtime"

    async def test_admin_cannot_write_restart_required_flag(self, engine: AsyncEngine) -> None:
        """Admin cannot write a restart-required flag."""
        from datetime import UTC, datetime

        from sqlalchemy import insert

        from modules.ops.domain.exceptions import InvalidFeatureFlagWriteError
        from modules.ops.schema.models import ops_feature_flags

        async with engine.begin() as conn:
            await conn.execute(
                insert(ops_feature_flags).values(
                    flag_key="test.admin_no_write",
                    enabled=False,
                    flag_kind="restart_required",
                    description="Admin not writable",
                    updated_by=None,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            )

        facade = OpsFacade(engine=engine, settings=Settings())

        with pytest.raises(InvalidFeatureFlagWriteError) as exc_info:
            await facade.write_feature_flag(
                flag_key="test.admin_no_write",
                enabled=True,
                updated_by=456,
            )

        assert "restart-required" in exc_info.value.reason.lower()
