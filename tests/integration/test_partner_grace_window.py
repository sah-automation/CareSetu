"""PHASE-5 T10: grace-window re-verification + deactivation against Postgres (#254).

Exercises the active-partner grace-window lifecycle end-to-end:

- Approval turns the partner ``[Active]``; re-submission stays ``[Active]``
  through the 7-day grace window (round incremented).
- Grace-window lapse auto-drops ``[Active]`` to ``[Under Verification]``
  (no ``credential.invalidated``, no background scanner - event-driven only).
- Reverification failure (operator reject on ``[Active]``) produces
  ``[Rejected]`` with ``credential.invalidated`` which drives the T03 chain
  to suspend the IAM role.

The credential.invalidated -> iam role suspension chain is observable through
the iam facade (``partner_role_status``), matching the T03 integration test
pattern. ``submit_credentials`` on an ``[Active]`` partner is already wired
(T04) to stay ``[Active]`` through the grace window; this test suite verifies
the end-to-end lifecycle including the iam role chain.

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
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from bus.dispatch import dispatch
from bus.registry import HandlerRegistry
from modules.iam.adapters import register_handlers as register_iam_handlers
from modules.iam.adapters.sms import MockSmsAdapter
from modules.iam.facade import IamFacade
from modules.partner.adapters.artifact_store import CredentialArtifactStore
from modules.partner.domain.credentials import CredentialType
from modules.partner.domain.events import (
    credential_invalidated_envelope,
    partner_activated_envelope,
    partner_rejected_envelope,
)
from modules.partner.domain.exceptions import IllegalPartnerTransitionError
from modules.partner.facade import CredentialSubmission, PartnerFacade

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

_DOC_BYTES = b"medical registration certificate image"
_DOC_BYTES_2 = b"updated medical registration certificate"

_OPERATOR_ID = 77


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture(scope="module")
def migration(database_url: str) -> Iterator[None]:
    """Migrate all schemas to head for the module, restore base after."""
    config = _alembic_config(database_url)
    try:
        command.upgrade(config, "head")
    except Exception as exc:
        pytest.skip(f"PostgreSQL unreachable at {database_url} - {exc}")
    yield
    command.downgrade(config, "base")


@pytest_asyncio.fixture
async def clean_partner(database_url: str, migration: None) -> AsyncIterator[None]:
    """Empty the iam + partner tables before every test for a clean slate."""
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


def _registry() -> HandlerRegistry:
    registry = HandlerRegistry()
    register_iam_handlers(registry)
    return registry


async def _dispatch_to_iam(registry: HandlerRegistry, envelope: Any) -> None:
    """Run the iam consumer for one terminal partner event (the T03 chain)."""
    await dispatch(registry, envelope)


async def _register_approve_activate(partner: PartnerFacade) -> tuple[int, int]:
    """Register a doctor, submit credentials, operator approve -> Active.

    Returns ``(partner_id, identity_id)``.
    """
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
    # Operator approval -> Active
    decision = await partner.operator_decision(
        result.partner_id, decision_by=_OPERATOR_ID, approve=True
    )
    assert decision.status == "Active"
    return result.partner_id, result.identity_id


@pytest.mark.asyncio
async def test_reverification_submit_stays_active_within_grace_window(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    """AC1: an active partner re-submitting stays [Active] within the 7-day
    grace window; the round increments for the re-verification trail."""
    iam, partner = _facade(database_url, tmp_path)
    partner_id, identity_id = await _register_approve_activate(partner)

    # Activate the role via the event chain.
    registry = _registry()
    await _dispatch_to_iam(
        registry,
        partner_activated_envelope(partner_id, identity_id, _OPERATOR_ID),
    )
    assert await iam.partner_role_status(identity_id) == "Active"

    # Active partner re-submits updated credentials: stays Active, round 2.
    submission = await partner.submit_credentials(
        partner_id,
        credentials=[
            CredentialSubmission(
                credential_type=CredentialType.MEDICAL_REGISTRATION, artifacts=[_DOC_BYTES_2]
            )
        ],
    )
    assert submission.status == "Active"
    assert submission.round == 2

    # Profile still Active; a new verification round is queued (round 2).
    profile = await _query(database_url, "SELECT status FROM partner.partner_profiles")
    assert profile == [{"status": "Active"}]
    rounds = await _query(
        database_url,
        "SELECT round, status FROM partner.partner_verifications ORDER BY round",
    )
    assert len(rounds) == 2
    assert rounds[0]["round"] == 1 and rounds[0]["status"] == "approved"
    assert rounds[1]["round"] == 2 and rounds[1]["status"] == "queued"

    # The role stays Active - the grace window keeps practicing.
    assert await iam.partner_role_status(identity_id) == "Active"

    # Only verification_started events, no deactivated / invalidated.
    outbox = await _query(database_url, "SELECT event_type FROM partner.partner_outbox")
    event_types = [row["event_type"] for row in outbox]
    assert "credential.invalidated" not in event_types
    assert event_types.count("partner.verification_started") == 2


@pytest.mark.asyncio
async def test_reverification_reject_deactivates_and_revokes_role(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    """AC3+AC4: reverification failure -> Rejected + credential.invalidated
    -> iam role suspended (the T03 chain observable through the iam facade)."""
    iam, partner = _facade(database_url, tmp_path)
    partner_id, identity_id = await _register_approve_activate(partner)

    registry = _registry()
    await _dispatch_to_iam(
        registry,
        partner_activated_envelope(partner_id, identity_id, _OPERATOR_ID),
    )
    assert await iam.partner_role_status(identity_id) == "Active"

    # Re-submit -> stays Active (round 2 queued).
    submission = await partner.submit_credentials(
        partner_id,
        credentials=[
            CredentialSubmission(
                credential_type=CredentialType.MEDICAL_REGISTRATION, artifacts=[_DOC_BYTES_2]
            )
        ],
    )
    assert submission.status == "Active"
    assert submission.round == 2

    # Operator rejects the re-verification: Rejected + credential.invalidated
    # fires - this is the deactivation path.
    decision = await partner.operator_decision(
        partner_id,
        decision_by=_OPERATOR_ID,
        approve=False,
        reason="credential expired",
    )
    assert decision.status == "Rejected"

    # credential.invalidated emitted alongside partner.rejected.
    outbox = await _query(database_url, "SELECT event_type FROM partner.partner_outbox")
    event_types = [row["event_type"] for row in outbox]
    assert "credential.invalidated" in event_types
    assert "partner.rejected" in event_types

    # The T03 chain: credential.invalidated suspends the iam role.
    await _dispatch_to_iam(
        registry,
        credential_invalidated_envelope(
            partner_id,
            identity_id=identity_id,
            reason="reverification_failed",
        ),
    )
    assert await iam.partner_role_status(identity_id) == "Suspended"


@pytest.mark.asyncio
async def test_grace_lapse_drops_active_to_under_verification(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    """AC2: grace-window lapse auto-drops Active -> Under Verification without
    deactivating (no credential.invalidated)."""
    iam, partner = _facade(database_url, tmp_path)
    partner_id, identity_id = await _register_approve_activate(partner)

    # Activate via the iam event chain.
    registry = _registry()
    await _dispatch_to_iam(
        registry,
        partner_activated_envelope(partner_id, identity_id, _OPERATOR_ID),
    )
    assert await iam.partner_role_status(identity_id) == "Active"

    # Re-submit -> stays Active (round 2 queued).
    submission = await partner.submit_credentials(
        partner_id,
        credentials=[
            CredentialSubmission(
                credential_type=CredentialType.MEDICAL_REGISTRATION, artifacts=[_DOC_BYTES_2]
            )
        ],
    )
    assert submission.status == "Active"

    # Grace window lapses without a decision -> drops to Under Verification.
    lapse = await partner.grace_lapse(partner_id)
    assert lapse.status == "Under Verification"
    assert lapse.round == 2

    # The profile row confirms the drop.
    profile = await _query(database_url, "SELECT status FROM partner.partner_profiles")
    assert profile == [{"status": "Under Verification"}]

    # A lapse is NOT a deactivation: no credential.invalidated, no partner.rejected.
    outbox = await _query(database_url, "SELECT event_type FROM partner.partner_outbox")
    event_types = [row["event_type"] for row in outbox]
    assert "credential.invalidated" not in event_types
    assert "partner.rejected" not in event_types

    # The role stays Active - the partner is still practicing while queued again.
    assert await iam.partner_role_status(identity_id) == "Active"


@pytest.mark.asyncio
async def test_lapse_then_reject_revokes_role(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    """AC2+AC3: lapse drops to Under Verification; a subsequent operator reject
    on the re-entered queue deactivates the partner via partner.rejected (T03
    chain suspends the role). No credential.invalidated in this path because
    the reject is against an Under Verification partner (first-time rejection),
    not an Active partner (reverification failure)."""
    iam, partner = _facade(database_url, tmp_path)
    partner_id, identity_id = await _register_approve_activate(partner)

    registry = _registry()
    await _dispatch_to_iam(
        registry,
        partner_activated_envelope(partner_id, identity_id, _OPERATOR_ID),
    )
    assert await iam.partner_role_status(identity_id) == "Active"

    # Re-submit -> stays Active (round 2 queued).
    await partner.submit_credentials(
        partner_id,
        credentials=[
            CredentialSubmission(
                credential_type=CredentialType.MEDICAL_REGISTRATION, artifacts=[_DOC_BYTES_2]
            )
        ],
    )

    # Grace window lapses -> Under Verification.
    lapse = await partner.grace_lapse(partner_id)
    assert lapse.status == "Under Verification"

    # The partner is now Under Verification; operator rejects the re-queued round.
    decision = await partner.operator_decision(
        partner_id,
        decision_by=_OPERATOR_ID,
        approve=False,
        reason="documents expired",
    )
    assert decision.status == "Rejected"

    # partner.rejected fires (not credential.invalidated - the partner was
    # Under Verification at the time of the reject, not Active).
    outbox = await _query(database_url, "SELECT event_type FROM partner.partner_outbox")
    event_types = [row["event_type"] for row in outbox]
    assert "credential.invalidated" not in event_types
    assert "partner.rejected" in event_types

    # The T03 chain: partner.rejected suspends the role.
    await _dispatch_to_iam(
        registry,
        partner_rejected_envelope(
            partner_id,
            identity_id=identity_id,
            reason="documents expired",
            round=2,
            decision_by=_OPERATOR_ID,
        ),
    )
    assert await iam.partner_role_status(identity_id) == "Suspended"


@pytest.mark.asyncio
async def test_no_background_expiry_scan(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    """AC5: background expiry-scanning is explicitly out of scope (Phase 6).

    This test verifies the current seam is purely event-driven: nothing changes
    a partner's status or emits credential.invalidated until the caller
    explicitly invokes grace_lapse or operator_decision - and a freshly-approved
    partner with no open reverification round cannot be lapsed at all.
    """
    _, partner = _facade(database_url, tmp_path)
    partner_id, _ = await _register_approve_activate(partner)

    # A waiting period is simulated by not invoking any operation: the partner
    # stays Active until an explicit action occurs.
    outbox_before = await _query(database_url, "SELECT event_type FROM partner.partner_outbox")
    profile_before = await _query(database_url, "SELECT status FROM partner.partner_profiles")

    # Nothing happened - state is stable.
    assert profile_before == [{"status": "Active"}]
    events_before = [row["event_type"] for row in outbox_before]
    assert "credential.invalidated" not in events_before

    # No background scan fired, and a lapse is refused outright for a partner
    # with no open, undecided reverification round (AC2 precondition).
    with pytest.raises(IllegalPartnerTransitionError):
        await partner.grace_lapse(partner_id)

    # Open a reverification round (re-submit), then the event-driven lapse seam
    # drops the partner on the explicit invocation.
    await partner.submit_credentials(
        partner_id,
        credentials=[
            CredentialSubmission(
                credential_type=CredentialType.MEDICAL_REGISTRATION, artifacts=[_DOC_BYTES_2]
            )
        ],
    )
    lapse = await partner.grace_lapse(partner_id)
    assert lapse.status == "Under Verification"
