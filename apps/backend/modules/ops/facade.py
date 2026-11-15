"""MOD-014: typed public facade for ops (#771, #773)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from app.config import Settings, parse_ai_pricing_table
from app.db import AsyncEngineLike
from bus.events import EVENT_AUDIT_EVENT, EVENT_OPS_RUNTIME_SETTING_CHANGED
from modules.ops.domain.events import OpsRuntimeSettingChangedPayload
from modules.ops.domain.exceptions import InvalidFeatureFlagWriteError
from modules.ops.domain.setting_encryption_service import SettingEncryptionService
from modules.ops.domain.settings import (
    ALL_EDITABLE_KEYS,
    EDITABLE_AI_KEYS,
    EDITABLE_CACHE_REDIS_KEYS,
    EDITABLE_NOTIFICATION_KEYS,
    EffectiveSetting,
    EffectiveSettingsResolver,
    FeatureFlag,
    FeatureFlagHistoryEntry,
    FeatureFlagKind,
    FeatureFlagRead,
    FeatureFlagWriteResponse,
    OpsSettingsCache,
    SettingHistoryEntry,
    validate_ai_setting,
    validate_cache_redis_setting,
    validate_feature_flag_write,
    validate_notification_setting,
)
from modules.ops.schema.models import (
    ops_feature_flag_history,
    ops_feature_flags,
    ops_outbox,
    ops_setting_history,
    ops_settings,
)


class OpsFacade:
    """Typed public facade for ops."""

    def __init__(
        self,
        engine: AsyncEngineLike,
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
        # Encryption service for dashboard-entered secrets (issue #921)
        self._encryption_service = SettingEncryptionService(
            getattr(settings, "ops_settings_encryption_key", "")
        )

    async def get_effective_settings(self) -> list[EffectiveSetting]:
        cached = self._cache.get()
        if cached is not None:
            return cached

        db_overrides: dict[str, Any] = {}
        history_timestamps: dict[str, str] = {}
        async with self._engine.begin() as connection:
            result = await connection.execute(select(ops_settings))
            for row in result.mappings():
                key = row.get("setting_key")
                value = row.get("value")
                if key is not None:
                    # value is JSONB; store raw for resolution logic
                    db_overrides[key] = value

            # Query latest history timestamps for encrypted keys
            for key in db_overrides:
                if self._encryption_service.is_encrypted_key(key):
                    ts_result = await connection.execute(
                        select(ops_setting_history.c.changed_at)
                        .where(ops_setting_history.c.setting_key == key)
                        .order_by(
                            ops_setting_history.c.changed_at.desc(),
                            ops_setting_history.c.id.desc(),
                        )
                        .limit(1)
                    )
                    ts_row = ts_result.mappings().first()
                    if ts_row is not None:
                        history_timestamps[key] = ts_row["changed_at"].isoformat()

        resolved = self._resolver.resolve_all(db_overrides)

        def _history_reader(setting_key: str) -> str | None:
            return history_timestamps.get(setting_key)

        # Replace encrypted key values with masked status
        masked_resolved = []
        for item in resolved:
            if self._encryption_service.is_encrypted_key(item.key):
                # Get the DB value for this key to determine masked status
                db_value = db_overrides.get(item.key)
                masked_status = self._encryption_service.get_masked_status_with_resolver(
                    item.key,
                    item.source,
                    self._resolver,
                    db_value,
                    _history_reader,
                )
                masked_resolved.append(
                    EffectiveSetting(
                        key=item.key,
                        value=masked_status,
                        source=item.source,
                        editable=item.editable,
                        restart_required=item.restart_required,
                    )
                )
            else:
                masked_resolved.append(item)

        self._cache.set(masked_resolved)
        return masked_resolved

    def get_ai_provider_catalog(self) -> list[Any]:
        from app.ai_provider_catalog import get_ai_provider_catalog

        return get_ai_provider_catalog(settings=self._settings)

    async def get_setting_history(
        self,
        setting_key: str | None = None,
        limit: int = 50,
    ) -> list[SettingHistoryEntry]:
        """Read the append-only setting history, newest first (#798).

        ``setting_key`` narrows the read to one key; the Settings AI section asks
        for the whole list once and filters the AI keys itself.

        For encrypted setting keys, values are redacted.
        """
        statement = (
            select(ops_setting_history)
            .order_by(
                ops_setting_history.c.changed_at.desc(),
                ops_setting_history.c.id.desc(),
            )
            .limit(limit)
        )
        if setting_key is not None:
            statement = statement.where(ops_setting_history.c.setting_key == setting_key)

        async with self._engine.connect() as connection:
            result = await connection.execute(statement)
            return [
                SettingHistoryEntry(
                    setting_key=row["setting_key"],
                    value=self._encryption_service.redact_value(row["setting_key"], row["value"]),
                    version=row["version"],
                    changed_by=row["changed_by"],
                    changed_at=row["changed_at"].isoformat(),
                )
                for row in result.mappings()
            ]

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

    async def get_feature_flag_history(
        self,
        flag_key: str | None = None,
        limit: int = 50,
    ) -> list[FeatureFlagHistoryEntry]:
        """Read the append-only feature flag history, newest first.

        ``flag_key`` narrows the read to one flag.
        """
        statement = (
            select(ops_feature_flag_history)
            .order_by(
                ops_feature_flag_history.c.changed_at.desc(),
                ops_feature_flag_history.c.id.desc(),
            )
            .limit(limit)
        )
        if flag_key is not None:
            statement = statement.where(ops_feature_flag_history.c.flag_key == flag_key)

        async with self._engine.connect() as connection:
            result = await connection.execute(statement)
            return [
                FeatureFlagHistoryEntry(
                    flag_key=row["flag_key"],
                    enabled=row["enabled"],
                    flag_kind=row["flag_kind"],
                    version=row["version"],
                    changed_by=row["changed_by"],
                    changed_at=row["changed_at"].isoformat(),
                )
                for row in result.mappings()
            ]

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

    async def write_setting(
        self,
        setting_key: str,
        value: Any,
        updated_by: int | None = None,
    ) -> dict[str, Any]:
        """Write a setting value with validation, history, and audit.

        Args:
            setting_key: The setting key to update (must be in allowlist)
            value: New value (JSON-serializable)
            updated_by: Actor ID making the change

        Returns:
            Dict with setting_key, value, version

        Raises:
            InvalidSettingWriteError: If key is not allowlisted or value is invalid
        """
        from modules.ops.domain.exceptions import InvalidSettingWriteError

        # Validate key is in allowlist
        if setting_key not in ALL_EDITABLE_KEYS:
            raise InvalidSettingWriteError(setting_key, "setting key is not editable")

        # Validate value for the allowlisted knob family. A bad value is an
        # expected write refusal, so it becomes the same domain error the route
        # already maps to the shared 400 envelope.
        catalog = None
        pricing_table = None
        if setting_key in EDITABLE_AI_KEYS:
            catalog = [dict(e) for e in self.get_ai_provider_catalog()]
            try:
                pricing_table = parse_ai_pricing_table(self._settings.ai_pricing_table or "")
            except ValueError:
                pricing_table = {}
        try:
            if setting_key in EDITABLE_AI_KEYS:
                validate_ai_setting(
                    setting_key, value, catalog=catalog, pricing_table=pricing_table
                )
            elif setting_key in EDITABLE_NOTIFICATION_KEYS:
                validate_notification_setting(setting_key, value)
            elif setting_key in EDITABLE_CACHE_REDIS_KEYS:
                validate_cache_redis_setting(setting_key, value)
        except ValueError as exc:
            raise InvalidSettingWriteError(setting_key, str(exc)) from exc

        # Encrypt value if this is an encrypted setting key
        stored_value = self._encryption_service.encrypt_if_needed(setting_key, value)

        async with self._engine.begin() as connection:
            # Read existing setting for update (lock row)
            result = await connection.execute(
                select(ops_settings).where(ops_settings.c.setting_key == setting_key)
            )
            row = result.mappings().first()

            old_value = None
            old_version = 0
            if row is not None:
                old_value = row["value"]
                old_version = row["version"]

            new_version = old_version + 1

            # Upsert the setting with encrypted value
            if row is None:
                await connection.execute(
                    ops_settings.insert().values(
                        setting_key=setting_key,
                        value=stored_value,
                        version=new_version,
                        updated_by=updated_by,
                    )
                )
            else:
                await connection.execute(
                    ops_settings.update()
                    .where(ops_settings.c.setting_key == setting_key)
                    .values(
                        value=stored_value,
                        updated_by=updated_by,
                        updated_at=datetime.now(UTC),
                        version=new_version,
                    )
                )

            # Record history with redacted value
            redacted_value = self._encryption_service.redact_value(setting_key, stored_value)
            await connection.execute(
                ops_setting_history.insert().values(
                    setting_key=setting_key,
                    value=redacted_value,
                    version=new_version,
                    changed_by=updated_by,
                )
            )

            # Emit audit event with redacted values
            audit_payload = {
                "action": "setting.write",
                "setting_key": setting_key,
                "old_value": self._encryption_service.redact_value(setting_key, old_value),
                "new_value": redacted_value,
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

            # Emit runtime setting changed event for cache/redis switches
            if setting_key in ("cache.enabled", "redis.enabled"):
                runtime_event = OpsRuntimeSettingChangedPayload(
                    key=setting_key, value=value, version=new_version
                )
                await connection.execute(
                    ops_outbox.insert().values(
                        event_id=uuid4(),
                        event_type=EVENT_OPS_RUNTIME_SETTING_CHANGED,
                        payload=runtime_event.model_dump(mode="json"),
                        occurred_at=datetime.now(UTC),
                        status="pending",
                        attempts=0,
                    )
                )

        # Invalidate cache so the next effective read resolves the new value
        self._cache.invalidate()

        return {"setting_key": setting_key, "value": value, "version": new_version}
