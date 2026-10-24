"""MOD-014: typed public facade for ops (#771)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from modules.ops.domain.settings import EffectiveSetting, EffectiveSettingsResolver, OpsSettingsCache
from modules.ops.schema.models import ops_settings


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
