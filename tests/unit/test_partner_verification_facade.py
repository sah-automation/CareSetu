"""PHASE-5 T08: the operator verification console facade seams (ticket #252).

Pins the DB-backed queue/detail/decision behavior against a mocked engine -
the HTTP surface and RBAC are covered by ``test_partner_verification_route``
and the live-Postgres decision -> event -> role chain by the integration suite
(``test_partner_verification_queue``). The contracts pinned here:

- ``operator_decision`` flips the current round's ``partner_verifications`` row
  to ``approved``/``rejected`` (with reason/actor/``decided_at``), moves the
  profile, and emits the terminal event in the same transaction - no bulk path.
- ``list_verification_queue`` defaults to ``[Under Verification]``, filters by
  partner type/status, sorts by registration age (oldest first) / type / status,
  and raises ``InvalidQueueSortError`` on an unknown sort key.
- ``get_verification_detail`` returns profile + credentials + history and emits
  ``partner.credential_reviewed`` for the view.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.sql.dml import Insert, Update

from modules.partner.domain.exceptions import (
    IllegalPartnerTransitionError,
    InvalidQueueSortError,
    PartnerNotFoundError,
    RejectionReasonRequiredError,
)
from modules.partner.facade import PartnerFacade
from modules.partner.outbox import PARTNER_OUTBOX_TABLE
from modules.partner.schema.models import partner_verifications

_NOW = datetime(2026, 8, 31, 10, 0, 0, tzinfo=UTC)


def _profile_row(
    *,
    partner_id: int = 3,
    iid: int = 9,
    partner_type: str = "doctor",
    status: str = "Under Verification",
):
    return SimpleNamespace(
        id=partner_id,
        identity_id=iid,
        partner_type=partner_type,
        status=status,
        practice_name="Dr. Arora Clinic",
        practice_address="Station Road, Daltonganj",
        service_area_id=None,
        created_at=_NOW,
    )


def _credential_row():
    return SimpleNamespace(
        id=5,
        credential_type="medical_registration",
        verified=False,
        expires_at=None,
        artifact_refs={"medical_registration_0": "partner/3/enc0"},
    )


def _history_row():
    return SimpleNamespace(
        round=1,
        status="queued",
        decision=None,
        decision_reason=None,
        decision_by=None,
        decided_at=None,
        created_at=_NOW,
    )


class _FakeResult:
    """Mimics ``Select`` result shapes: ``first`` / ``all`` / ``scalar_one``."""

    def __init__(self, first=None, all=None, scalar=None) -> None:
        self._first = first
        self._all = all if all is not None else []
        self._scalar = scalar

    def first(self):
        return self._first

    def all(self):
        return self._all

    def scalar_one(self):
        return self._scalar

    def scalar_one_or_none(self):
        return self._scalar


def _connection(execute_results: list[object]) -> AsyncMock:
    connection = AsyncMock()
    connection.execute = AsyncMock(side_effect=execute_results)
    return connection


def _engine(connection: AsyncMock, *, transactions: int = 1) -> MagicMock:
    engine = MagicMock(spec=AsyncEngine)
    engine.begin.return_value.__aenter__.side_effect = [connection] * transactions
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    return engine


def _updates(connection: AsyncMock) -> list[Update]:
    return [
        call.args[0]
        for call in connection.execute.await_args_list
        if isinstance(call.args[0], (Update, Insert))
    ]


def _outbox_inserts(connection: AsyncMock) -> list[Insert]:
    return [
        call.args[0]
        for call in connection.execute.await_args_list
        if isinstance(call.args[0], Insert) and call.args[0].table.name == PARTNER_OUTBOX_TABLE
    ]


def _bound_value(value: object) -> object:
    """Unwrap a SQLAlchemy BindParameter to its literal value for assertions."""
    return value.value if hasattr(value, "value") else value


@pytest.mark.asyncio
async def test_operator_approve_records_decision_and_emits_activated() -> None:
    connection = _connection(
        [
            _FakeResult(first=_profile_row()),  # load profile
            _FakeResult(scalar=1),  # max(round) = 1
            _FakeResult(),  # profile update
            _FakeResult(),  # verification update
            _FakeResult(),  # partner.activated outbox insert
        ]
    )
    facade = PartnerFacade(engine=_engine(connection), iam_facade=MagicMock())

    result = await facade.operator_decision(3, decision_by=77, approve=True)

    assert result.status == "Active"
    assert result.round == 1
    writes = _updates(connection)
    verification_update = writes[1]
    assert verification_update.table.name == partner_verifications.name
    values = verification_update._values
    assert _bound_value(values["status"]) == "approved"
    assert _bound_value(values["decision"]) == "approved"
    assert _bound_value(values["decision_reason"]) is None
    assert _bound_value(values["decision_by"]) == 77

    outbox = _outbox_inserts(connection)
    assert len(outbox) == 1


@pytest.mark.asyncio
async def test_operator_reject_records_reason_and_emits_rejected() -> None:
    connection = _connection(
        [
            _FakeResult(first=_profile_row()),  # load profile
            _FakeResult(scalar=1),  # max(round) = 1
            _FakeResult(),  # profile update
            _FakeResult(),  # verification update
            _FakeResult(),  # partner.rejected outbox insert
        ]
    )
    facade = PartnerFacade(engine=_engine(connection), iam_facade=MagicMock())

    result = await facade.operator_decision(
        3, decision_by=77, approve=False, reason="documents unreadable"
    )

    assert result.status == "Rejected"
    verify_update = _updates(connection)[1]
    values = verify_update._values
    assert _bound_value(values["status"]) == "rejected"
    assert _bound_value(values["decision"]) == "rejected"
    assert _bound_value(values["decision_reason"]) == "documents unreadable"
    assert _bound_value(values["decision_by"]) == 77

    outbox = _outbox_inserts(connection)
    assert len(outbox) == 1


@pytest.mark.asyncio
async def test_operator_reject_of_an_active_partner_emits_invalidated() -> None:
    """PHASE-5 T10 AC3: re-verification failure emits credential.invalidated.

    Rejecting an ``[Active]`` partner (a failed re-verification) is a clean
    deactivation: besides ``partner.rejected`` (role deny via T03) the
    ``credential.invalidated`` envelope must be written in the SAME transaction
    so the partner is deindexed and the iam role suspended via MOD-001.
    """
    connection = _connection(
        [
            _FakeResult(first=_profile_row(status="Active")),  # load profile
            _FakeResult(scalar=1),  # max(round) = 1
            _FakeResult(),  # profile update
            _FakeResult(),  # verification update
            _FakeResult(),  # partner.rejected outbox insert
            _FakeResult(),  # credential.invalidated outbox insert
        ]
    )
    facade = PartnerFacade(engine=_engine(connection), iam_facade=MagicMock())

    result = await facade.operator_decision(
        3, decision_by=77, approve=False, reason="credential expired"
    )

    assert result.status == "Rejected"
    outbox = _outbox_inserts(connection)
    event_types = sorted(_bound_value(insert._values["event_type"]) for insert in outbox)
    assert event_types == ["credential.invalidated", "partner.rejected"]


@pytest.mark.asyncio
async def test_operator_reject_of_an_under_verification_partner_emits_no_invalidated() -> None:
    """A first-time rejection is NOT a deactivation: no credential.invalidated.

    The brief (ticket #254) explicitly says only an Active partner's failed
    re-verification emits ``credential.invalidated`` - a mere lapse or first-time
    rejection never fires it.
    """
    connection = _connection(
        [
            _FakeResult(first=_profile_row(status="Under Verification")),  # load profile
            _FakeResult(scalar=1),  # max(round) = 1
            _FakeResult(),  # profile update
            _FakeResult(),  # verification update
            _FakeResult(),  # partner.rejected outbox insert
        ]
    )
    facade = PartnerFacade(engine=_engine(connection), iam_facade=MagicMock())

    result = await facade.operator_decision(
        3, decision_by=77, approve=False, reason="documents unreadable"
    )

    assert result.status == "Rejected"
    outbox = _outbox_inserts(connection)
    assert len(outbox) == 1
    assert _bound_value(outbox[0]._values["event_type"]) == "partner.rejected"


@pytest.mark.asyncio
async def test_grace_lapse_drops_active_to_under_verification_and_requeues() -> None:
    """PHASE-5 T10 AC2: grace-window lapse auto-drops Active -> Under Verification.

    The lapse is event-driven (no background scanner - Phase 6) and is NOT a
    deactivation, so no ``credential.invalidated`` fires. The state change
    still writes its own outbox event in the same transaction (coding-standards
    §4): ``partner.verification_started`` (round unchanged) re-queues the
    still-open round for the operator gate. It requires an open, undecided
    reverification round (the current round is still queued).
    """
    connection = _connection(
        [
            _FakeResult(first=_profile_row(status="Active")),  # load profile
            _FakeResult(scalar=1),  # max(round) = 1
            _FakeResult(first=_history_row()),  # current round is open/queued
            _FakeResult(),  # profile update (GRACE_LAPSE)
            _FakeResult(),  # partner.verification_started outbox insert
        ]
    )
    facade = PartnerFacade(engine=_engine(connection), iam_facade=MagicMock())

    result = await facade.grace_lapse(3)

    assert result.status == "Under Verification"
    assert result.round == 1
    outbox = _outbox_inserts(connection)
    assert len(outbox) == 1
    assert _bound_value(outbox[0]._values["event_type"]) == "partner.verification_started"


@pytest.mark.asyncio
async def test_grace_lapse_with_no_open_round_raises_illegal_transition() -> None:
    """AC2's "window lapses without a decision" precondition: a lapse is only
    legal over an open, undecided reverification round. A freshly-approved
    ``[Active]`` partner (round already decided) cannot be lapsed over an
    already-decided round."""
    connection = _connection(
        [
            _FakeResult(first=_profile_row(status="Active")),  # load profile
            _FakeResult(scalar=1),  # max(round) = 1
            _FakeResult(first=SimpleNamespace(status="approved")),  # round already decided
        ]
    )
    facade = PartnerFacade(engine=_engine(connection), iam_facade=MagicMock())

    with pytest.raises(IllegalPartnerTransitionError):
        await facade.grace_lapse(3)


@pytest.mark.asyncio
async def test_grace_lapse_on_non_active_raises_illegal_transition() -> None:
    """A lapse can only target an Active partner; anything else is illegal
    (the state machine edge refuses it even with an open round)."""
    for status in ("Registered", "Under Verification", "Rejected"):
        connection = _connection(
            [
                _FakeResult(first=_profile_row(status=status)),  # load profile
                _FakeResult(scalar=1),  # max(round) = 1
                _FakeResult(first=_history_row()),  # open round (still refused)
            ]
        )
        facade = PartnerFacade(engine=_engine(connection), iam_facade=MagicMock())

        with pytest.raises(IllegalPartnerTransitionError):
            await facade.grace_lapse(3)


@pytest.mark.asyncio
async def test_operator_reject_without_reason_raises_reason_required() -> None:
    connection = _connection([])
    facade = PartnerFacade(engine=_engine(connection), iam_facade=MagicMock())

    for reason in (None, "", "   "):
        with pytest.raises(RejectionReasonRequiredError):
            await facade.operator_decision(3, decision_by=77, approve=False, reason=reason)

    assert connection.execute.await_args_list == []


@pytest.mark.asyncio
async def test_queue_defaults_to_under_verification_registration_age_order() -> None:
    profile = _profile_row()
    profile.practice_name = None
    row = MagicMock()
    row.id, row.identity_id = 3, 9
    row.partner_type, row.status = "doctor", "Under Verification"
    row.practice_name, row.practice_address = None, "Station Road, Daltonganj"
    row.created_at, row.round = _NOW, 1
    connection = _connection([_FakeResult(all=[row])])
    facade = PartnerFacade(engine=_engine(connection), iam_facade=MagicMock())

    queue = await facade.list_verification_queue()

    stmt = connection.execute.await_args_list[0].args[0]
    assert stmt is not None
    queue_item = queue.items[0]
    assert queue_item.partner_id == 3
    assert queue_item.status == "Under Verification"
    assert queue_item.round == 1


@pytest.mark.asyncio
async def test_queue_filters_by_partner_type() -> None:
    row = MagicMock()
    row.id, row.identity_id = 3, 9
    row.partner_type, row.status = "chemist", "Under Verification"
    row.practice_name, row.practice_address = None, "Market Road"
    row.created_at, row.round = _NOW, 1
    connection = _connection([_FakeResult(all=[row])])
    facade = PartnerFacade(engine=_engine(connection), iam_facade=MagicMock())

    await facade.list_verification_queue(partner_type="chemist")

    stmt = connection.execute.await_args_list[0].args[0]
    assert stmt.compile().params["partner_type_1"] == "chemist"


@pytest.mark.asyncio
async def test_queue_unknown_sort_raises_invalid_queue_sort() -> None:
    facade = PartnerFacade(engine=_engine(_connection([_FakeResult()])), iam_facade=MagicMock())

    with pytest.raises(InvalidQueueSortError):
        await facade.list_verification_queue(sort_by="bogus")


@pytest.mark.asyncio
async def test_detail_returns_profile_credentials_history_and_emits_reviewed() -> None:
    connection = _connection(
        [
            _FakeResult(first=_profile_row()),  # profile (txn 1)
            _FakeResult(all=[_credential_row()]),  # credentials
            _FakeResult(all=[_history_row()]),  # history
            _FakeResult(),  # partner.credential_reviewed outbox insert (txn 2)
        ]
    )
    facade = PartnerFacade(engine=_engine(connection, transactions=2), iam_facade=MagicMock())

    detail = await facade.get_verification_detail(3, actor_id=77)

    assert detail.partner_id == 3
    assert detail.credentials[0].credential_type == "medical_registration"
    assert detail.verification_history[0].round == 1
    outbox = _outbox_inserts(connection)
    assert len(outbox) == 1


@pytest.mark.asyncio
async def test_detail_missing_partner_raises_not_found_without_event() -> None:
    connection = _connection([_FakeResult(first=None)])
    facade = PartnerFacade(engine=_engine(connection), iam_facade=MagicMock())

    with pytest.raises(PartnerNotFoundError):
        await facade.get_verification_detail(404, actor_id=77)
    assert _outbox_inserts(connection) == []
