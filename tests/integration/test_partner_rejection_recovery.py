"""PHASE-5 T09: rejected-partner recovery end-to-end against Postgres (#253).

Exercises the recovery surface against a live PostgreSQL, mirroring
``test_partner_verification_queue.py`` (facade + artifact store + bus):

- A rejected partner views the specific rejection reason recorded at reject.
- Re-submitting corrected credentials opens a NEW round (round > 1) and
  re-enters the operator queue with a fresh ``partner.verification_started``.
- The one-time appeal re-enters the queue and can only be used once (the second
  appeal is rejected with the appeal flag consumed).
- The re-submission throttle boundary is enforced (max 3 re-submission rounds
  then a cooldown).

Requires the native PostgreSQL; the suite skips cleanly when unreachable.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from conftest import seed_daltonganj_service_area
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from modules.iam.adapters.sms import MockSmsAdapter
from modules.iam.facade import IamFacade
from modules.partner.adapters.artifact_store import CredentialArtifactStore
from modules.partner.domain.credentials import CredentialType
from modules.partner.domain.exceptions import (
    AppealAlreadyUsedError,
    ReSubmissionThrottledError,
)
from modules.partner.facade import CredentialSubmission, PartnerFacade

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

_DOC_BYTES = b"medical registration certificate image"
_OPERATOR_ID = 77
_REJECT_REASON = "documents unreadable"


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture(scope="module")
def migration(database_url: str) -> Iterator[None]:
    config = _alembic_config(database_url)
    try:
        command.upgrade(config, "head")
    except Exception as exc:
        pytest.skip(f"PostgreSQL unreachable at {database_url} - {exc}")
    yield
    command.downgrade(config, "base")


@pytest_asyncio.fixture
async def clean_partner(database_url: str, migration: None) -> AsyncIterator[None]:
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "TRUNCATE TABLE partner.partner_verifications, "
                    "partner.partner_credentials, partner.partner_profiles, "
                    "partner.partner_outbox, partner.partner_service_areas, "
                    "iam.iam_role_grants, iam.iam_sessions, "
                    "iam.iam_otp_challenges, iam.iam_outbox, "
                    "iam.consumed_events, iam.iam_identities CASCADE"
                )
            )
            await seed_daltonganj_service_area(connection)
    finally:
        await engine.dispose()
    yield


async def _query(database_url: str, sql: str) -> list[dict[str, Any]]:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text(sql))
            return [dict(row) for row in result.mappings().all()]
    finally:
        await engine.dispose()


def _facade(database_url: str, tmp_path: Path) -> tuple[IamFacade, PartnerFacade]:
    engine = create_async_engine(database_url, poolclass=NullPool)
    iam = IamFacade(engine=engine, sms_adapter=MockSmsAdapter())
    store = CredentialArtifactStore(root=tmp_path, key_bytes=bytes(32))
    partner = PartnerFacade(engine=engine, iam_facade=iam, artifact_store=store)
    return iam, partner


async def _register_and_reject(partner: PartnerFacade, reason: str = _REJECT_REASON) -> int:
    """Register a doctor, pass Step-1, and reject with a reason (round 1 rejected)."""
    result = await partner.register(
        phone="9876543210",
        partner_type="doctor",
        practice_address="Station Road, Daltonganj",
        practice_latitude=24.04,
        practice_longitude=84.07,
    )
    assert result.status == "Registered"
    submission = await partner.submit_credentials(
        result.partner_id,
        credentials=[
            CredentialSubmission(
                credential_type=CredentialType.MEDICAL_REGISTRATION, artifacts=[_DOC_BYTES]
            )
        ],
    )
    assert submission.status == "Under Verification"
    assert submission.round == 1
    decision = await partner.operator_decision(
        result.partner_id, decision_by=_OPERATOR_ID, approve=False, reason=reason
    )
    assert decision.status == "Rejected"
    return result.partner_id


async def _resubmit(partner: PartnerFacade, partner_id: int) -> Any:
    return await partner.submit_credentials(
        partner_id,
        credentials=[
            CredentialSubmission(
                credential_type=CredentialType.MEDICAL_REGISTRATION, artifacts=[_DOC_BYTES]
            )
        ],
    )


@pytest.mark.asyncio
async def test_rejected_partner_views_specific_rejection_reason(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    """AC: a [Rejected] partner views the specific rejection reason."""
    _, partner = _facade(database_url, tmp_path)
    partner_id = await _register_and_reject(partner)

    view = await partner.get_rejection_reason(partner_id)

    assert view.partner_id == partner_id
    assert view.rejection_reason == _REJECT_REASON
    assert view.round == 1


@pytest.mark.asyncio
async def test_resubmission_opens_new_round_and_re_enters_queue(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    """AC: re-submitting corrected credentials starts a new round and re-enters the queue."""
    _, partner = _facade(database_url, tmp_path)
    partner_id = await _register_and_reject(partner)

    result = await _resubmit(partner, partner_id)

    assert result.status == "Under Verification"
    assert result.round == 2
    rounds = await _query(
        database_url,
        "SELECT round, status FROM partner.partner_verifications ORDER BY round",
    )
    assert rounds == [{"round": 1, "status": "rejected"}, {"round": 2, "status": "queued"}]
    outbox = await _query(database_url, "SELECT event_type FROM partner.partner_outbox")
    started = [row["event_type"] for row in outbox].count("partner.verification_started")
    assert started == 2  # round 1 and round 2
    queue = await partner.list_verification_queue()
    assert [item.partner_id for item in queue.items] == [partner_id]


@pytest.mark.asyncio
async def test_one_time_appeal_re_enters_queue_and_can_only_be_used_once(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    """AC: a one-time appeal re-enters the queue and can only be used once."""
    _, partner = _facade(database_url, tmp_path)
    partner_id = await _register_and_reject(partner)

    first = await partner.appeal(partner_id)
    assert first.status == "Under Verification"
    assert first.round == 2

    profile = await _query(database_url, "SELECT appeal_used FROM partner.partner_profiles")
    assert profile == [{"appeal_used": True}]
    # The appeal opened exactly one new round, but must NOT bump the re-submission
    # counter (it is a distinct recovery path, not a re-submission).
    profile_count = await _query(
        database_url, "SELECT re_submission_count FROM partner.partner_profiles"
    )
    assert profile_count == [{"re_submission_count": 0}]

    # While the appeal round is Under Verification the partner is no longer
    # Rejected, so a second appeal is refused on status.
    from modules.partner.domain.exceptions import PartnerNotRejectedError

    with pytest.raises(PartnerNotRejectedError):
        await partner.appeal(partner_id)

    # The appeal round is itself rejected, returning the partner to [Rejected].
    await partner.operator_decision(
        partner_id, decision_by=_OPERATOR_ID, approve=False, reason="appeal denied"
    )

    # Even though the partner is Rejected again, the consumed flag blocks the
    # one-time appeal from being used a second time.
    with pytest.raises(AppealAlreadyUsedError):
        await partner.appeal(partner_id)


@pytest.mark.asyncio
async def test_re_submission_throttle_boundary_is_enforced(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    """AC: the 3-re-submission throttle then cooldown is enforced."""
    _, partner = _facade(database_url, tmp_path)
    partner_id = await _register_and_reject(partner)

    # Reject after each re-submission so the partner is again Rejected and the
    # throttle budget advances. Rounds 2, 3, 4 are the three re-submissions.
    for expected_round in (2, 3, 4):
        result = await _resubmit(partner, partner_id)
        assert result.round == expected_round
        await partner.operator_decision(
            partner_id, decision_by=_OPERATOR_ID, approve=False, reason="still unreadable"
        )

    # Budget exhausted: the 4th re-submission is throttled.
    with pytest.raises(ReSubmissionThrottledError):
        await _resubmit(partner, partner_id)

    count = await _query(database_url, "SELECT re_submission_count FROM partner.partner_profiles")
    assert count == [{"re_submission_count": 3}]

    # The cooldown deadline is persisted so the throttle is durable - the
    # partner cannot beat the queue-protection rule by re-calling. Blocked_until
    # sits roughly RE_SUBMISSION_COOLDOWN in the future.
    cooldown = await _query(
        database_url,
        "SELECT re_submission_blocked_until IS NOT NULL AS blocked FROM partner.partner_profiles",
    )
    assert cooldown == [{"blocked": True}]
