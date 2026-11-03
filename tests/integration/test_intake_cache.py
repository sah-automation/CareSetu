"""ARCH-P2 #839 / FEAT-006: intake detail and pre-summary read-cache verification.

Proves the ``MOD-005`` patient intake caches against a real Postgres engine and
a fake Redis:

* the first read executes SQL and a fresh second read is a cache hit, for both
  the intake detail key and the pre-summary key;
* each mutation (re-record, patient edits, doctor review) invalidates the
  affected key and leaves the other key warm;
* a Redis miss or a Redis error falls back to SQL;
* a malformed or incompatible payload is treated as a miss, never a typed
  failure;
* the PHI gate blocks caching when ``PHI_CACHE_ENABLED`` is off.

Uses the shared cache fixtures (#829) and skips cleanly when PostgreSQL is
unreachable.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, TypeVar

import pytest
import pytest_asyncio
from cache_fixtures import (
    FakeRedis,
    SqlCounter,
    build_intake_facade,
)
from cache_fixtures import fake_redis as fake_redis_client
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from modules.intake.facade import IntakeFacade
from modules.intake.intake_models import IntakeDetailView, MediaUploadRef, PreSummaryView
from modules.intake.schema.models import intake_intakes, intake_pre_summaries

_PATIENT_ID = 990_001
_DOCTOR_ID = 990_002
_PHI_ENV_VARS = ("PHI_CACHE_ENABLED", "REDIS_URL")
_REDIS_URL = "redis://localhost:6379/0"


#: Full key the facade writes for the intake detail read. Named here only to
#: seed malformed/missing payloads; every other assertion observes SQL counts.
def _detail_key(patient_id: int, intake_id: int) -> str:
    return f"intake:{patient_id}:{intake_id}"


def _pre_summary_key(patient_id: int, intake_id: int) -> str:
    return f"intake:{patient_id}:{intake_id}:pre_summary"


_INTAKE_TABLES = (
    "intake.intake_outbox",
    "intake.intake_ai_jobs",
    "intake.intake_pre_summaries",
    "intake.intake_media_refs",
    "intake.intake_intakes",
    "intake.consumed_events",
)

_STRUCTURED_FIELDS = {
    "chief_complaints": ["fever"],
    "symptoms": ["headache", "body ache"],
    "duration": "2 days",
}


class _ErrorRedis(FakeRedis):
    """A fake Redis whose reads and writes always fail."""

    async def get(self, key: str) -> str | None:
        raise RuntimeError("redis unavailable")

    async def set(self, *args: Any, **kwargs: Any) -> bool | None:
        raise RuntimeError("redis unavailable")


_T = TypeVar("_T")


@pytest_asyncio.fixture(autouse=True)
async def clean_intake(database_url: str, migrated_schema: None) -> AsyncIterator[None]:
    """Empty the intake tables before every test for a clean slate."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("TRUNCATE TABLE " + ", ".join(_INTAKE_TABLES) + " CASCADE")
            )
    finally:
        await engine.dispose()
    yield


@pytest.fixture(autouse=True)
def clear_phi_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the PHI gate off unless a test opts in."""
    for name in _PHI_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def phi_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the cache with the PHI gate open and a configured Redis URL."""
    monkeypatch.setenv("PHI_CACHE_ENABLED", "true")
    monkeypatch.setenv("REDIS_URL", _REDIS_URL)


@pytest.fixture(autouse=True)
def cache_client(fake_redis: FakeRedis) -> FakeRedis:
    """Install the fake Redis as the shared cache client for every test."""
    return fake_redis


def _build_intake(database_url: str) -> tuple[AsyncEngine, IntakeFacade]:
    return build_intake_facade(database_url=database_url, return_engine=True)


async def _submit(facade: IntakeFacade, patient_id: int = _PATIENT_ID) -> int:
    submitted = await facade.submit_intake(
        patient_id=patient_id,
        mode="text",
        language="hi",
        text="sir dard hai aur bukhar bhi",
    )
    return submitted.intake_id


async def _seed_pre_summary(
    engine: AsyncEngine,
    intake_id: int,
    *,
    confidence: float = 0.9,
) -> int:
    async with engine.begin() as connection:
        result = await connection.execute(
            intake_pre_summaries.insert()
            .values(
                intake_id=intake_id,
                structured_fields=_STRUCTURED_FIELDS,
                structuring_confidence=confidence,
            )
            .returning(intake_pre_summaries.c.id)
        )
        return int(result.scalar_one())


async def _set_status(engine: AsyncEngine, intake_id: int, status: str) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            intake_intakes.update().where(intake_intakes.c.id == intake_id).values(status=status)
        )


async def _count_selects(engine: AsyncEngine, call: Callable[[], Awaitable[_T]]) -> tuple[_T, int]:
    counter = SqlCounter(engine)
    try:
        return await call(), counter.count
    finally:
        counter.detach()


def _read_detail(
    facade: IntakeFacade, intake_id: int, patient_id: int = _PATIENT_ID
) -> Callable[[], Awaitable[Any]]:
    return lambda: facade.get_intake(intake_id=intake_id, patient_id=patient_id)


def _read_pre_summary(
    facade: IntakeFacade, intake_id: int, patient_id: int = _PATIENT_ID
) -> Callable[[], Awaitable[PreSummaryView]]:
    return lambda: facade.get_pre_summary(intake_id=intake_id, patient_id=patient_id)


async def _assert_detail_sql_read(
    facade: IntakeFacade, engine: AsyncEngine, intake_id: int
) -> None:
    result, selects = await _count_selects(engine, _read_detail(facade, intake_id))
    assert result.intake_id == intake_id
    assert selects >= 1


async def _assert_pre_summary_sql_read(
    facade: IntakeFacade, engine: AsyncEngine, intake_id: int
) -> PreSummaryView:
    result, selects = await _count_selects(engine, _read_pre_summary(facade, intake_id))
    assert result.intake_id == intake_id
    assert selects >= 1
    return result


@pytest.mark.asyncio
async def test_submit_intake_invalidates_a_stale_cached_detail_key(
    database_url: str, phi_enabled: None, fake_redis: FakeRedis
) -> None:
    engine, facade = _build_intake(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("TRUNCATE TABLE " + ", ".join(_INTAKE_TABLES) + " RESTART IDENTITY CASCADE")
            )

        # Stale, mutated entry left in the cache for the id about to be assigned:
        # a detail row claiming "voice" mode. submit_intake must evict it so the
        # post-submit read resolves from SQL instead of serving the stale row.
        stale = IntakeDetailView(
            intake_id=1,
            patient_id=_PATIENT_ID,
            mode="voice",
            language="hi",
            status="captured",
            record_attempts=1,
            text=None,
            transcript=None,
            transcript_usability=None,
            forced_text=False,
            media_refs=[],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ).model_dump(mode="json")
        fake_redis.store[_detail_key(_PATIENT_ID, 1)] = json.dumps(stale)

        submitted = await facade.submit_intake(
            patient_id=_PATIENT_ID,
            mode="text",
            language="hi",
            text="sir dard hai aur bukhar bhi",
        )
        assert submitted.intake_id == 1

        # The invalidated cache falls back to SQL on the very first post-submit
        # read, and the row served is the freshly submitted one (text mode).
        result, selects = await _count_selects(engine, _read_detail(facade, submitted.intake_id))
        assert selects >= 1
        assert result.mode == "text"
        assert result.text == "sir dard hai aur bukhar bhi"

        # Having re-populated the cache, a fresh second read is a hit again.
        second, second_selects = await _count_selects(
            engine, _read_detail(facade, submitted.intake_id)
        )
        assert second.mode == "text"
        assert second_selects == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_detail_first_read_executes_sql_and_fresh_second_read_hits(
    database_url: str, phi_enabled: None
) -> None:
    engine, facade = _build_intake(database_url)
    try:
        intake_id = await _submit(facade)

        first, first_selects = await _count_selects(engine, _read_detail(facade, intake_id))
        assert first.intake_id == intake_id
        assert first.status == "captured"
        assert first_selects >= 1

        second, second_selects = await _count_selects(engine, _read_detail(facade, intake_id))
        assert second.intake_id == first.intake_id
        assert second.status == first.status
        assert second.text == first.text
        assert second.media_refs == first.media_refs
        assert second_selects == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_pre_summary_first_read_executes_sql_and_fresh_second_read_hits(
    database_url: str, phi_enabled: None
) -> None:
    engine, facade = _build_intake(database_url)
    try:
        intake_id = await _submit(facade)
        await _seed_pre_summary(engine, intake_id)

        first, first_selects = await _count_selects(engine, _read_pre_summary(facade, intake_id))
        assert first.intake_id == intake_id
        assert first.review_state == "draft"
        assert first.structured_fields.chief_complaints == ["fever"]
        assert first_selects >= 1

        second, second_selects = await _count_selects(engine, _read_pre_summary(facade, intake_id))
        assert second.intake_id == first.intake_id
        assert second.review_state == first.review_state
        assert second.structured_fields == first.structured_fields
        assert second.low_confidence == first.low_confidence
        assert second_selects == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_re_record_invalidates_the_detail_key(database_url: str, phi_enabled: None) -> None:
    engine, facade = _build_intake(database_url)
    try:
        intake_id = await _submit(facade)

        await _assert_detail_sql_read(facade, engine, intake_id)
        _, warm_selects = await _count_selects(engine, _read_detail(facade, intake_id))
        assert warm_selects == 0

        # Warm the pre-summary key as well so its survival of the detail
        # invalidation is observable alongside the detail (affected-key-only).
        await _seed_pre_summary(engine, intake_id)
        await _assert_pre_summary_sql_read(facade, engine, intake_id)
        _, pre_summary_warm = await _count_selects(engine, _read_pre_summary(facade, intake_id))
        assert pre_summary_warm == 0

        # Put the intake into the re-record state out of band: the cached detail
        # still says "captured", so a served hit would be stale.
        await _set_status(engine, intake_id, "re_record")

        re_recorded = await facade.re_record_intake(
            intake_id=intake_id,
            patient_id=_PATIENT_ID,
            media_ref=MediaUploadRef(
                object_key="intake/re-record-1",
                media_type="audio",
                audio_duration_ms=5_000,
                file_size_bytes=1_024,
                record_attempt=2,
            ),
        )
        assert re_recorded.accepted is True
        assert re_recorded.status == "structuring"

        result, selects = await _count_selects(engine, _read_detail(facade, intake_id))
        assert selects >= 1
        assert result.status == "structuring"
        assert result.record_attempts == 2

        # The pre-summary key was not affected by the detail invalidation.
        _, pre_summary_selects = await _count_selects(engine, _read_pre_summary(facade, intake_id))
        assert pre_summary_selects == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_patient_edits_invalidate_only_the_pre_summary_key(
    database_url: str, phi_enabled: None
) -> None:
    engine, facade = _build_intake(database_url)
    try:
        intake_id = await _submit(facade)
        await _seed_pre_summary(engine, intake_id)

        # Warm both keys so the mutation's scoping is observable.
        await _assert_detail_sql_read(facade, engine, intake_id)
        await _assert_pre_summary_sql_read(facade, engine, intake_id)

        await facade.save_patient_pre_summary_edits(
            intake_id=intake_id,
            patient_id=_PATIENT_ID,
            fields={"duration": "3 days"},
        )

        # Pre-summary key was invalidated: the next read executes SQL.
        view = await _assert_pre_summary_sql_read(facade, engine, intake_id)
        assert view.patient_edits == {"duration": "3 days"}

        # Detail key was untouched: still a warm hit.
        _, detail_selects = await _count_selects(engine, _read_detail(facade, intake_id))
        assert detail_selects == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_doctor_review_invalidates_only_the_pre_summary_key(
    database_url: str, phi_enabled: None
) -> None:
    engine, facade = _build_intake(database_url)
    try:
        intake_id = await _submit(facade)
        await _seed_pre_summary(engine, intake_id)

        await _assert_detail_sql_read(facade, engine, intake_id)
        await _assert_pre_summary_sql_read(facade, engine, intake_id)

        reviewed = await facade.mark_pre_summary_reviewed(
            intake_id=intake_id,
            doctor_id=_DOCTOR_ID,
            corrections={"duration": "4 days"},
        )
        assert reviewed.review_state == "final"

        view = await _assert_pre_summary_sql_read(facade, engine, intake_id)
        assert view.review_state == "final"
        assert view.structured_fields.duration == "4 days"
        assert view.reviewed_by == _DOCTOR_ID

        _, detail_selects = await _count_selects(engine, _read_detail(facade, intake_id))
        assert detail_selects == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_redis_miss_falls_back_to_sql_for_both_keys(
    database_url: str, phi_enabled: None, fake_redis: FakeRedis
) -> None:
    engine, facade = _build_intake(database_url)
    try:
        intake_id = await _submit(facade)
        await _seed_pre_summary(engine, intake_id)

        await _assert_detail_sql_read(facade, engine, intake_id)
        await _assert_pre_summary_sql_read(facade, engine, intake_id)

        # Evict every entry: both reads fall back to SQL and re-populate.
        await fake_redis.flushdb()

        await _assert_detail_sql_read(facade, engine, intake_id)
        await _assert_pre_summary_sql_read(facade, engine, intake_id)

        _, detail_selects = await _count_selects(engine, _read_detail(facade, intake_id))
        _, pre_summary_selects = await _count_selects(engine, _read_pre_summary(facade, intake_id))
        assert detail_selects == 0
        assert pre_summary_selects == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_redis_error_falls_back_to_sql_for_both_keys(
    database_url: str, phi_enabled: None
) -> None:
    engine, facade = _build_intake(database_url)
    try:
        with fake_redis_client(_ErrorRedis()):
            intake_id = await _submit(facade)
            await _seed_pre_summary(engine, intake_id)

            await _assert_detail_sql_read(facade, engine, intake_id)
            await _assert_pre_summary_sql_read(facade, engine, intake_id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", ["[1, 2, 3]", '{"intake_id": "not-an-int"}'])
async def test_malformed_detail_payload_is_a_miss(
    database_url: str, phi_enabled: None, fake_redis: FakeRedis, payload: str
) -> None:
    engine, facade = _build_intake(database_url)
    try:
        intake_id = await _submit(facade)
        fake_redis.store[_detail_key(_PATIENT_ID, intake_id)] = payload

        await _assert_detail_sql_read(facade, engine, intake_id)

        # The miss recomputed and re-cached a valid payload.
        _, selects = await _count_selects(engine, _read_detail(facade, intake_id))
        assert selects == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", ["[1, 2, 3]", '{"review_state": "draft"}'])
async def test_malformed_pre_summary_payload_is_a_miss(
    database_url: str, phi_enabled: None, fake_redis: FakeRedis, payload: str
) -> None:
    engine, facade = _build_intake(database_url)
    try:
        intake_id = await _submit(facade)
        await _seed_pre_summary(engine, intake_id)
        fake_redis.store[_pre_summary_key(_PATIENT_ID, intake_id)] = payload

        await _assert_pre_summary_sql_read(facade, engine, intake_id)

        _, selects = await _count_selects(engine, _read_pre_summary(facade, intake_id))
        assert selects == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_phi_gate_blocks_cache_when_disabled_and_allows_when_enabled(
    database_url: str,
    phi_enabled: None,
    monkeypatch: pytest.MonkeyPatch,
    fake_redis: FakeRedis,
) -> None:
    engine, facade = _build_intake(database_url)
    try:
        intake_id = await _submit(facade)
        await _seed_pre_summary(engine, intake_id)

        # Gate open: first read executes SQL, second read is a warm hit.
        await _assert_detail_sql_read(facade, engine, intake_id)
        _, warm_detail_selects = await _count_selects(engine, _read_detail(facade, intake_id))
        assert warm_detail_selects == 0

        await _assert_pre_summary_sql_read(facade, engine, intake_id)
        _, warm_pre_summary_selects = await _count_selects(
            engine, _read_pre_summary(facade, intake_id)
        )
        assert warm_pre_summary_selects == 0

        # Gate closed: every read executes SQL and nothing is written to Redis.
        monkeypatch.setenv("PHI_CACHE_ENABLED", "false")
        fake_redis.store.clear()

        await _assert_detail_sql_read(facade, engine, intake_id)
        await _assert_detail_sql_read(facade, engine, intake_id)
        await _assert_pre_summary_sql_read(facade, engine, intake_id)
        await _assert_pre_summary_sql_read(facade, engine, intake_id)

        assert fake_redis.store == {}
    finally:
        await engine.dispose()
