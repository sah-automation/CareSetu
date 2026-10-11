"""#648 (FEAT-002): the consent read models carry a counterparty display name.

``ConsentView`` and ``EgressLogEntry`` each gain one optional, nullable
``counterparty_display_name`` (#645). The name is an enrichment of an id, never
the authorization: the id stays on the wire, and a missing name never changes
whether a grant is live. Resolution is an injected keyword-only resolver
callable, not an import - the consent module learns no other module's name, and
the binding that supplies real names lives at the composition root (#649).

Whatever the seam answers it degrades: unbound resolver, resolver exception, and
an unresolvable counterparty all leave the field null. A failure logs one
warning naming the counterparty **type** only - never the id, never PHI.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from modules.consent.facade import ConsentFacade

_NOW = datetime(2026, 8, 24, 12, 0, 0, tzinfo=UTC)


class _FakeResult:
    """Mimics asyncpg ``CursorResult.all()`` - the only shape these reads use."""

    def __init__(self, rows: list[object] | None = None) -> None:
        self._rows = rows or []

    def all(self) -> list[object]:
        return self._rows


def _connection(execute_results: list[object]) -> AsyncMock:
    connection = AsyncMock()
    connection.execute = AsyncMock(side_effect=execute_results)
    return connection


def _engine(connection: AsyncMock) -> AsyncMock:
    engine = AsyncMock(spec=AsyncEngine)
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=connection)
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    return engine


def _lineage_row(
    *,
    consent_id: int = 1,
    counterparty_type: str = "doctor",
    counterparty_id: str = "dr-77",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=consent_id,
        patient_id=7,
        counterparty_type=counterparty_type,
        counterparty_id=counterparty_id,
        record_scope="consultations",
        lineage_ref="C-2026-004",
        status="granted",
        version=1,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _egress_row(
    *,
    egress_id: int = 5,
    counterparty_type: str = "doctor",
    counterparty_id: str = "dr-77",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=egress_id,
        patient_id=7,
        consent_id=1,
        lineage_ref="C-2026-004",
        version=1,
        counterparty_type=counterparty_type,
        counterparty_id=counterparty_id,
        record_scope="consultations",
        disclosed_entry_ids=[10],
        disclosed_at=_NOW,
    )


def _consents_connection() -> AsyncMock:
    return _connection([_FakeResult([_lineage_row()]), _FakeResult([])])


def _egress_connection() -> AsyncMock:
    return _connection([_FakeResult([_egress_row()])])


class _RecordingResolver:
    """A resolver that answers a fixed name and records what it was asked."""

    def __init__(self, name: str | None = "Sunrise Clinic") -> None:
        self.name = name
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, counterparty_type: str, counterparty_id: str) -> str | None:
        self.calls.append((counterparty_type, counterparty_id))
        return self.name


class _FailingResolver:
    async def __call__(self, counterparty_type: str, counterparty_id: str) -> str | None:
        raise RuntimeError("partner seam unavailable")


# ---------------------------------------------------------------------------
# The seam is optional: engine-only construction keeps working
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_engine_only_construction_answers_the_consent_name_present_and_null() -> None:
    facade = ConsentFacade(engine=_engine(_consents_connection()))

    log = await facade.list_consents(patient_id=7)

    # Present and null, not missing: the frontend's fallback chain depends on the
    # key always being there.
    assert log.model_dump()["items"][0]["counterparty_display_name"] is None
    assert log.items[0].counterparty_id == "dr-77"


@pytest.mark.asyncio
async def test_engine_only_construction_answers_the_egress_name_present_and_null() -> None:
    facade = ConsentFacade(engine=_engine(_egress_connection()))

    log = await facade.list_egress_log(patient_id=7)

    assert log.model_dump()["items"][0]["counterparty_display_name"] is None
    assert log.items[0].counterparty_id == "dr-77"


# ---------------------------------------------------------------------------
# A bound resolver answers both reads
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_bound_resolver_names_the_consent_read() -> None:
    resolver = _RecordingResolver()
    facade = ConsentFacade(
        engine=_engine(_consents_connection()),
        counterparty_display_name_resolver=resolver,
    )

    log = await facade.list_consents(patient_id=7)

    assert log.items[0].counterparty_display_name == "Sunrise Clinic"
    assert resolver.calls == [("doctor", "dr-77")]


@pytest.mark.asyncio
async def test_a_bound_resolver_names_the_egress_read() -> None:
    resolver = _RecordingResolver()
    facade = ConsentFacade(
        engine=_engine(_egress_connection()),
        counterparty_display_name_resolver=resolver,
    )

    log = await facade.list_egress_log(patient_id=7)

    assert log.items[0].counterparty_display_name == "Sunrise Clinic"
    assert resolver.calls == [("doctor", "dr-77")]


@pytest.mark.asyncio
async def test_an_unresolvable_counterparty_stays_null() -> None:
    facade = ConsentFacade(
        engine=_engine(_consents_connection()),
        counterparty_display_name_resolver=_RecordingResolver(None),
    )

    log = await facade.list_consents(patient_id=7)

    assert log.items[0].counterparty_display_name is None
    assert log.items[0].counterparty_id == "dr-77"


# ---------------------------------------------------------------------------
# A raising resolver degrades and never leaks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_raising_resolver_degrades_the_consent_read_to_null(
    caplog: pytest.LogCaptureFixture,
) -> None:
    facade = ConsentFacade(
        engine=_engine(_consents_connection()),
        counterparty_display_name_resolver=_FailingResolver(),
    )

    with caplog.at_level(logging.WARNING, logger="modules.consent.facade"):
        log = await facade.list_consents(patient_id=7)

    assert log.items[0].counterparty_display_name is None
    assert log.items[0].counterparty_id == "dr-77"
    warnings = [
        record.getMessage() for record in caplog.records if record.levelno == logging.WARNING
    ]
    assert len(warnings) == 1
    assert "doctor" in warnings[0]
    # The counterparty id and any PHI stay out of the log line.
    assert "dr-77" not in warnings[0]


@pytest.mark.asyncio
async def test_a_raising_resolver_degrades_the_egress_read_to_null(
    caplog: pytest.LogCaptureFixture,
) -> None:
    facade = ConsentFacade(
        engine=_engine(_egress_connection()),
        counterparty_display_name_resolver=_FailingResolver(),
    )

    with caplog.at_level(logging.WARNING, logger="modules.consent.facade"):
        log = await facade.list_egress_log(patient_id=7)

    assert log.items[0].counterparty_display_name is None
    warnings = [
        record.getMessage() for record in caplog.records if record.levelno == logging.WARNING
    ]
    assert len(warnings) == 1
    assert "doctor" in warnings[0]
    assert "dr-77" not in warnings[0]
