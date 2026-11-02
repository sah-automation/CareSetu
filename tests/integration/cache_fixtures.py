"""Shared integration-test fixtures for the ARCH-P2 cache verification tickets.

Every cache integration test reuses three pieces from here:

* ``FakeRedis`` - an in-memory stand-in for ``redis.asyncio.Redis`` supporting
  get, set, delete, scan, and TTL behavior, installable as the shared client.
* ``SqlCounter`` - a SELECT-statement counter driven by a SQLAlchemy engine
  event listener, resettable between assertions.
* facade builders - construct a facade with caching enabled or disabled against
  a real Postgres test engine.

No production behavior lives here; this module is test-only.
"""

from __future__ import annotations

import contextlib
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

# --- Fake Redis -------------------------------------------------------------


class FakeRedis:
    """In-memory stand-in for the ``redis.asyncio.Redis`` surface the caches touch."""

    def __init__(self, store: dict[str, str] | None = None) -> None:
        self.store: dict[str, str] = store if store is not None else {}
        self.ttls: dict[str, int | None] = {}
        self.last_ttl: int | None = None

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(
        self,
        key: str,
        value: str,
        ex: int | None = None,
        px: int | None = None,
        nx: bool = False,
        xx: bool = False,
        **_kwargs: Any,
    ) -> bool | None:
        if nx and key in self.store:
            return None
        if xx and key not in self.store:
            return None
        self.store[key] = value
        ttl = ex if ex is not None else (px // 1000 if px is not None else None)
        self.ttls[key] = ttl
        self.last_ttl = ttl

    async def scan(
        self,
        cursor: int = 0,
        match: str | None = None,
        count: int | None = None,
    ) -> tuple[int, list[str]]:
        if match is None:
            keys = sorted(self.store)
        else:
            prefix = match.rstrip("*")
            keys = [k for k in self.store if k.startswith(prefix)]
        return 0, keys

    async def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            if key in self.store:
                del self.store[key]
                self.ttls.pop(key, None)
                removed += 1
        return removed

    async def ttl(self, key: str) -> int:
        if key not in self.store:
            return -2
        ttl = self.ttls.get(key)
        if ttl is None:
            return -1
        return int(ttl)

    async def expire(self, key: str, seconds: int) -> bool:
        if key not in self.store:
            return False
        self.ttls[key] = seconds
        self.last_ttl = seconds
        return True

    async def exists(self, *keys: str) -> int:
        return sum(1 for key in keys if key in self.store)

    async def keys(self, pattern: str | None = None) -> list[str]:
        if not pattern or pattern == "*":
            return sorted(self.store)
        prefix = pattern.rstrip("*")
        return [k for k in self.store if k.startswith(prefix)]

    async def mget(self, *keys: str) -> list[str | None]:
        return [self.store.get(key) for key in keys]

    async def flushdb(self) -> None:
        self.store.clear()
        self.ttls.clear()


# Alias for the legacy private name used by the directory cache test.
_FakeRedis = FakeRedis


def install_fake_redis(client: FakeRedis | None = None) -> FakeRedis:
    """Install ``client`` (or a fresh FakeRedis) as the shared Redis client."""
    import app.redis as shared_redis

    chosen = client if client is not None else FakeRedis()
    shared_redis._REDIS_CLIENT = chosen
    return chosen


def reset_shared_redis() -> None:
    """Clear the shared Redis client (restore in teardown)."""
    import app.redis as shared_redis

    shared_redis._REDIS_CLIENT = None


@contextlib.contextmanager
def fake_redis(client: FakeRedis | None = None) -> Iterator[FakeRedis]:
    """Context manager that installs a fake Redis and restores the previous client."""
    import app.redis as shared_redis

    previous = shared_redis._REDIS_CLIENT
    chosen = install_fake_redis(client)
    try:
        yield chosen
    finally:
        shared_redis._REDIS_CLIENT = previous


@contextlib.asynccontextmanager
async def async_fake_redis(client: FakeRedis | None = None) -> Any:
    import app.redis as shared_redis

    previous = shared_redis._REDIS_CLIENT
    chosen = install_fake_redis(client)
    try:
        yield chosen
    finally:
        shared_redis._REDIS_CLIENT = previous


# --- SQL counter -----------------------------------------------------------


def _strip_leading_sql_comments(statement: str) -> str:
    text = (statement or "").lstrip()
    while True:
        if text.startswith("--"):
            newline = text.find("\n")
            if newline == -1:
                return ""
            text = text[newline + 1 :].lstrip()
        elif text.startswith("/*"):
            end = text.find("*/", 2)
            if end == -1:
                return text
            text = text[end + 2 :].lstrip()
        else:
            return text


class SqlCounter:
    """Counts SELECT statements executed through a SQLAlchemy engine."""

    def __init__(self, engine: AsyncEngine | None = None) -> None:
        self.engine: AsyncEngine | None = engine
        self.count: int = 0
        self.statements: list[str] = []
        self._attached: bool = False
        if engine is not None:
            self.attach(engine)

    def attach(self, engine: AsyncEngine) -> None:
        if self._attached and self.engine is engine:
            return
        if self._attached:
            self.detach()
        self.engine = engine
        event.listen(engine.sync_engine, "before_cursor_execute", self._handler)
        self._attached = True

    def detach(self) -> None:
        if self._attached and self.engine is not None:
            with contextlib.suppress(Exception):
                event.remove(self.engine.sync_engine, "before_cursor_execute", self._handler)
        self._attached = False

    def reset(self) -> None:
        self.count = 0
        self.statements.clear()

    def _handler(self, connection, cursor, statement, parameters, context, executemany) -> None:
        normalized = _strip_leading_sql_comments(
            statement if isinstance(statement, str) else str(statement)
        )
        if normalized.lower().startswith("select"):
            self.count += 1
            self.statements.append(statement if isinstance(statement, str) else str(statement))

    @property
    def selects(self) -> list[str]:
        return self.statements

    def __enter__(self) -> SqlCounter:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.detach()

    async def __aenter__(self) -> SqlCounter:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.detach()


# Aliases for the counter under likely names.
SQLCounter = SqlCounter
SelectCounter = SqlCounter
QueryCounter = SqlCounter
SqlStatementCounter = SqlCounter
StatementCounter = SqlCounter
Counter = SqlCounter


@contextlib.contextmanager
def sql_counter(engine: AsyncEngine | None = None) -> Iterator[SqlCounter]:
    counter = SqlCounter(engine)
    try:
        yield counter
    finally:
        counter.detach()


@contextlib.contextmanager
def count_sql(engine: AsyncEngine | None = None) -> Iterator[SqlCounter]:
    counter = SqlCounter(engine)
    try:
        yield counter
    finally:
        counter.detach()


@contextlib.contextmanager
def count_sql_statements(engine: AsyncEngine | None = None) -> Iterator[SqlCounter]:
    counter = SqlCounter(engine)
    try:
        yield counter
    finally:
        counter.detach()


@contextlib.asynccontextmanager
async def async_sql_counter(engine: AsyncEngine | None = None) -> Any:
    counter = SqlCounter(engine)
    try:
        yield counter
    finally:
        counter.detach()


def sql_counter_for(engine: AsyncEngine) -> SqlCounter:
    return SqlCounter(engine)


def make_sql_counter(engine: AsyncEngine) -> SqlCounter:
    return SqlCounter(engine)


# --- Facade builders -------------------------------------------------------


def _engine_from(database_url: str | None, engine: AsyncEngine | None) -> AsyncEngine:
    if engine is not None:
        return engine
    if database_url is None:
        raise ValueError("database_url or engine is required")
    return create_async_engine(database_url, poolclass=NullPool)


def _ttl(cache_enabled: bool, ttl_seconds: int | None) -> int | None:
    if not cache_enabled:
        return 0
    if ttl_seconds is None:
        return None
    return ttl_seconds


def build_partner_facade(
    database_url: str | None = None,
    engine: AsyncEngine | None = None,
    tmp_path: Path | None = None,
    *,
    cache_enabled: bool = True,
    cache_on: bool | None = None,
    cached: bool | None = None,
    directory_ttl_seconds: int = 300,
    profile_cache_ttl_seconds: int | None = None,
    return_engine: bool = False,
    **_kwargs: Any,
) -> Any:
    if cache_on is not None:
        cache_enabled = cache_on
    if cached is not None:
        cache_enabled = cached
    path = tmp_path if tmp_path is not None else Path(tempfile.mkdtemp())
    eng = _engine_from(database_url, engine)
    iam = None
    partner = None
    from modules.iam.adapters.sms import MockSmsAdapter
    from modules.iam.facade import IamFacade
    from modules.partner.adapters.artifact_store import CredentialArtifactStore
    from modules.partner.facade import PartnerFacade

    iam = IamFacade(
        engine=eng,
        sms_adapter=MockSmsAdapter(),
        profile_cache_ttl_seconds=_ttl(
            cache_enabled,
            profile_cache_ttl_seconds
            if profile_cache_ttl_seconds is not None
            else (300 if cache_enabled else 0),
        ),
    )
    store = CredentialArtifactStore(root=path, key_bytes=bytes(32))
    partner = PartnerFacade(
        engine=eng,
        iam_facade=iam,
        artifact_store=store,
        directory_ttl_seconds=_ttl(cache_enabled, directory_ttl_seconds),
    )
    if return_engine:
        return eng, iam, partner
    return iam, partner


build_facade = build_partner_facade
build_cached_facade = build_partner_facade
make_partner_facade = build_partner_facade
make_facade = build_partner_facade
partner_facade_builder = build_partner_facade


def build_iam_facade(
    database_url: str | None = None,
    engine: AsyncEngine | None = None,
    *,
    cache_enabled: bool = True,
    cache_on: bool | None = None,
    profile_cache_ttl_seconds: int = 300,
    return_engine: bool = False,
    **_kwargs: Any,
) -> Any:
    if cache_on is not None:
        cache_enabled = cache_on
    eng = _engine_from(database_url, engine)
    from modules.iam.adapters.sms import MockSmsAdapter
    from modules.iam.facade import IamFacade

    iam = IamFacade(
        engine=eng,
        sms_adapter=MockSmsAdapter(),
        profile_cache_ttl_seconds=_ttl(cache_enabled, profile_cache_ttl_seconds),
    )
    if return_engine:
        return eng, iam
    return iam


build_profile_facade = build_iam_facade
make_iam_facade = build_iam_facade
make_profile_facade = build_iam_facade


def build_intake_facade(
    database_url: str | None = None,
    engine: AsyncEngine | None = None,
    *,
    cache_enabled: bool = True,
    cache_on: bool | None = None,
    intake_cache_ttl_seconds: int = 120,
    media_store: Any = None,
    ai_gateway: Any = None,
    consent_facade: Any = None,
    iam_facade: Any = None,
    return_engine: bool = False,
    **_kwargs: Any,
) -> Any:
    if cache_on is not None:
        cache_enabled = cache_on
    eng = _engine_from(database_url, engine)
    from modules.intake.facade import IntakeFacade

    facade = IntakeFacade(
        engine=eng,
        media_store=media_store,
        ai_gateway=ai_gateway,
        consent_facade=consent_facade,
        iam_facade=iam_facade,
        intake_cache_ttl_seconds=_ttl(cache_enabled, intake_cache_ttl_seconds),
    )
    if return_engine:
        return eng, facade
    return facade


make_intake_facade = build_intake_facade


def build_care_facade(
    database_url: str | None = None,
    engine: AsyncEngine | None = None,
    *,
    cache_enabled: bool = True,
    cache_on: bool | None = None,
    care_cases_cache_ttl_seconds: int = 60,
    intake_facade: Any = None,
    return_engine: bool = False,
    **_kwargs: Any,
) -> Any:
    if cache_on is not None:
        cache_enabled = cache_on
    eng = _engine_from(database_url, engine)
    from modules.care.case_facade import CaseConsoleFacade
    from modules.intake.facade import IntakeFacade

    if intake_facade is None:
        intake_facade = IntakeFacade(engine=eng)
    facade = CaseConsoleFacade(
        engine=eng,
        intake_facade=intake_facade,
        care_cases_cache_ttl_seconds=_ttl(cache_enabled, care_cases_cache_ttl_seconds),
    )
    if return_engine:
        return eng, facade
    return facade


make_care_facade = build_care_facade
build_case_facade = build_care_facade


def build_observability_facade(
    database_url: str | None = None,
    engine: AsyncEngine | None = None,
    *,
    cache_enabled: bool = True,
    cache_on: bool | None = None,
    provider_health_cache_ttl_seconds: int = 30,
    settings: Any = None,
    ops_facade: Any = None,
    return_engine: bool = False,
    **_kwargs: Any,
) -> Any:
    if cache_on is not None:
        cache_enabled = cache_on
    eng = _engine_from(database_url, engine)
    from modules.observability.facade import ObservabilityFacade

    facade = ObservabilityFacade(
        engine=eng,
        settings=settings,
        ops_facade=ops_facade,
        provider_health_cache_ttl_seconds=_ttl(cache_enabled, provider_health_cache_ttl_seconds),
    )
    if return_engine:
        return eng, facade
    return facade


make_observability_facade = build_observability_facade
build_provider_health_facade = build_observability_facade


def build_facade_for(module: str, *args: Any, **kwargs: Any) -> Any:
    module = (module or "").lower()
    if module in {"partner", "directory"}:
        return build_partner_facade(*args, **kwargs)
    if module in {"iam", "profile"}:
        return build_iam_facade(*args, **kwargs)
    if module in {"intake"}:
        return build_intake_facade(*args, **kwargs)
    if module in {"care", "case", "cases"}:
        return build_care_facade(*args, **kwargs)
    if module in {"observability", "provider_health", "provider-health"}:
        return build_observability_facade(*args, **kwargs)
    raise ValueError(f"unknown cache facade module: {module}")


# Null helper for teardown.
def dispose_engine(engine: AsyncEngine) -> None:
    import asyncio

    with contextlib.suppress(RuntimeError):
        asyncio.run(engine.dispose())


# Re-export convenience aliases.
