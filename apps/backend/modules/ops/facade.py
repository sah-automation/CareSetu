"""MOD-014: typed public facade for ops (#771, #773)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from bus.events import EVENT_AUDIT_EVENT
from modules.ops.domain.exceptions import InvalidFeatureFlagWriteError
from modules.ops.domain.settings import (
    EffectiveSetting,
    EffectiveSettingsResolver,
    FeatureFlag,
    FeatureFlagKind,
    FeatureFlagRead,
    FeatureFlagWriteResponse,
    OpsSettingsCache,
    validate_feature_flag_write,
)
from modules.ops.schema.models import (
    ops_feature_flag_history,
    ops_feature_flags,
    ops_outbox,
    ops_settings,
)


class OpsFacade:
    """Typed public facade for ops."""

    def __init__(
        self,
        engine: AsyncEngine,
        settings: Settings,
        cache_ttl_seconds: int | None = None,
    ) -> None:
        self._engine = engine
        self._settings = settings
        ttl = (
            cache_ttl_seconds
            if cache_ttl_seconds is not None
            else getattr(settings, "settings_cache_ttl_seconds", 30)
        )
        self._cache = OpsSettingsCache(ttl_seconds=ttl)
        self._resolver = EffectiveSettingsResolver(settings)

    async def get_effective_settings(self) -> list[EffectiveSetting]:
        cached = self._cache.get()
        if cached is not None:
            return cached

        db_overrides: dict[str, Any] = {}
        async with self._engine.begin() as connection:
            result = await connection.execute(select(ops_settings))
            for row in result.mappings():
                key = row.get("setting_key")
                value = row.get("value")
                if key is not None:
                    # value is JSONB; store raw for resolution logic
                    db_overrides[key] = value

        resolved = self._resolver.resolve_all(db_overrides)
        self._cache.set(resolved)
        return resolved

    async def get_feature_flags(self) -> list[FeatureFlagRead]:
        """Get all feature flags for operator view."""
        async with self._engine.connect() as connection:
            result = await connection.execute(select(ops_feature_flags))
            flags = []
            for row in result.mappings():
                flag = FeatureFlag(
                    flag_key=row["flag_key"],
                    enabled=row["enabled"],
                    flag_kind=FeatureFlagKind(row["flag_kind"]),
                    description=row["description"],
                    updated_by=row["updated_by"],
                    created_at=row["created_at"].isoformat(),
                    updated_at=row["updated_at"].isoformat(),
                )
                flags.append(
                    FeatureFlagRead(
                        flag_key=flag.flag_key,
                        enabled=flag.enabled,
                        flag_kind=flag.flag_kind.value,
                        description=flag.description,
                        editable=flag.editable,
                        updated_at=flag.updated_at,
                    )
                )
            return flags

    async def get_feature_flag(self, flag_key: str) -> FeatureFlagRead | None:
        """Get a single feature flag for operator view."""
        async with self._engine.connect() as connection:
            result = await connection.execute(
                select(ops_feature_flags).where(ops_feature_flags.c.flag_key == flag_key)
            )
            row = result.mappings().first()
            if row is None:
                return None
            flag = FeatureFlag(
                flag_key=row["flag_key"],
                enabled=row["enabled"],
                flag_kind=FeatureFlagKind(row["flag_kind"]),
                description=row["description"],
                updated_by=row["updated_by"],
                created_at=row["created_at"].isoformat(),
                updated_at=row["updated_at"].isoformat(),
            )
            return FeatureFlagRead(
                flag_key=flag.flag_key,
                enabled=flag.enabled,
                flag_kind=flag.flag_kind.value,
                description=flag.description,
                editable=flag.editable,
                updated_at=flag.updated_at,
            )

    async def write_feature_flag(
        self,
        flag_key: str,
        enabled: bool,
        updated_by: int | None = None,
    ) -> FeatureFlagWriteResponse:
        """Write a feature flag value with validation, history, and audit.

        Args:
            flag_key: The flag key to update
            enabled: New enabled value
            updated_by: Actor ID making the change

        Returns:
            FeatureFlagWriteResponse with updated flag info

        Raises:
            InvalidFeatureFlagWriteError: If flag doesn't exist or is restart-required
        """
        async with self._engine.begin() as connection:
            # Read and lock the existing flag for update
            result = await connection.execute(
                select(ops_feature_flags).where(ops_feature_flags.c.flag_key == flag_key)
            )
            row = result.mappings().first()
            if row is None:
                raise InvalidFeatureFlagWriteError(flag_key, "feature flag not found")

            old_enabled = row["enabled"]
            old_version = row["version"]
            flag_kind = FeatureFlagKind(row["flag_kind"])

            # Validate the write is allowed
            flag = FeatureFlag(
                flag_key=row["flag_key"],
                enabled=row["enabled"],
                flag_kind=flag_kind,
                description=row["description"],
                updated_by=row["updated_by"],
                created_at=row["created_at"].isoformat(),
                updated_at=row["updated_at"].isoformat(),
            )
            validate_feature_flag_write(flag, enabled)

            new_version = old_version + 1

            # Update the flag with incremented version
            await connection.execute(
                ops_feature_flags.update()
                .where(ops_feature_flags.c.flag_key == flag_key)
                .values(
                    enabled=enabled,
                    updated_by=updated_by,
                    updated_at=datetime.now(UTC),
                    version=new_version,
                )
            )

            # Record history
            await connection.execute(
                ops_feature_flag_history.insert().values(
                    flag_key=flag_key,
                    enabled=enabled,
                    flag_kind=flag_kind.value,
                    version=new_version,
                    changed_by=updated_by,
                )
            )

            # Emit audit event with old and new values
            audit_payload = {
                "action": "feature_flag.write",
                "flag_key": flag_key,
                "old_enabled": old_enabled,
                "new_enabled": enabled,
                "flag_kind": flag_kind.value,
                "version": new_version,
                "updated_by": updated_by,
            }
            await connection.execute(
                ops_outbox.insert().values(
                    event_id=uuid4(),
                    event_type=EVENT_AUDIT_EVENT,
                    payload=audit_payload,
                    occurred_at=datetime.now(UTC),
                    status="pending",
                    attempts=0,
                )
            )

        return FeatureFlagWriteResponse(
            flag_key=flag_key,
            enabled=enabled,
            flag_kind=flag_kind.value,
            version=new_version,
        )
