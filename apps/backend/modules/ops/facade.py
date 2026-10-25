"""MOD-014: typed public facade for ops (#771, #772, #773)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from bus.events import EVENT_AUDIT_EVENT
from modules.ops.domain.settings import (
    EDITABLE_AI_KEYS,
    EffectiveSetting,
    EffectiveSettingsResolver,
    FeatureFlagRead,
    FeatureFlagWriteResponse,
    OpsSettingsCache,
    get_feature_flag,
    get_feature_flags,
    is_editable,
    write_feature_flag,
)
from modules.ops.schema.models import ops_outbox, ops_setting_history, ops_settings


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

    def _validate_setting(self, key: str, value: Any) -> Any:
        if key not in EDITABLE_AI_KEYS or not is_editable(key):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "INVALID_SETTING_KEY", "message": "Setting key is not editable"},
            )

        if key == "ai.monthly_budget_paise":
            if not isinstance(value, int) or isinstance(value, bool):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"code": "INVALID_SETTING_VALUE", "message": "Invalid setting value"},
                )
            if value < 0 or value > 10_000_000_000:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"code": "INVALID_SETTING_VALUE", "message": "Invalid setting value"},
                )
            return value

        if key == "ai.budget_alert_threshold_pct":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"code": "INVALID_SETTING_VALUE", "message": "Invalid setting value"},
                )
            if value < 0 or value > 100:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"code": "INVALID_SETTING_VALUE", "message": "Invalid setting value"},
                )
            # store as number
            return value

        if key == "ai.timeout_seconds":
            if not isinstance(value, int) or isinstance(value, bool):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"code": "INVALID_SETTING_VALUE", "message": "Invalid setting value"},
                )
            if value < 1 or value > 600:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"code": "INVALID_SETTING_VALUE", "message": "Invalid setting value"},
                )
            return value

        if key == "ai.fallback_enabled":
            if not isinstance(value, bool):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"code": "INVALID_SETTING_VALUE", "message": "Invalid setting value"},
                )
            return value

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_SETTING_KEY", "message": "Setting key is not editable"},
        )

    async def write_setting(
        self,
        key: str,
        value: Any,
        updated_by: int | None = None,
    ) -> dict[str, Any]:
        validated = self._validate_setting(key, value)

        async with self._engine.begin() as connection:
            # Get current version if exists
            result = await connection.execute(
                select(ops_settings.c.version).where(ops_settings.c.setting_key == key)
            )
            row = result.first()
            current_version = row[0] if row else 0
            new_version = current_version + 1

            # Upsert into ops_settings
            stmt = insert(ops_settings).values(
                setting_key=key,
                value=validated,
                version=new_version,
                updated_by=updated_by,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[ops_settings.c.setting_key],
                set_={
                    "value": validated,
                    "version": new_version,
                    "updated_by": updated_by,
                },
            )
            await connection.execute(stmt)

            # Record history
            await connection.execute(
                ops_setting_history.insert().values(
                    setting_key=key,
                    value=validated,
                    version=new_version,
                    changed_by=updated_by,
                )
            )

            # Emit audit event
            audit_payload = {
                "action": "settings.write",
                "setting_key": key,
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

        # Invalidate cache
        self._cache = OpsSettingsCache(ttl_seconds=self._cache._ttl_seconds)

        return {"key": key, "value": validated, "version": new_version}

    async def get_feature_flags(self) -> list[FeatureFlagRead]:
        """Get all feature flags for operator view."""
        flags = await get_feature_flags(self._engine)
        return [
            FeatureFlagRead(
                flag_key=flag.flag_key,
                enabled=flag.enabled,
                flag_kind=flag.flag_kind.value,
                description=flag.description,
                editable=flag.editable,
                updated_at=flag.updated_at,
            )
            for flag in flags
        ]

    async def get_feature_flag(self, flag_key: str) -> FeatureFlagRead | None:
        """Get a single feature flag for operator view."""
        flag = await get_feature_flag(self._engine, flag_key)
        if flag is None:
            return None
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
            HTTPException: If flag doesn't exist or is restart-required
        """
        try:
            return await write_feature_flag(
                engine=self._engine,
                flag_key=flag_key,
                enabled=enabled,
                updated_by=updated_by,
            )
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "INVALID_FEATURE_FLAG_WRITE", "message": str(e)},
            ) from e
