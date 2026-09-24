"""Ticket #535: the health-background height/weight series facade.

Pins the append (identity-scoped insert, server-minted id, Decimal->float
serialization) and the read (bounded page, newest-first ordering on
``(recorded_at, id)``, identity scoping, empty page for a patient with no
measurements) against a mocked transaction (coding-standards A2: DB-free unit
surface; module isolation rule). The at-least-one-value and extra-field-refused
rules are pinned at the request-model boundary, matching the route contract.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from modules.health.facade import HealthBackgroundMetric, HealthFacade

_NOW = datetime(2026, 9, 24, 12, 0, 0, tzinfo=UTC)


class _FakeResult:
    """One execute reply: one() / first() / all() for the read shapes used."""

    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self._rows = rows

    def one(self) -> SimpleNamespace:
        return self._rows[0]

    def first(self) -> SimpleNamespace | None:
        return self._rows[0] if self._rows else None

    def all(self) -> list[SimpleNamespace]:
        return self._rows


def _engine(connection: AsyncMock) -> MagicMock:
    engine = MagicMock()
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=connection)
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    return engine


def _compiled(stmt: object) -> str:
    """Compile the statement and strip the schema prefix (audit-test precedent).

    ``test_audit_query_facade`` strips ``audit.`` the same way, so the
    assertions read against unqualified column names.
    """
    return str(stmt.compile(dialect=postgresql.dialect())).replace("health.", "")


def _metric_row(
    *,
    entry_id: int = 101,
    height_cm: Decimal | None,
    weight_kg: Decimal | None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=entry_id,
        height_cm=height_cm,
        weight_kg=weight_kg,
        recorded_at=_NOW,
    )


async def test_append_inserts_identity_scoped_row_and_returns_the_entry() -> None:
    connection = AsyncMock()
    connection.execute = AsyncMock(
        return_value=_FakeResult(
            [_metric_row(height_cm=Decimal("172.0"), weight_kg=Decimal("68.50"))]
        )
    )
    facade = HealthFacade(_engine(connection))

    entry = await facade.append_health_background_metric(
        7, HealthBackgroundMetric(height_cm=172.0, weight_kg=68.5, recorded_at=_NOW)
    )

    assert entry.entry_id == 101
    assert entry.height_cm == 172.0
    assert entry.weight_kg == 68.5
    assert entry.recorded_at == _NOW
    (insert_stmt,) = connection.execute.await_args.args
    sql = _compiled(insert_stmt)
    assert "INSERT INTO health_background_metrics" in sql
    assert "identity_id" in sql
    assert "recorded_at" in sql
    # The id is minted by the table and read back in the same round trip.
    assert "RETURNING health_background_metrics.id" in sql


async def test_append_with_only_one_measurement_stores_the_present_value() -> None:
    connection = AsyncMock()
    connection.execute = AsyncMock(
        return_value=_FakeResult([_metric_row(height_cm=Decimal("172.0"), weight_kg=None)])
    )
    facade = HealthFacade(_engine(connection))

    entry = await facade.append_health_background_metric(
        7, HealthBackgroundMetric(height_cm=172.0, recorded_at=_NOW)
    )

    assert entry.entry_id == 101
    assert entry.height_cm == 172.0
    assert entry.weight_kg is None
    assert entry.recorded_at == _NOW
    (insert_stmt,) = connection.execute.await_args.args
    assert "INSERT INTO health_background_metrics" in _compiled(insert_stmt)


async def test_list_empty_answers_an_empty_page() -> None:
    connection = AsyncMock()
    connection.scalar = AsyncMock(return_value=0)
    connection.execute = AsyncMock(return_value=_FakeResult([]))
    facade = HealthFacade(_engine(connection))

    page = await facade.list_health_background_metrics(7)

    assert page.items == []
    assert page.total == 0


async def test_list_orders_newest_first_and_paginates() -> None:
    connection = AsyncMock()
    connection.scalar = AsyncMock(return_value=5)
    connection.execute = AsyncMock(
        return_value=_FakeResult(
            [
                _metric_row(entry_id=105, height_cm=Decimal("171.5"), weight_kg=Decimal("68.00")),
                _metric_row(entry_id=104, height_cm=Decimal("171.5"), weight_kg=Decimal("67.50")),
            ]
        )
    )
    facade = HealthFacade(_engine(connection))

    page = await facade.list_health_background_metrics(7, page=3, per_page=2)

    assert [item.entry_id for item in page.items] == [105, 104]
    assert page.total == 5
    page_stmt = connection.execute.await_args.args[0]
    sql = _compiled(page_stmt)
    assert "ORDER BY health_background_metrics.recorded_at DESC" in sql
    assert "health_background_metrics.id DESC" in sql
    assert "LIMIT" in sql
    assert "OFFSET" in sql


async def test_list_scopes_to_the_patient_identity() -> None:
    connection = AsyncMock()
    connection.scalar = AsyncMock(return_value=0)
    connection.execute = AsyncMock(return_value=_FakeResult([]))
    facade = HealthFacade(_engine(connection))

    await facade.list_health_background_metrics(7)

    count_stmt = connection.scalar.await_args.args[0]
    page_stmt = connection.execute.await_args.args[0]
    # Both the series count and the page read are pinned to the caller's
    # identity - a patient's list can never see another patient's rows.
    assert "health_background_metrics.identity_id = %(identity_id_1)s" in _compiled(count_stmt)
    assert "health_background_metrics.identity_id = %(identity_id_1)s" in _compiled(page_stmt)


def test_append_row_ids_are_never_client_supplied_at_the_model_boundary() -> None:
    with pytest.raises(ValidationError):
        HealthBackgroundMetric(
            height_cm=172.0,
            weight_kg=68.5,
            recorded_at=_NOW,
            id=999,
            entry_id=999,
        )


def test_append_model_requires_at_least_one_measurement() -> None:
    with pytest.raises(ValidationError):
        HealthBackgroundMetric(recorded_at=_NOW)

    with pytest.raises(ValidationError):
        HealthBackgroundMetric(height_cm=300.0, recorded_at=_NOW)

    with pytest.raises(ValidationError):
        HealthBackgroundMetric(weight_kg=0.5, recorded_at=_NOW)
