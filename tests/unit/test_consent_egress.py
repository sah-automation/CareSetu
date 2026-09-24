"""#531: the consent egress ledger accepts the health_background record scope.

Pins ``record_egress_disclosure`` and ``seed_egress_log`` against a mocked
connection (coding-standards A2, module-isolation rule): the new scope value
flows into the ``consent_egress_log`` row unchanged, and each write happens
inside the facade's own transaction. The prior-art shape is the access-history
and outbox facade tests.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from sqlalchemy.ext.asyncio import AsyncEngine

from modules.consent.facade import ConsentFacade


class _FakeResult:
    """Mimics query-result shapes: ``scalar_one``/``scalar_one_or_none``/``all``."""

    def __init__(self, scalar: object | None = None) -> None:
        self._scalar = scalar

    def scalar_one(self) -> object:
        return self._scalar

    def scalar_one_or_none(self) -> object | None:
        return self._scalar

    def all(self) -> list:
        return []


def _connection(execute_results: list[object]) -> AsyncMock:
    connection = AsyncMock()
    connection.execute = AsyncMock(side_effect=execute_results)
    return connection


def _engine(connection: AsyncMock) -> AsyncMock:
    engine = AsyncMock(spec=AsyncEngine)
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=connection)
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    return engine


def _insert_params(connection: AsyncMock, index: int) -> dict:
    (stmt,) = connection.execute.await_args_list[index].args
    return stmt.compile().params


async def test_record_egress_disclosure_writes_health_background_row() -> None:
    connection = _connection([_FakeResult()])
    facade = ConsentFacade(engine=_engine(connection))

    await facade.record_egress_disclosure(
        patient_id=7,
        consent_id=None,
        version=1,
        counterparty_type="doctor",
        counterparty_id="dr-77",
        record_scope="health_background",
        disclosed_entry_ids=[10],
    )

    assert connection.execute.await_count == 1
    params = _insert_params(connection, 0)
    assert params["record_scope"] == "health_background"
    assert params["patient_id"] == 7
    assert params["disclosed_entry_ids"] == [10]


async def test_record_egress_disclosure_links_lineage_when_consent_exists() -> None:
    connection = _connection([_FakeResult(scalar="C-2026-004"), _FakeResult()])
    facade = ConsentFacade(engine=_engine(connection))

    await facade.record_egress_disclosure(
        patient_id=7,
        consent_id=9,
        version=1,
        counterparty_type="doctor",
        counterparty_id="dr-77",
        record_scope="health_background",
        disclosed_entry_ids=[10, 11],
    )

    assert connection.execute.await_count == 2
    params = _insert_params(connection, 1)
    assert params["record_scope"] == "health_background"
    assert params["consent_id"] == 9
    assert params["lineage_ref"] == "C-2026-004"


async def test_seed_egress_log_writes_health_background_row_and_returns_its_id() -> None:
    connection = _connection([_FakeResult(scalar=9), _FakeResult(scalar=77)])
    facade = ConsentFacade(engine=_engine(connection))

    result = await facade.seed_egress_log(
        patient_id=7,
        counterparty_type="doctor",
        counterparty_id="dr-77",
        record_scope="health_background",
        disclosed_entry_ids=[10],
    )

    assert result == 77
    params = _insert_params(connection, 1)
    assert params["record_scope"] == "health_background"
    assert params["consent_id"] == 9
