"""PHASE-8 T07: consent-gated history - fail-closed drafting (ticket #423).

Pins the NFR-SEC-006 fail-closed seam that the AI-draft leg of ``CareFacade``
delegates history reads through (``HealthFacade.read_consented_history``, which
calls ``ConsentFacade.check_consent``):

- The consented history read calls ``check_consent`` with the FULL
  patient/scope/counterparty contract - ``RX_DRAFT_HISTORY_SCOPE =
  prescriptions`` for the doctor - and never performs a raw read.
- Allowed: the scoped timeline is returned and the consent ``egress`` row is
  recorded (citing consent id/version and the disclosed entry ids).
- Denied / unconfigured: the read raises and the caller (the AI draft) fails
  closed - no prescription row, no ``care_outbox`` event, no AI draft.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import ClauseElement
from sqlalchemy.ext.asyncio import AsyncEngine

from modules.care.facade import RX_DRAFT_HISTORY_SCOPE, CareFacade
from modules.care.outbox import CARE_OUTBOX_TABLE
from modules.care.schema.models import care_prescriptions
from modules.consent.facade import ConsentDecision
from modules.health.domain.exceptions import RecordAccessDeniedError
from modules.health.facade import HealthFacade, RecordEntryView, RecordTimeline
from modules.health.outbox import HEALTH_OUTBOX_TABLE
from modules.health.schema.models import health_record_access_history
from modules.intake.adapters.ai_provider_mock import MockAiProvider
from modules.intake.facade import IntakeFacade

NOW = datetime.now(UTC)


class _FakeResult:
    """Mimics result shapes the health facade uses, incl. ``.one()``."""

    def __init__(
        self,
        scalar: object | None = None,
        scalar_one: object | None = None,
        row: object | None = None,
        rows: list[object] | None = None,
        one: object | None = None,
    ) -> None:
        self._scalar = scalar_one if scalar_one is not None else scalar
        self._row = row
        self._rows = rows or []
        self._one = one

    def scalar_one(self) -> object:
        return self._scalar

    def first(self) -> object:
        return self._row

    def all(self) -> list:
        return self._rows

    def one(self) -> object:
        return self._one


def _connection(execute_results: list[object]) -> AsyncMock:
    connection = AsyncMock()
    connection.execute = AsyncMock(side_effect=execute_results)
    return connection


def _engine(connection: AsyncMock) -> AsyncMock:
    engine = AsyncMock(spec=AsyncEngine)
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=connection)
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    return engine


def _statements(connection: AsyncMock) -> list[ClauseElement]:
    return [
        call.args[0]
        for call in connection.execute.await_args_list
        if isinstance(call.args[0], ClauseElement)
    ]


def _stmt_params(statements: list[ClauseElement], table_name: str) -> dict[str, Any] | None:
    for stmt in statements:
        table = getattr(stmt, "table", None)
        if table is not None and table.name == table_name:
            return dict(stmt.compile().params)
    return None


def _entry_row(*, entry_id: int = 1, entry_type: str = "rx") -> object:
    return SimpleNamespace(
        id=entry_id,
        entry_type=entry_type,
        payload={"med": "paracetamol"},
        occurred_at=NOW,
        created_at=NOW,
    )


def _timeline(*, entry_ids: list[int] | None = None) -> RecordTimeline:
    entry_ids = entry_ids or [1]
    entries = [
        RecordEntryView(
            entry_id=eid,
            entry_type="rx",
            payload={"med": "paracetamol"},
            occurred_at=NOW,
            created_at=NOW,
        )
        for eid in entry_ids
    ]
    return RecordTimeline(record_id=7, patient_id=7, created_at=NOW, entries=entries)


class _FakeConsentFacade:
    """Records the consent seam calls the health facade makes (fail-closed gate)."""

    def __init__(self, decision: ConsentDecision) -> None:
        self._decision = decision
        self.check_calls: list[dict[str, Any]] = []
        self.egress_calls: list[dict[str, Any]] = []

    async def check_consent(
        self,
        patient_id: int,
        counterparty_type: str,
        counterparty_id: str,
        record_scope: str,
        settings: Any = None,
    ) -> ConsentDecision:
        self.check_calls.append(
            {
                "patient_id": patient_id,
                "counterparty_type": counterparty_type,
                "counterparty_id": counterparty_id,
                "record_scope": record_scope,
            }
        )
        return self._decision

    async def record_egress_disclosure(
        self,
        patient_id: int,
        consent_id: int | None,
        version: int,
        counterparty_type: str,
        counterparty_id: str,
        record_scope: str,
        disclosed_entry_ids: list[int],
    ) -> None:
        self.egress_calls.append(
            {
                "patient_id": patient_id,
                "consent_id": consent_id,
                "version": version,
                "counterparty_type": counterparty_type,
                "counterparty_id": counterparty_id,
                "record_scope": record_scope,
                "disclosed_entry_ids": disclosed_entry_ids,
            }
        )


def _health_facade(
    connection: AsyncMock,
    consent_facade: _FakeConsentFacade | None,
) -> HealthFacade:
    return HealthFacade(engine=_engine(connection), consent_facade=consent_facade)


def _record_shell_results() -> list[object]:
    """``_ensure_record_shell``: no-op conflict insert, then the record id."""
    return [_FakeResult(), _FakeResult(scalar_one=7)]


class TestConsentedHistoryRead:
    """The fail-closed history read itself (HealthFacade + ConsentFacade seam)."""

    @pytest.mark.asyncio
    async def test_allowed_read_calls_check_consent_and_records_egress(self) -> None:
        """Allowed: check_consent is called with the full drafting contract,
        the timeline is returned, and the egress row cites the disclosed ids."""
        connection = _connection(
            [
                *_record_shell_results(),
                _FakeResult(),
                _FakeResult(),
                _FakeResult(one=SimpleNamespace(created_at=NOW)),
                _FakeResult(rows=[_entry_row(entry_id=11), _entry_row(entry_id=12)]),
            ]
        )
        consent = _FakeConsentFacade(
            ConsentDecision(allowed=True, consent_id=42, version=3, effective_scope="full_record")
        )
        facade = _health_facade(connection, consent)

        timeline = await facade.read_consented_history(
            patient_id=7,
            scope=RX_DRAFT_HISTORY_SCOPE,
            counterparty_type="doctor",
            counterparty_id=42,
        )

        assert consent.check_calls == [
            {
                "patient_id": 7,
                "counterparty_type": "doctor",
                "counterparty_id": "42",
                "record_scope": RX_DRAFT_HISTORY_SCOPE,
            }
        ]
        assert [e.entry_id for e in timeline.entries] == [11, 12]
        # Access history was written with the allowed outcome.
        history_params = _stmt_params(_statements(connection), health_record_access_history.name)
        assert history_params is not None
        assert history_params["outcome"] == "allowed"
        assert history_params["scope"] == RX_DRAFT_HISTORY_SCOPE
        # The egress disclosure ran in the consent facade's own transaction.
        assert consent.egress_calls == [
            {
                "patient_id": 7,
                "consent_id": 42,
                "version": 3,
                "counterparty_type": "doctor",
                "counterparty_id": "42",
                "record_scope": RX_DRAFT_HISTORY_SCOPE,
                "disclosed_entry_ids": [11, 12],
            }
        ]

    @pytest.mark.asyncio
    async def test_denied_read_fails_closed_and_skips_egress(self) -> None:
        """Denied: the ledger + denied event are written, then the read raises
        RecordAccessDeniedError - no timeline escapes the gate."""
        connection = _connection(
            [
                *_record_shell_results(),
                _FakeResult(),
                _FakeResult(),
            ]
        )
        consent = _FakeConsentFacade(
            ConsentDecision(allowed=False, consent_id=None, version=None, effective_scope=None)
        )
        facade = _health_facade(connection, consent)

        with pytest.raises(RecordAccessDeniedError, match="consent check failed"):
            await facade.read_consented_history(
                patient_id=7,
                scope=RX_DRAFT_HISTORY_SCOPE,
                counterparty_type="doctor",
                counterparty_id=42,
            )

        assert consent.check_calls[0]["record_scope"] == RX_DRAFT_HISTORY_SCOPE
        assert consent.egress_calls == []
        history_params = _stmt_params(_statements(connection), health_record_access_history.name)
        assert history_params is not None
        assert history_params["outcome"] == "denied"
        assert history_params["denial_reason"] == "consent check failed"
        # The denied event also lands in the health outbox.
        assert _stmt_params(_statements(connection), HEALTH_OUTBOX_TABLE) is not None

    @pytest.mark.asyncio
    async def test_read_fails_closed_when_consent_facade_unconfigured(self) -> None:
        """No consent facade configured => hard RuntimeError, never a raw read."""
        facade = _health_facade(_connection([]), None)

        with pytest.raises(RuntimeError, match="ConsentFacade not configured"):
            await facade.read_consented_history(
                patient_id=7,
                scope=RX_DRAFT_HISTORY_SCOPE,
                counterparty_type="doctor",
                counterparty_id=42,
            )


# ---------------------------------------------------------------------------
# Care facade AI draft: consent denial propagates fail-closed (NFR-SEC-006)
# ---------------------------------------------------------------------------


def _case_row(
    *,
    case_id: int = 1,
    patient_id: int = 7,
    doctor_id: int | None = 42,
    pre_summary_id: int | None = 5,
    stage: str = "prescription_pending",
    forced_review: bool = False,
) -> object:
    return SimpleNamespace(
        id=case_id,
        patient_id=patient_id,
        doctor_id=doctor_id,
        pre_summary_id=pre_summary_id,
        stage=stage,
        forced_review=forced_review,
        closed_at=None,
        close_reason=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _care_facade(
    case_connection: AsyncMock,
    health_facade: HealthFacade,
) -> CareFacade:
    intake = IntakeFacade(engine=_engine(_connection([])), ai_gateway=MockAiProvider())
    return CareFacade(
        engine=_engine(case_connection),
        intake_facade=intake,
        health_facade=health_facade,
    )


class TestAiDraftFailClosed:
    """A denied consent read blocks the AI draft with no care-side writes."""

    @pytest.mark.asyncio
    async def test_ai_draft_propagates_denial_and_writes_nothing(self) -> None:
        care_conn = _connection([_FakeResult(row=_case_row()), _FakeResult(row=None)])
        health_conn = _connection(
            [
                *_record_shell_results(),
                _FakeResult(),
                _FakeResult(),
            ]
        )
        consent = _FakeConsentFacade(
            ConsentDecision(allowed=False, consent_id=None, version=None, effective_scope=None)
        )
        facade = _care_facade(care_conn, _health_facade(health_conn, consent))

        with pytest.raises(RecordAccessDeniedError, match="consent check failed"):
            await facade.create_rx_draft(case_id=1, doctor_id=42, source="ai_draft")

        # The drafting leg consulted the consent gate for the patient's
        # prescription history, was denied, and shut down.
        assert consent.check_calls[0]["record_scope"] == RX_DRAFT_HISTORY_SCOPE
        assert consent.check_calls[0]["patient_id"] == 7
        # No prescription row and no care outbox event on the care connection.
        assert _stmt_params(_statements(care_conn), care_prescriptions.name) is None
        assert _stmt_params(_statements(care_conn), CARE_OUTBOX_TABLE) is None
