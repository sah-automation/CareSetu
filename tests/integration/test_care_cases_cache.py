"""ARCH-P2 #840 / FEAT-008: care cases read-cache against Postgres + fake Redis.

Proves the ``MOD-006`` case-console cache observable behavior.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, TypeVar

import pytest
import pytest_asyncio
from cache_fixtures import (
    FakeRedis,
    SqlCounter,
    build_care_facade,
)
from cache_fixtures import fake_redis as fake_redis_client
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from modules.care.case_facade import CaseConsoleFacade
from modules.care.schema.models import care_cases
from modules.intake.schema.models import intake_pre_summaries

_PATIENT_ID = 990_003
_DOCTOR_ID = 990_004
_INTAKE_TABLES = (
    "intake.intake_outbox",
    "intake.intake_ai_jobs",
    "intake.intake_pre_summaries",
    "intake.intake_media_refs",
    "intake.intake_intakes",
    "intake.consumed_events",
)
_CARE_TABLES = (
    "care.care_doctor_inputs",
    "care.care_prescriptions",
    "care.care_cases",
    "care.care_outbox",
)
_STRUCTURED_FIELDS = {
    "chief_complaints": ["fever"],
    "symptoms": ["headache", "body ache"],
    "duration": "2 days",
}


class _ErrorRedis(FakeRedis):
    async def get(self, key: str) -> str | None:
        raise RuntimeError("redis unavailable")

    async def set(self, *args: Any, **kwargs: Any) -> bool | None:
        raise RuntimeError("redis unavailable")


_T = TypeVar("_T")


@pytest_asyncio.fixture(autouse=True)
async def clean_care(database_url: str, migrated_schema: None) -> AsyncIterator[None]:
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "TRUNCATE TABLE "
                    + ", ".join(_INTAKE_TABLES + _CARE_TABLES)
                    + " RESTART IDENTITY CASCADE"
                )
            )
    finally:
        await engine.dispose()
    yield


@pytest.fixture(autouse=True)
def cache_client(fake_redis: FakeRedis) -> FakeRedis:
    return fake_redis


def _build_care(database_url: str) -> tuple[AsyncEngine, CaseConsoleFacade]:
    return build_care_facade(database_url=database_url, return_engine=True)


async def _seed_final_pre_summary(engine: AsyncEngine, intake_id: int) -> int:
    async with engine.begin() as connection:
        result = await connection.execute(
            intake_pre_summaries.insert()
            .values(
                intake_id=intake_id,
                structured_fields=_STRUCTURED_FIELDS,
                structuring_confidence=0.9,
                review_state="final",
                low_confidence=False,
                reviewed_by=_DOCTOR_ID,
                review_attribution="doctor",
            )
            .returning(intake_pre_summaries.c.id)
        )
        return int(result.scalar_one())


async def _seed_case(engine: AsyncEngine, facade: CaseConsoleFacade) -> int:
    submitted = await facade._intake_facade.submit_intake(
        patient_id=_PATIENT_ID,
        mode="text",
        language="hi",
        text="care case seed",
    )
    pre_summary_id = await _seed_final_pre_summary(engine, submitted.intake_id)
    async with engine.begin() as connection:
        result = await connection.execute(
            care_cases.insert()
            .values(
                patient_id=_PATIENT_ID,
                doctor_id=_DOCTOR_ID,
                pre_summary_id=pre_summary_id,
                stage="pre_summary",
            )
            .returning(care_cases.c.id)
        )
        return int(result.scalar_one())


async def _count_selects(engine: AsyncEngine, call: Callable[[], Awaitable[_T]]) -> tuple[_T, int]:
    counter = SqlCounter(engine)
    try:
        return await call(), counter.count
    finally:
        counter.detach()


def _read_case(
    facade: CaseConsoleFacade, case_id: int, doctor_id: int = _DOCTOR_ID
) -> Callable[[], Awaitable[Any]]:
    return lambda: facade.get_case(doctor_id=doctor_id, case_id=case_id)


def _read_list(
    facade: CaseConsoleFacade, doctor_id: int = _DOCTOR_ID
) -> Callable[[], Awaitable[Any]]:
    return lambda: facade.list_doctor_cases(doctor_id=doctor_id)


async def _assert_case_sql_read(
    facade: CaseConsoleFacade, engine: AsyncEngine, case_id: int
) -> None:
    result, selects = await _count_selects(engine, _read_case(facade, case_id))
    assert result.case_id == case_id
    assert selects >= 1


async def _assert_list_sql_read(facade: CaseConsoleFacade, engine: AsyncEngine) -> None:
    result, selects = await _count_selects(engine, _read_list(facade))
    assert isinstance(result, list)
    assert selects >= 1


@pytest.mark.asyncio
async def test_case_detail_first_read_executes_sql_and_fresh_second_read_hits(
    database_url: str,
) -> None:
    engine, facade = _build_care(database_url)
    try:
        case_id = await _seed_case(engine, facade)

        first, first_selects = await _count_selects(engine, _read_case(facade, case_id))
        assert first.case_id == case_id
        assert first_selects >= 1

        second, second_selects = await _count_selects(engine, _read_case(facade, case_id))
        assert second.case_id == first.case_id
        assert second_selects == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_doctor_cases_list_first_read_executes_sql_and_fresh_second_read_hits(
    database_url: str,
) -> None:
    engine, facade = _build_care(database_url)
    try:
        await _seed_case(engine, facade)

        first, first_selects = await _count_selects(engine, _read_list(facade))
        assert isinstance(first, list)
        assert first_selects >= 1

        second, second_selects = await _count_selects(engine, _read_list(facade))
        assert [v.case_id for v in second] == [v.case_id for v in first]
        assert second_selects == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_mark_consult_complete_invalidates_case_and_list(database_url: str) -> None:
    engine, facade = _build_care(database_url)
    try:
        case_id = await _seed_case(engine, facade)

        await _assert_case_sql_read(facade, engine, case_id)
        _, warm_case_selects = await _count_selects(engine, _read_case(facade, case_id))
        assert warm_case_selects == 0

        await _assert_list_sql_read(facade, engine)
        _, warm_list_selects = await _count_selects(engine, _read_list(facade))
        assert warm_list_selects == 0

        view = await facade.mark_consult_complete(doctor_id=_DOCTOR_ID, case_id=case_id)
        assert view.stage == "prescription_pending"

        result, case_selects = await _count_selects(engine, _read_case(facade, case_id))
        assert case_selects >= 1
        assert result.stage == "prescription_pending"

        _, list_selects = await _count_selects(engine, _read_list(facade))
        assert list_selects >= 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_close_case_without_rx_invalidates_case_and_list(database_url: str) -> None:
    engine, facade = _build_care(database_url)
    try:
        case_id = await _seed_case(engine, facade)
        await facade.mark_consult_complete(doctor_id=_DOCTOR_ID, case_id=case_id)

        await _assert_case_sql_read(facade, engine, case_id)
        _, warm_case_selects = await _count_selects(engine, _read_case(facade, case_id))
        assert warm_case_selects == 0

        await _assert_list_sql_read(facade, engine)
        _, warm_list_selects = await _count_selects(engine, _read_list(facade))
        assert warm_list_selects == 0

        view = await facade.close_case_without_rx(
            doctor_id=_DOCTOR_ID, case_id=case_id, close_reason="no_show"
        )
        assert view.stage == "closed"

        result, case_selects = await _count_selects(engine, _read_case(facade, case_id))
        assert case_selects >= 1
        assert result.stage == "closed"

        _, list_selects = await _count_selects(engine, _read_list(facade))
        assert list_selects >= 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_redis_miss_falls_back_to_sql_for_case_and_list(
    database_url: str, fake_redis: FakeRedis
) -> None:
    engine, facade = _build_care(database_url)
    try:
        case_id = await _seed_case(engine, facade)

        await _assert_case_sql_read(facade, engine, case_id)
        await _assert_list_sql_read(facade, engine)

        await fake_redis.flushdb()

        await _assert_case_sql_read(facade, engine, case_id)
        await _assert_list_sql_read(facade, engine)

        _, case_selects = await _count_selects(engine, _read_case(facade, case_id))
        _, list_selects = await _count_selects(engine, _read_list(facade))
        assert case_selects == 0
        assert list_selects == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_redis_error_falls_back_to_sql_for_case_and_list(database_url: str) -> None:
    engine, facade = _build_care(database_url)
    try:
        case_id = await _seed_case(engine, facade)
        with fake_redis_client(_ErrorRedis()):
            await _assert_case_sql_read(facade, engine, case_id)
            await _assert_list_sql_read(facade, engine)

            _, case_selects = await _count_selects(engine, _read_case(facade, case_id))
            _, list_selects = await _count_selects(engine, _read_list(facade))
            assert case_selects >= 1
            assert list_selects >= 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", ["[1, 2, 3]", '{"case_id": "not-an-int"}'])
async def test_malformed_case_payload_is_a_miss(
    database_url: str, fake_redis: FakeRedis, payload: str
) -> None:
    engine, facade = _build_care(database_url)
    try:
        case_id = await _seed_case(engine, facade)
        fake_redis.store[f"care:{_DOCTOR_ID}:{case_id}"] = payload

        await _assert_case_sql_read(facade, engine, case_id)

        _, selects = await _count_selects(engine, _read_case(facade, case_id))
        assert selects == 0
    finally:
        await engine.dispose()
