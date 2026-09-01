"""PHASE-5 T09: rejected-partner recovery facade seams (#253).

Pins the DB-backed recovery operations against a mocked engine - view rejection
reason, one-time appeal, and the re-submission throttle guard on
``submit_credentials`` (the HTTP surface is covered by
``test_partner_rejection_recovery_route``; live-Postgres round-trips by the
integration suite). Contracts pinned here:

- ``get_rejection_reason`` returns the latest rejected round's reason for a
  ``[Rejected]`` partner, and raises ``PartnerNotRejectedError`` for any other
  status or when no rejected reason is on record.
- ``appeal`` re-enters the operator queue (opens a round, emits
  ``partner.verification_started``) and consumes the one-time ``appeal_used``
  flag; a second appeal raises ``AppealAlreadyUsedError``, and a non-rejected
  appeal raises ``PartnerNotRejectedError``.
- ``submit_credentials`` raises ``ReSubmissionThrottledError`` before any
  submission work when a ``[Rejected]`` partner has exhausted the re-submission
  budget (the domain policy decides; this pins the facade guard).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.sql.dml import Insert

from modules.partner.domain.rejection import MAX_RE_SUBMISSIONS
from modules.partner.facade import PartnerFacade
from modules.partner.outbox import PARTNER_OUTBOX_TABLE

_NOW = datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)

_OPERATOR_REASON = "documents unreadable"


def _profile_row(
    *,
    partner_id: int = 3,
    iid: int = 9,
    status: str = "Rejected",
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
    )


class _FakeResult:
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


def _engine(connection: AsyncMock) -> MagicMock:
    engine = MagicMock(spec=AsyncEngine)
    engine.begin.return_value.__aenter__.side_effect = [connection]
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    return engine


def _outbox_inserts(connection: AsyncMock) -> list[Insert]:
    return [
        call.args[0]
        for call in connection.execute.await_args_list
        if isinstance(call.args[0], Insert) and call.args[0].table.name == PARTNER_OUTBOX_TABLE
    ]


def _bound_value(value: object) -> object:
    """Unwrap a SQLAlchemy BindParameter to its literal value for assertions."""
    return value.value if hasattr(value, "value") else value


def _facade(connection: AsyncMock) -> PartnerFacade:
    return PartnerFacade(engine=_engine(connection), iam_facade=MagicMock())


def _rejected_reason_row(round_value: int = 2, reason: str = _OPERATOR_REASON):
    return SimpleNamespace(round=round_value, decision_reason=reason)


# -- get_rejection_reason -----------------------------------------------------


@pytest.mark.asyncio
async def test_get_rejection_reason_returns_latest_rejected_round_reason() -> None:
    connection = _connection(
        [
            _FakeResult(first=_profile_row()),  # load profile (Rejected)
            _FakeResult(scalar=2),  # max(round) = 2
            _FakeResult(first=_rejected_reason_row()),  # latest rejected reason
        ]
    )
    facade = _facade(connection)

    view = await facade.get_rejection_reason(3)

    assert view.partner_id == 3
    assert view.rejection_reason == _OPERATOR_REASON
    assert view.round == 2


@pytest.mark.asyncio
async def test_get_rejection_reason_raises_when_not_rejected() -> None:
    from modules.partner.domain.exceptions import PartnerNotRejectedError

    connection = _connection(
        [
            _FakeResult(first=_profile_row(status="Active")),
            _FakeResult(scalar=2),
        ]
    )
    facade = _facade(connection)

    with pytest.raises(PartnerNotRejectedError):
        await facade.get_rejection_reason(3)


@pytest.mark.asyncio
async def test_get_rejection_reason_raises_when_no_reason_on_record() -> None:
    from modules.partner.domain.exceptions import PartnerNotRejectedError

    connection = _connection(
        [
            _FakeResult(first=_profile_row()),  # load profile (Rejected)
            _FakeResult(scalar=2),  # max(round)
            _FakeResult(first=SimpleNamespace(round=2, decision_reason=None)),
        ]
    )
    facade = _facade(connection)

    with pytest.raises(PartnerNotRejectedError):
        await facade.get_rejection_reason(3)


# -- appeal -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_appeal_re_enters_queue_consumes_flag_and_emits_started() -> None:
    connection = _connection(
        [
            _FakeResult(first=_profile_row(re_submission_count=2)),  # load profile
            _FakeResult(scalar=2),  # max(round) = 2
            _FakeResult(),  # _apply_transition profile update
            _FakeResult(),  # verification insert (new round 3)
            _FakeResult(),  # appeal_used profile update
            _FakeResult(),  # partner.verification_started outbox insert
        ]
    )
    facade = _facade(connection)

    result = await facade.appeal(3)

    assert result.status == "Under Verification"
    assert result.round == 3
    outbox = _outbox_inserts(connection)
    assert len(outbox) == 1


@pytest.mark.asyncio
async def test_appeal_consumes_appeal_used_on_profile() -> None:
    connection = _connection(
        [
            _FakeResult(first=_profile_row()),  # load profile
            _FakeResult(scalar=1),  # max(round)
            _FakeResult(),  # _apply_transition profile update
            _FakeResult(),  # verification insert
            _FakeResult(),  # appeal_used profile update
            _FakeResult(),  # outbox insert
        ]
    )
    facade = _facade(connection)

    await facade.appeal(3)

    updates = [
        call.args[0]
        for call in connection.execute.await_args_list
        if hasattr(call.args[0], "table") and call.args[0].table.name == "partner_profiles"
    ]
    appeal_updates = [
        u
        for u in updates
        if "appeal_used" in getattr(u, "_values", {})
        and _bound_value(u._values["appeal_used"]) is True
    ]
    assert len(appeal_updates) == 1


@pytest.mark.asyncio
async def test_appeal_rejected_when_flag_already_consumed() -> None:
    from modules.partner.domain.exceptions import AppealAlreadyUsedError

    connection = _connection(
        [
            _FakeResult(first=_profile_row(appeal_used=True)),  # load profile
            _FakeResult(scalar=2),
        ]
    )
    facade = _facade(connection)

    with pytest.raises(AppealAlreadyUsedError):
        await facade.appeal(3)
    assert _outbox_inserts(connection) == []


@pytest.mark.asyncio
async def test_appeal_raises_when_partner_not_rejected() -> None:
    from modules.partner.domain.exceptions import PartnerNotRejectedError

    connection = _connection(
        [
            _FakeResult(first=_profile_row(status="Active")),
            _FakeResult(scalar=2),
        ]
    )
    facade = _facade(connection)

    with pytest.raises(PartnerNotRejectedError):
        await facade.appeal(3)


# -- re-submission throttle ---------------------------------------------------


@pytest.mark.asyncio
async def test_submit_credentials_throttles_when_budget_exhausted() -> None:
    from modules.partner.domain.exceptions import ReSubmissionThrottledError

    connection = _connection(
        [
            # A rejected partner already at the max re-submission budget with no
            # in-flight cooldown: the guard must fire the throttle immediately.
            _FakeResult(first=_profile_row(re_submission_count=MAX_RE_SUBMISSIONS)),
            _FakeResult(scalar=2),  # max(round) = 2 (inside _load_profile)
            _FakeResult(),  # persist the cooldown deadline on the profile
        ]
    )
    facade = _facade(connection)

    with pytest.raises(ReSubmissionThrottledError):
        await facade.submit_credentials(
            3,
            credentials=[],
        )


@pytest.mark.asyncio
async def test_submit_credentials_persists_cooldown_deadline_when_throttled() -> None:
    """The cooldown deadline is written to the profile so the throttle is durable.

    The persist happens in its own committed transaction (returned, not raised)
    so it is NOT rolled back with the throttled error - the partner cannot beat
    the queue-protection rule by re-calling within the cooldown.
    """
    connection = _connection(
        [
            _FakeResult(first=_profile_row(re_submission_count=MAX_RE_SUBMISSIONS)),
            _FakeResult(scalar=2),  # max(round) = 2 (inside _load_profile)
            _FakeResult(),  # persist the cooldown deadline on the profile
        ]
    )
    facade = _facade(connection)

    from modules.partner.domain.exceptions import ReSubmissionThrottledError

    with pytest.raises(ReSubmissionThrottledError):
        await facade.submit_credentials(3, credentials=[])

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


@pytest.mark.asyncio
async def test_submit_credentials_throttles_while_cooldown_in_flight() -> None:
    from modules.partner.domain.exceptions import ReSubmissionThrottledError

    future = _NOW + timedelta(days=5)
    connection = _connection(
        [
            _FakeResult(
                first=_profile_row(re_submission_count=0, re_submission_blocked_until=future)
            ),
            _FakeResult(scalar=2),  # max(round) = 2 (inside _load_profile)
            _FakeResult(),  # persist the cooldown deadline on the profile
        ]
    )
    facade = _facade(connection)

    with pytest.raises(ReSubmissionThrottledError):
        await facade.submit_credentials(
            3,
            credentials=[],
        )
