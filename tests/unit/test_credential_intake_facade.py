"""WI-2 p2c (#338): CredentialIntakeFacade direct-seam unit suite.

Drives the credential-intake sub-facade (:mod:`modules.partner.credential_intake_facade`)
through a mocked engine, mirroring the iam MFA facade direct-seam suite - no
private facade helpers are imported and no exact SQL call order is scripted; the
tests pin the business contract of the two-step intake gate. The coordinator
delegation is covered by ``test_partner_facade_coordinator`` (thin mock) and the
DB-backed row behavior by the integration suites.

The contracts pinned here, unchanged from the pre-extraction coordinator:

- ``submit_credentials`` runs the Step-1 pre-filter: a format/duplicate auto-fail
  returns the partner straight to ``[Rejected]`` (never queued) with the specific
  reason and ``partner.rejected``; a pass encrypts the documents through the
  artifact store, opens the round, advances ``Under Verification``, and emits
  ``partner.verification_started``.
- A ``[Rejected]`` partner's re-submission is throttled when the budget is
  exhausted: the cooldown deadline is persisted (durable) and
  ``ReSubmissionThrottledError`` raised before any submission work; an accepted
  re-submission advances the budget.
- ``get_my_verification`` projects the partner's own review state: a
  ``[Registered]`` partner with no round answers round 0 / ``None`` fields, a
  decided round projects the decision.
- ``get_rejection_reason`` returns the latest rejected round's reason for a
  ``[Rejected]`` partner and raises ``PartnerNotRejectedError`` otherwise.
- ``appeal`` re-enters the operator queue (opens a round, emits
  ``partner.verification_started``) and consumes the one-time ``appeal_used``
  flag; a second appeal raises ``AppealAlreadyUsedError``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.sql.dml import Insert

from modules.partner import credential_validity as credential_validity_module
from modules.partner.adapters.artifact_store import CredentialArtifactStore
from modules.partner.credential_intake_facade import CredentialIntakeFacade
from modules.partner.credential_intake_models import CredentialSubmission
from modules.partner.domain.credentials import CredentialType
from modules.partner.domain.exceptions import (
    AppealAlreadyUsedError,
    PartnerNotFoundError,
    PartnerNotRejectedError,
    ReSubmissionThrottledError,
)
from modules.partner.domain.rejection import MAX_RE_SUBMISSIONS
from modules.partner.outbox import PARTNER_OUTBOX_TABLE

_NOW = datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)


def _profile_row(
    *,
    partner_id: int = 3,
    iid: int = 9,
    status: str = "Registered",
    appeal_used: bool = False,
    re_submission_count: int = 0,
    re_submission_blocked_until: datetime | None = None,
):
    return SimpleNamespace(
        id=partner_id,
        identity_id=iid,
        partner_type="doctor",
        status=status,
        appeal_used=appeal_used,
        re_submission_count=re_submission_count,
        re_submission_blocked_until=re_submission_blocked_until,
        created_at=_NOW,
    )


class _FakeResult:
    """Mimics ``Select`` result shapes: ``first`` / ``all`` / ``scalar``."""

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
    artifact_store: Any = None,
    re_submission_max: int = MAX_RE_SUBMISSIONS,
    clock: Any = lambda: _NOW,
) -> CredentialIntakeFacade:
    return CredentialIntakeFacade(
        engine=_engine(connection, transactions=transactions),
        credential_validity=credential_validity_module,
        artifact_store=artifact_store,
        re_submission_max=re_submission_max,
        clock=clock,
    )


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


def _credential(
    credential_type: CredentialType = CredentialType.MEDICAL_REGISTRATION,
    artifacts: tuple[bytes, ...] = (b"encoded-doc",),
) -> CredentialSubmission:
    return CredentialSubmission(credential_type=credential_type, artifacts=list(artifacts))


# -- submit_credentials: Step-1 pre-filter -------------------------------------


@pytest.mark.asyncio
async def test_submit_auto_rejects_invalid_format_never_queued() -> None:
    """A format auto-fail returns the partner straight to ``[Rejected]``.

    A doctor submitting a chemist's drug license trips the format gate: the
    partner is rejected with the specific pre-filter reason, never queued for
    the operator (ADR-0008).
    """
    connection = _connection(
        [
            _FakeResult(first=_profile_row()),  # throttle guard: load profile
            _FakeResult(scalar=0),  # max(round)
            _FakeResult(first=_profile_row()),  # submission: load profile
            _FakeResult(scalar=0),  # max(round)
            _FakeResult(all=[]),  # live credential types (current round)
            _FakeResult(),  # AUTO_FAIL profile update
            _FakeResult(),  # partner.rejected outbox insert
        ]
    )
    facade = _facade(connection, transactions=2)

    result = await facade.submit_credentials(
        3,
        credentials=[_credential(credential_type=CredentialType.DRUG_LICENSE)],
    )

    assert result.status == "Rejected"
    assert result.reason == "invalid_credential_type"
    assert _outbox_event_types(connection) == ["partner.rejected"]


@pytest.mark.asyncio
async def test_submit_auto_rejects_duplicate_type() -> None:
    """S13 (#266): a like credential type already live trips the duplicate gate.

    An ``Under Verification`` partner re-offering a credential type already live
    in the current round is auto-rejected as a duplicate (never double-queued).
    """
    connection = _connection(
        [
            _FakeResult(first=_profile_row(status="Under Verification")),  # throttle guard
            _FakeResult(scalar=1),  # max(round)
            _FakeResult(first=_profile_row(status="Under Verification")),  # submission
            _FakeResult(scalar=1),  # max(round)
            _FakeResult(all=[SimpleNamespace(credential_type="medical_registration")]),
            _FakeResult(),  # AUTO_FAIL profile update
            _FakeResult(),  # partner.rejected outbox insert
        ]
    )
    facade = _facade(connection, transactions=2)

    result = await facade.submit_credentials(
        3,
        credentials=[_credential()],
    )

    assert result.status == "Rejected"
    assert result.reason == "duplicate_credential"
    assert _outbox_event_types(connection) == ["partner.rejected"]


@pytest.mark.asyncio
async def test_submit_pass_encrypts_opens_round_and_emits_started() -> None:
    """A well-formed non-duplicate submission passes Step-1 and opens the round.

    On a pass the documents are encrypted through the artifact store (refs
    persisted, never the bytes), a ``partner_credentials`` row opens, the partner
    advances ``Under Verification``, and ``partner.verification_started`` fires -
    this is NOT approval, only the Step-2 queue entry (ADR-0008).
    """
    store = MagicMock(spec=CredentialArtifactStore)
    store.save_artifact.return_value = "partner/3/medical_registration_0.enc"
    connection = _connection(
        [
            _FakeResult(first=_profile_row()),  # throttle guard: load profile
            _FakeResult(scalar=0),  # max(round)
            _FakeResult(first=_profile_row()),  # submission: load profile
            _FakeResult(scalar=0),  # max(round)
            _FakeResult(all=[]),  # live credential types (none yet)
            _FakeResult(),  # partner_credentials insert
            _FakeResult(),  # START_VERIFICATION profile update
            _FakeResult(),  # queued verification row insert
            _FakeResult(),  # partner.verification_started outbox insert
        ]
    )
    facade = _facade(connection, transactions=2, artifact_store=store)

    result = await facade.submit_credentials(3, credentials=[_credential()])

    assert result.status == "Under Verification"
    assert result.round == 1
    assert store.save_artifact.called
    stored_refs = [
        u._values["artifact_refs"]
        for call in connection.execute.await_args_list
        if hasattr(call.args[0], "table") and call.args[0].table.name == "partner_credentials"
        for u in [call.args[0]]
    ]
    assert _bound_value(stored_refs[0]) == {
        "medical_registration_0": "partner/3/medical_registration_0.enc"
    }
    assert _outbox_event_types(connection) == ["partner.verification_started"]


@pytest.mark.asyncio
async def test_submit_pass_without_artifact_store_fails_loud() -> None:
    """A Step-1 pass must never queue the operator with nothing to review.

    With no artifact store wired, a passing submission fails loudly rather than
    silently dropping the documents (coding-standards §8) - no lifecycle write
    and no event happen.
    """
    connection = _connection(
        [
            _FakeResult(first=_profile_row()),  # throttle guard: load profile
            _FakeResult(scalar=0),  # max(round)
            _FakeResult(first=_profile_row()),  # submission: load profile
            _FakeResult(scalar=0),  # max(round)
            _FakeResult(all=[]),  # live credential types
        ]
    )
    facade = _facade(connection, transactions=2)

    with pytest.raises(RuntimeError, match="artifact store"):
        await facade.submit_credentials(3, credentials=[_credential()])
    assert _outbox_inserts(connection) == []
    assert not any(
        call.args[0].table.name == "partner_credentials"
        for call in connection.execute.await_args_list
        if hasattr(call.args[0], "table")
    )


# -- submit_credentials: re-submission throttle (PHASE-5 T09) ------------------


@pytest.mark.asyncio
async def test_submit_throttles_rejected_partner_at_budget_boundary() -> None:
    """A ``[Rejected]`` partner at the budget boundary is throttled up front.

    The cooldown deadline is persisted in its own committed transaction (durable
    - the partner cannot beat the queue-protection rule by re-calling) and
    ``ReSubmissionThrottledError`` is raised before any submission work.
    """
    connection = _connection(
        [
            _FakeResult(
                first=_profile_row(status="Rejected", re_submission_count=MAX_RE_SUBMISSIONS)
            ),
            _FakeResult(scalar=2),  # max(round) (inside load_profile)
            _FakeResult(),  # persist the cooldown deadline on the profile
        ]
    )
    facade = _facade(connection)

    with pytest.raises(ReSubmissionThrottledError):
        await facade.submit_credentials(3, credentials=[_credential()])

    updates = [
        call.args[0]
        for call in connection.execute.await_args_list
        if hasattr(call.args[0], "table") and call.args[0].table.name == "partner_profiles"
    ]
    cooldown_updates = [
        u
        for u in updates
        if "re_submission_blocked_until" in getattr(u, "_values", {})
        and _bound_value(u._values["re_submission_blocked_until"]) is not None
    ]
    assert len(cooldown_updates) == 1
    assert _outbox_inserts(connection) == []


@pytest.mark.asyncio
async def test_accepted_re_submission_advances_throttle_budget() -> None:
    """An accepted re-submission advances the rejected partner's budget.

    A ``[Rejected]`` partner's passing re-submission opens a fresh round and
    advances the counter - the budget only protects repeated failed attempts, so
    a business-round cleanup restarts the count after the cooldown lapses.
    """
    connection = _connection(
        [
            _FakeResult(first=_profile_row(status="Rejected", re_submission_count=2)),
            _FakeResult(scalar=1),  # max(round)
            _FakeResult(first=_profile_row(status="Rejected", re_submission_count=2)),
            _FakeResult(scalar=1),  # max(round)
            _FakeResult(all=[]),  # live credential types (Rejected bypasses anyway)
            _FakeResult(),  # partner_credentials insert
            _FakeResult(),  # START_VERIFICATION profile update
            _FakeResult(),  # queued verification row insert
            _FakeResult(),  # re_submission_count profile update
            _FakeResult(),  # partner.verification_started outbox insert
        ]
    )
    facade = _facade(
        connection, transactions=2, artifact_store=MagicMock(spec=CredentialArtifactStore)
    )

    result = await facade.submit_credentials(3, credentials=[_credential()])

    assert result.status == "Under Verification"
    assert result.round == 2
    budget_updates = [
        u
        for call in connection.execute.await_args_list
        if hasattr(call.args[0], "table") and call.args[0].table.name == "partner_profiles"
        for u in [call.args[0]]
        if "re_submission_count" in getattr(u, "_values", {})
    ]
    assert _bound_value(budget_updates[-1]._values["re_submission_count"]) == 3
    assert _outbox_event_types(connection) == ["partner.verification_started"]


# -- get_my_verification (US-7, P3 #271) ---------------------------------------


@pytest.mark.asyncio
async def test_get_my_verification_answers_no_submission_for_round_zero() -> None:
    connection = _connection(
        [
            _FakeResult(first=_profile_row(status="Registered")),  # by identity
            _FakeResult(scalar=0),  # max(round)
        ]
    )
    facade = _facade(connection)

    view = await facade.get_my_verification(7)

    assert view.partner_id == 3
    assert view.round == 0
    assert view.status is None
    assert view.decision is None
    assert view.decision_reason is None
    assert view.decided_at is None


@pytest.mark.asyncio
async def test_get_my_verification_projects_current_round_review_state() -> None:
    connection = _connection(
        [
            _FakeResult(first=_profile_row(status="Under Verification")),  # by identity
            _FakeResult(scalar=2),  # max(round)
            _FakeResult(
                first=SimpleNamespace(
                    status="queued",
                    decision="approved",
                    decision_reason="acceptable",
                    decided_at=_NOW,
                )
            ),
        ]
    )
    facade = _facade(connection)

    view = await facade.get_my_verification(7)

    assert view.round == 2
    assert view.status == "queued"
    assert view.decision == "approved"
    assert view.decision_reason == "acceptable"
    assert view.decided_at == _NOW


@pytest.mark.asyncio
async def test_get_my_verification_unknown_identity_raises() -> None:
    connection = _connection(
        [
            _FakeResult(first=None),  # no profile for this identity
        ]
    )
    facade = _facade(connection)

    with pytest.raises(PartnerNotFoundError):
        await facade.get_my_verification(7)


# -- get_rejection_reason (PHASE-5 T09) ----------------------------------------


@pytest.mark.asyncio
async def test_get_rejection_reason_returns_latest_rejected_round_reason() -> None:
    connection = _connection(
        [
            _FakeResult(first=_profile_row(status="Rejected")),  # load profile
            _FakeResult(scalar=2),  # max(round)
            _FakeResult(first=SimpleNamespace(round=2, decision_reason="documents unreadable")),
        ]
    )
    facade = _facade(connection)

    view = await facade.get_rejection_reason(3)

    assert view.partner_id == 3
    assert view.rejection_reason == "documents unreadable"
    assert view.round == 2


@pytest.mark.asyncio
async def test_get_rejection_reason_raises_for_non_rejected_partner() -> None:
    connection = _connection(
        [
            _FakeResult(first=_profile_row(status="Active")),  # load profile
            _FakeResult(scalar=2),  # max(round)
        ]
    )
    facade = _facade(connection)

    with pytest.raises(PartnerNotRejectedError):
        await facade.get_rejection_reason(3)


# -- appeal (PHASE-5 T09) ------------------------------------------------------


@pytest.mark.asyncio
async def test_appeal_re_enters_queue_and_emits_started() -> None:
    connection = _connection(
        [
            _FakeResult(first=_profile_row(status="Rejected")),  # load profile
            _FakeResult(scalar=2),  # max(round)
            _FakeResult(),  # START_VERIFICATION profile update
            _FakeResult(),  # queued verification row insert
            _FakeResult(),  # appeal_used profile update
            _FakeResult(),  # partner.verification_started outbox insert
        ]
    )
    facade = _facade(connection)

    result = await facade.appeal(3)

    assert result.status == "Under Verification"
    assert result.round == 3
    assert _outbox_event_types(connection) == ["partner.verification_started"]


@pytest.mark.asyncio
async def test_appeal_consumes_one_time_flag() -> None:
    connection = _connection(
        [
            _FakeResult(first=_profile_row(status="Rejected")),  # load profile
            _FakeResult(scalar=1),  # max(round)
            _FakeResult(),  # START_VERIFICATION profile update
            _FakeResult(),  # queued verification row insert
            _FakeResult(),  # appeal_used profile update
            _FakeResult(),  # outbox insert
        ]
    )
    facade = _facade(connection)

    await facade.appeal(3)

    appeal_updates = [
        u
        for call in connection.execute.await_args_list
        if hasattr(call.args[0], "table") and call.args[0].table.name == "partner_profiles"
        for u in [call.args[0]]
        if "appeal_used" in getattr(u, "_values", {})
        and _bound_value(u._values["appeal_used"]) is True
    ]
    assert len(appeal_updates) == 1


@pytest.mark.asyncio
async def test_appeal_raises_when_one_time_flag_consumed() -> None:
    connection = _connection(
        [
            _FakeResult(first=_profile_row(status="Rejected", appeal_used=True)),  # load profile
            _FakeResult(scalar=2),  # max(round)
        ]
    )
    facade = _facade(connection)

    with pytest.raises(AppealAlreadyUsedError):
        await facade.appeal(3)
    assert _outbox_inserts(connection) == []
