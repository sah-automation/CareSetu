"""WI-2 p2a (#334): OperatorGateFacade direct-seam unit suite.

Drives the operator-gate sub-facade (:mod:`modules.partner.operator_gate_facade`)
through a mocked engine, mirroring the iam MFA facade direct-seam suite - no
private facade helpers are imported and no exact SQL call order is scripted; the
tests pin the business contract of the gate. The coordinator delegation itself
is covered by ``test_partner_facade_coordinator`` (thin mock) and the DB-backed
row behavior by the integration suites (``test_partner_verification_queue``,
``test_partner_grace_window``).

The contracts pinned here, unchanged from the pre-extraction coordinator:

- ``operator_decision`` flips the current round's ``partner_verifications`` row
  to ``approved``/``rejected`` (with reason/actor/``decided_at``), moves the
  profile, and emits the terminal event in the same transaction - no bulk path.
- Rejecting an ``[Active]`` partner routes the close-out through the
  credential-validity deep module's SINGLE close-out transition
  (``close_out_credentials``) - the sub-facade never re-implements the
  deindex/``credential.invalidated``/cache-flush choreography (WI-1, #331).
- ``list_verification_queue`` defaults to ``[Under Verification]``, filters by
  partner type/status, sorts by registration age (oldest first), and raises on
  an unknown sort key / status (S15 - before any query).
- ``get_verification_detail`` returns profile + credentials + history and emits
  ``partner.credential_reviewed`` for the view.
- ``grace_lapse`` auto-drops an ``[Active]`` partner on an open, undecided
  re-verification round and never fires ``credential.invalidated``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.sql.dml import Insert, Update

from modules.partner import credential_validity as credential_validity_module
from modules.partner import directory_cache as directory_cache_module
from modules.partner.credential_validity import CloseOutCredential
from modules.partner.domain.exceptions import (
    IllegalPartnerTransitionError,
    InvalidQueueSortError,
    InvalidQueueStatusError,
    PartnerNotFoundError,
    RejectionReasonRequiredError,
)
from modules.partner.operator_gate_facade import OperatorGateFacade
from modules.partner.outbox import PARTNER_OUTBOX_TABLE
from modules.partner.schema.models import (
    partner_credentials,
    partner_verifications,
)

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


def _facade(
    connection: AsyncMock,
    *,
    transactions: int = 1,
    credential_validity: Any = credential_validity_module,
    directory_cache: Any = directory_cache_module,
    audit_facade: Any = None,
    credential_cleanup_days: int = 30,
    clock: Any = lambda: _NOW,
) -> OperatorGateFacade:
    return OperatorGateFacade(
        engine=_engine(connection, transactions=transactions),
        credential_validity=credential_validity,
        directory_cache=directory_cache,
        audit_facade=audit_facade,
        credential_cleanup_days=credential_cleanup_days,
        clock=clock,
    )


def _writes(connection: AsyncMock) -> list[Update]:
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


def _outbox_event_types(connection: AsyncMock) -> list[str]:
    return sorted(_bound_value(i._values["event_type"]) for i in _outbox_inserts(connection))


def _bound_value(value: object) -> object:
    """Unwrap a SQLAlchemy BindParameter to its literal value for assertions."""
    return value.value if hasattr(value, "value") else value


# ---------------------------------------------------------------------------
# operator_decision
# ---------------------------------------------------------------------------


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
    facade = _facade(connection)

    result = await facade.operator_decision(3, decision_by=77, approve=True)

    assert result.status == "Active"
    assert result.round == 1
    verify_update = _writes(connection)[1]
    assert verify_update.table.name == partner_verifications.name
    values = verify_update._values
    assert _bound_value(values["status"]) == "approved"
    assert _bound_value(values["decision"]) == "approved"
    assert _bound_value(values["decision_reason"]) is None
    assert _bound_value(values["decision_by"]) == 77
    assert _outbox_event_types(connection) == ["partner.activated"]


@pytest.mark.asyncio
async def test_operator_approve_flushes_the_directory_cache_seam() -> None:
    """PHASE-6 T02b (#314): approval changes directory visibility, so the sub-
    facade flushes through the injected directory-cache seam (never a local
    re-implementation of the flush)."""
    cache = MagicMock()
    cache.directory_visibility_changed = AsyncMock()
    connection = _connection(
        [
            _FakeResult(first=_profile_row()),
            _FakeResult(scalar=1),
            _FakeResult(),
            _FakeResult(),
            _FakeResult(),
        ]
    )
    facade = _facade(connection, directory_cache=cache)

    await facade.operator_decision(3, decision_by=77, approve=True)

    cache.directory_visibility_changed.assert_awaited_once()


@pytest.mark.asyncio
async def test_operator_reject_records_reason_and_emits_rejected() -> None:
    connection = _connection(
        [
            _FakeResult(first=_profile_row()),  # load profile
            _FakeResult(scalar=1),  # max(round) = 1
            _FakeResult(),  # profile update
            _FakeResult(),  # verification update
            _FakeResult(),  # partner.rejected outbox insert
            _FakeResult(all=[]),  # credential-cleanup select (none held)
        ]
    )
    facade = _facade(connection)

    result = await facade.operator_decision(
        3, decision_by=77, approve=False, reason="documents unreadable"
    )

    assert result.status == "Rejected"
    verify_update = _writes(connection)[1]
    values = verify_update._values
    assert _bound_value(values["status"]) == "rejected"
    assert _bound_value(values["decision_reason"]) == "documents unreadable"
    assert _bound_value(values["decision_by"]) == 77
    assert _outbox_event_types(connection) == ["partner.rejected"]


@pytest.mark.asyncio
async def test_operator_reject_without_reason_raises_before_any_query() -> None:
    connection = _connection([])
    facade = _facade(connection)

    for reason in (None, "", "   "):
        with pytest.raises(RejectionReasonRequiredError):
            await facade.operator_decision(3, decision_by=77, approve=False, reason=reason)

    assert connection.execute.await_args_list == []


@pytest.mark.asyncio
async def test_reject_of_an_active_partner_routes_through_credential_validity_seam() -> None:
    """WI-1 (#331) convergence: rejecting an ``[Active]`` partner routes the
    close-out through the deep module's single transition - the sub-facade does
    NOT re-implement the deindex/``credential.invalidated``/flush choreography.

    With the credential-validity seam mocked, the facade writes only the
    ``partner.rejected`` envelope and the credential cleanup schedule, then hands
    the close-out to ``close_out_credentials`` (never a local directory-index
    update or credential.invalidated write)."""
    seam = MagicMock()
    seam.close_out_credentials = AsyncMock(return_value=[5])
    connection = _connection(
        [
            _FakeResult(first=_profile_row(status="Active")),  # load profile
            _FakeResult(scalar=1),  # max(round) = 1
            _FakeResult(),  # profile update
            _FakeResult(),  # verification update
            _FakeResult(),  # partner.rejected outbox insert
            _FakeResult(all=[SimpleNamespace(id=5, artifact_refs={})]),  # credential select
            _FakeResult(),  # credential cleanup_due_at update
        ]
    )
    facade = _facade(connection, credential_validity=seam)

    result = await facade.operator_decision(
        3, decision_by=77, approve=False, reason="credential expired"
    )

    assert result.status == "Rejected"
    seam.close_out_credentials.assert_awaited_once()
    [cred] = seam.close_out_credentials.await_args.args[1]
    assert isinstance(cred, CloseOutCredential)
    assert cred.credential_id == 5
    assert cred.partner_id == 3
    assert cred.identity_id == 9
    # The facade never wrote credential.invalidated itself - only partner.rejected.
    assert _outbox_event_types(connection) == ["partner.rejected"]
    # No directory-index update was executed locally either.
    directory_updates = [
        w for w in _writes(connection) if w.table.name == "partner_directory_index"
    ]
    assert directory_updates == []


@pytest.mark.asyncio
async def test_reject_of_an_active_partner_close_out_uses_the_single_transition() -> None:
    """The full reject-of-active path (real seam): the close-out emits the
    ``credential.invalidated`` envelope carrying the round's real credential id
    in the same transaction - the convergence the seam owns."""
    connection = _connection(
        [
            _FakeResult(first=_profile_row(status="Active")),  # load profile
            _FakeResult(scalar=1),  # max(round) = 1
            _FakeResult(),  # profile update
            _FakeResult(),  # verification update
            _FakeResult(),  # partner.rejected outbox insert
            _FakeResult(all=[SimpleNamespace(id=5, artifact_refs={})]),  # credential select
            _FakeResult(),  # credential cleanup_due_at update
            _FakeResult(),  # directory index deindex (close-out transition)
            _FakeResult(),  # credential.invalidated outbox insert (close-out transition)
        ]
    )
    facade = _facade(connection)

    result = await facade.operator_decision(
        3, decision_by=77, approve=False, reason="credential expired"
    )

    assert result.status == "Rejected"
    assert _outbox_event_types(connection) == ["credential.invalidated", "partner.rejected"]
    invalidated = next(
        i
        for i in _outbox_inserts(connection)
        if _bound_value(i._values["event_type"]) == "credential.invalidated"
    )
    payload = _bound_value(invalidated._values["payload"])
    assert payload["credential_id"] == 5
    assert payload["reason"] == "credential expired"


@pytest.mark.asyncio
async def test_reject_of_an_under_verification_partner_emits_no_invalidated() -> None:
    """A first-time rejection is NOT a deactivation: no credential.invalidated,
    yet the 30-day cleanup window is still scheduled on the held rows (US-27)."""
    connection = _connection(
        [
            _FakeResult(first=_profile_row(status="Under Verification")),
            _FakeResult(scalar=1),
            _FakeResult(),
            _FakeResult(),
            _FakeResult(),
            _FakeResult(all=[SimpleNamespace(id=5, artifact_refs={})]),
            _FakeResult(),
        ]
    )
    facade = _facade(connection)

    result = await facade.operator_decision(
        3, decision_by=77, approve=False, reason="documents unreadable"
    )

    assert result.status == "Rejected"
    assert _outbox_event_types(connection) == ["partner.rejected"]


@pytest.mark.asyncio
async def test_operator_reject_schedules_cleanup_window_with_clock() -> None:
    connection = _connection(
        [
            _FakeResult(first=_profile_row(status="Active")),
            _FakeResult(scalar=1),
            _FakeResult(),
            _FakeResult(),
            _FakeResult(),
            _FakeResult(all=[SimpleNamespace(id=5, artifact_refs={})]),
            _FakeResult(),
            _FakeResult(),
            _FakeResult(),
        ]
    )
    facade = _facade(connection, credential_cleanup_days=30)

    await facade.operator_decision(3, decision_by=77, approve=False, reason="rejected")

    credential_updates = [
        u
        for u in _writes(connection)
        if isinstance(u, Update) and u.table.name == partner_credentials.name
    ]
    assert len(credential_updates) == 1
    assert _bound_value(credential_updates[0]._values["cleanup_due_at"]) == _NOW + timedelta(
        days=30
    )


# ---------------------------------------------------------------------------
# grace_lapse
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grace_lapse_drops_active_to_under_verification_and_requeues() -> None:
    connection = _connection(
        [
            _FakeResult(first=_profile_row(status="Active")),
            _FakeResult(scalar=1),
            _FakeResult(first=_history_row()),  # current round is open/queued
            _FakeResult(),
            _FakeResult(),
        ]
    )
    facade = _facade(connection)

    result = await facade.grace_lapse(3)

    assert result.status == "Under Verification"
    assert result.round == 1
    # The mere lapse is NOT a deactivation - only verification_started requeues.
    assert _outbox_event_types(connection) == ["partner.verification_started"]


@pytest.mark.asyncio
async def test_grace_lapse_with_no_open_round_raises_illegal_transition() -> None:
    connection = _connection(
        [
            _FakeResult(first=_profile_row(status="Active")),
            _FakeResult(scalar=1),
            _FakeResult(first=SimpleNamespace(status="approved")),
        ]
    )
    facade = _facade(connection)

    with pytest.raises(IllegalPartnerTransitionError):
        await facade.grace_lapse(3)


@pytest.mark.asyncio
async def test_grace_lapse_on_non_active_raises_illegal_transition() -> None:
    for status in ("Registered", "Under Verification", "Rejected"):
        connection = _connection(
            [
                _FakeResult(first=_profile_row(status=status)),
                _FakeResult(scalar=1),
                _FakeResult(first=_history_row()),
            ]
        )
        facade = _facade(connection)

        with pytest.raises(IllegalPartnerTransitionError):
            await facade.grace_lapse(3)


# ---------------------------------------------------------------------------
# list_verification_queue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_queue_defaults_to_under_verification_registration_age_order() -> None:
    row = MagicMock()
    row.id, row.identity_id = 3, 9
    row.partner_type, row.status = "doctor", "Under Verification"
    row.practice_name, row.practice_address = "Dr. Arora Clinic", "Station Road, Daltonganj"
    row.created_at, row.round = _NOW, 1
    connection = _connection([_FakeResult(all=[row])])
    facade = _facade(connection)

    queue = await facade.list_verification_queue()

    item = queue.items[0]
    assert item.partner_id == 3
    assert item.status == "Under Verification"
    assert item.round == 1
    assert item.audit_link is None
    assert item.practice_name == "Dr. Arora Clinic"


@pytest.mark.asyncio
async def test_queue_populates_audit_link_via_the_audit_seam() -> None:
    row = MagicMock()
    row.id, row.identity_id = 3, 9
    row.partner_type, row.status = "doctor", "Under Verification"
    row.practice_name, row.practice_address = None, "Station Road"
    row.created_at, row.round = _NOW, 1

    class StubAuditFacade:
        def __init__(self) -> None:
            self.requested: list[int] = []

        def get_partner_audit_links(self, partner_ids: list[int]) -> dict[int, str]:
            self.requested = list(partner_ids)
            return {pid: f"audit-link-{pid}" for pid in partner_ids}

    audit = StubAuditFacade()
    connection = _connection([_FakeResult(all=[row])])
    facade = _facade(connection, audit_facade=audit)

    queue = await facade.list_verification_queue()

    assert audit.requested == [3]
    assert queue.items[0].audit_link == "audit-link-3"


@pytest.mark.asyncio
async def test_queue_filters_by_partner_type() -> None:
    row = MagicMock()
    row.id, row.identity_id = 3, 9
    row.partner_type, row.status = "chemist", "Under Verification"
    row.practice_name, row.practice_address = None, "Market Road"
    row.created_at, row.round = _NOW, 1
    connection = _connection([_FakeResult(all=[row])])
    facade = _facade(connection)

    queue = await facade.list_verification_queue(partner_type="chemist")

    assert queue.items[0].partner_type == "chemist"


@pytest.mark.asyncio
async def test_queue_unknown_sort_raises_invalid_queue_sort() -> None:
    facade = _facade(_connection([_FakeResult()]))

    with pytest.raises(InvalidQueueSortError):
        await facade.list_verification_queue(sort_by="bogus")


@pytest.mark.asyncio
async def test_queue_unknown_status_raises_before_any_query() -> None:
    """S15 (#268): an unknown status is an explicit error, never a silent empty
    queue - validation fires before the query runs."""
    connection = _connection([_FakeResult()])
    facade = _facade(connection)

    with pytest.raises(InvalidQueueStatusError):
        await facade.list_verification_queue(status="Nonsense")
    assert connection.execute.await_count == 0


@pytest.mark.asyncio
async def test_queue_filters_by_valid_status() -> None:
    row = MagicMock()
    row.id, row.identity_id = 3, 9
    row.partner_type, row.status = "doctor", "Rejected"
    row.practice_name, row.practice_address = None, "Station Road"
    row.created_at, row.round = _NOW, 1
    connection = _connection([_FakeResult(all=[row])])
    facade = _facade(connection)

    queue = await facade.list_verification_queue(status="Rejected")

    assert queue.items[0].status == "Rejected"


# ---------------------------------------------------------------------------
# get_verification_detail
# ---------------------------------------------------------------------------


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
    facade = _facade(connection, transactions=2)

    detail = await facade.get_verification_detail(3, actor_id=77)

    assert detail.partner_id == 3
    assert detail.practice_name == "Dr. Arora Clinic"
    assert detail.credentials[0].credential_type == "medical_registration"
    assert detail.verification_history[0].round == 1
    assert _outbox_event_types(connection) == ["partner.credential_reviewed"]


@pytest.mark.asyncio
async def test_detail_missing_partner_raises_not_found_without_event() -> None:
    connection = _connection([_FakeResult(first=None)])
    facade = _facade(connection)

    with pytest.raises(PartnerNotFoundError):
        await facade.get_verification_detail(404, actor_id=77)
    assert _outbox_inserts(connection) == []


@pytest.mark.asyncio
async def test_detail_includes_partner_audit_chain_when_audit_facade_present() -> None:
    from uuid import uuid4

    from modules.audit.facade import AuditEventView, AuditPage

    event = AuditEventView(
        id=uuid4(),
        event_type="partner.registered",
        actor_id=None,
        target_id=uuid4(),
        scope="partner_registration",
        metadata={"partner_type": "doctor"},
        timestamp=_NOW,
        prev_hash="0" * 64,
        hash="1" * 64,
    )

    class StubAuditFacade:
        def __init__(self) -> None:
            self.partner_id: int | None = None

        async def query_partner_audit(self, partner_id: int, *, page_size: int = 50) -> AuditPage:
            self.partner_id = partner_id
            return AuditPage(events=[event], total_count=1)

        def get_partner_audit_link(self, partner_id: int) -> str:
            return f"audit-link-{partner_id}"

    audit = StubAuditFacade()
    connection = _connection(
        [
            _FakeResult(first=_profile_row()),  # profile (txn 1)
            _FakeResult(all=[_credential_row()]),  # credentials
            _FakeResult(all=[_history_row()]),  # history
            _FakeResult(),  # partner.credential_reviewed outbox insert (txn 2)
        ]
    )
    facade = _facade(connection, transactions=2, audit_facade=audit)

    detail = await facade.get_verification_detail(3, actor_id=77)

    assert audit.partner_id == 3
    assert len(detail.audit_events) == 1
    assert detail.audit_events[0].event_type == "partner.registered"
    assert detail.audit_events[0].hash == event.hash
    assert detail.audit_link == "audit-link-3"


@pytest.mark.asyncio
async def test_detail_without_audit_facade_surfaces_no_audit_chain() -> None:
    connection = _connection(
        [
            _FakeResult(first=_profile_row()),
            _FakeResult(all=[_credential_row()]),
            _FakeResult(all=[_history_row()]),
            _FakeResult(),
        ]
    )
    facade = _facade(connection, transactions=2)

    detail = await facade.get_verification_detail(3, actor_id=77)

    assert detail.audit_events == []
    assert detail.audit_link is None
