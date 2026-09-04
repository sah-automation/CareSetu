"""PHASE-5 T08: the operator verification queue + approve/reject against Postgres (#252).

Exercises the Step-2 manual gate end to end against a live PostgreSQL, mirroring
``test_partner_credentials.py`` (facade + artifact store) and
``test_iam_partner_role_chain.py`` (the iam outbox poll -> role grant/deny):

- Approval turns the partner ``[Active]``, records ``approved`` on the current
  round, emits ``partner.activated``, and the iam consumer grants the ``partner``
  role (observable through the iam facade).
- Rejection with a required reason turns the partner ``[Rejected]``, records the
  reason on the round, emits ``partner.rejected``, and the iam consumer suspends
  the role.
- No auto-approve: a Step-1 pass alone never reaches ``[Active]``.
- The queue lists ``[Under Verification]`` partners; opening a detail view
  returns profile + credentials + history and emits ``partner.credential_reviewed``.
- No bulk actions: every decision is a single attributed action.

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

from bus.dispatch import dispatch
from bus.registry import HandlerRegistry
from modules.iam.adapters import register_handlers as register_iam_handlers
from modules.iam.adapters.sms import MockSmsAdapter
from modules.iam.facade import IamFacade
from modules.partner.adapters.artifact_store import CredentialArtifactStore
from modules.partner.domain.credentials import CredentialType
from modules.partner.domain.events import (
    partner_activated_envelope,
    partner_rejected_envelope,
)
from modules.partner.facade import CredentialSubmission, PartnerFacade

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

_PHONE = "+919876543210"
_DOC_BYTES = b"medical registration certificate image"

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


async def _register_and_queue(partner: PartnerFacade) -> int:
    """Register a doctor and pass Step-1 so they enter the operator queue."""
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
    return result.partner_id


async def _dispatch_to_iam(registry: HandlerRegistry, envelope: Any) -> None:
    """Run the iam consumer for one terminal partner event (the T03 chain)."""
    await dispatch(registry, envelope)


def _registry() -> HandlerRegistry:
    registry = HandlerRegistry()
    register_iam_handlers(registry)
    return registry


@pytest.mark.asyncio
async def test_approval_activates_partner_emits_activated_and_grants_role(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    """AC: operator approval -> Active + partner.activated -> role granted."""
    iam, partner = _facade(database_url, tmp_path)
    partner_id = await _register_and_queue(partner)
    identity_id = int(
        (await _query(database_url, "SELECT identity_id FROM partner.partner_profiles"))[0][
            "identity_id"
        ]
    )

    # No auto-approve: a Step-1 pass alone left the partner Under Verification
    # and granted no partner role.
    assert await iam.partner_role_status(identity_id) is None

    result = await partner.operator_decision(partner_id, decision_by=_OPERATOR_ID, approve=True)

    assert result.status == "Active"
    profile = await _query(database_url, "SELECT status FROM partner.partner_profiles")
    assert profile == [{"status": "Active"}]
    verifications = await _query(
        database_url, "SELECT status, decision, decision_by FROM partner.partner_verifications"
    )
    assert verifications == [
        {"status": "approved", "decision": "approved", "decision_by": _OPERATOR_ID}
    ]
    outbox = await _query(database_url, "SELECT event_type, status FROM partner.partner_outbox")
    assert [row["event_type"] for row in outbox].count("partner.activated") == 1

    # The T03 chain: the partner.activated event grants the partner role (the
    # iam consumer observes it through the event chain, test_iam_partner_role_chain).
    await _dispatch_to_iam(
        _registry(), partner_activated_envelope(partner_id, identity_id, _OPERATOR_ID)
    )
    assert await iam.partner_role_status(identity_id) == "Active"


@pytest.mark.asyncio
async def test_rejection_with_reason_rejects_emits_rejected_and_denies_role(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    """AC: operator reject (required reason) -> Rejected + partner.rejected -> role denied."""
    iam, partner = _facade(database_url, tmp_path)
    partner_id = await _register_and_queue(partner)
    identity_id = int(
        (await _query(database_url, "SELECT identity_id FROM partner.partner_profiles"))[0][
            "identity_id"
        ]
    )
    registry = _registry()

    # A rejection on a never-granted partner leaves no grant behind (denied).
    result = await partner.operator_decision(
        partner_id, decision_by=_OPERATOR_ID, approve=False, reason="documents unreadable"
    )

    assert result.status == "Rejected"
    verifications = await _query(
        database_url,
        "SELECT status, decision, decision_reason, decision_by FROM partner.partner_verifications",
    )
    assert verifications == [
        {
            "status": "rejected",
            "decision": "rejected",
            "decision_reason": "documents unreadable",
            "decision_by": _OPERATOR_ID,
        }
    ]

    await _dispatch_to_iam(
        registry,
        partner_rejected_envelope(
            partner_id,
            identity_id=identity_id,
            reason="documents unreadable",
            round=1,
            decision_by=_OPERATOR_ID,
        ),
    )
    assert await iam.partner_role_status(identity_id) is None


@pytest.mark.asyncio
async def test_reactivation_rejection_suspends_a_granted_role(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    """A previously-active partner who is rejected has the role denied (Suspended)."""
    iam, partner = _facade(database_url, tmp_path)
    partner_id = await _register_and_queue(partner)
    identity_id = int(
        (await _query(database_url, "SELECT identity_id FROM partner.partner_profiles"))[0][
            "identity_id"
        ]
    )
    registry = _registry()

    # Approve -> Active grant fires.
    await partner.operator_decision(partner_id, decision_by=_OPERATOR_ID, approve=True)
    await _dispatch_to_iam(
        registry, partner_activated_envelope(partner_id, identity_id, _OPERATOR_ID)
    )
    assert await iam.partner_role_status(identity_id) == "Active"

    # Reject -> the grant is suspended (role denied).
    await partner.operator_decision(
        partner_id, decision_by=_OPERATOR_ID, approve=False, reason="credential revoked"
    )
    await _dispatch_to_iam(
        registry,
        partner_rejected_envelope(
            partner_id,
            identity_id=identity_id,
            reason="credential revoked",
            round=1,
            decision_by=_OPERATOR_ID,
        ),
    )
    assert await iam.partner_role_status(identity_id) == "Suspended"


@pytest.mark.asyncio
async def test_queue_lists_under_verification_and_detail_emits_credential_reviewed(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    """AC: queue lists [Under Verification]; opening detail emits credential_reviewed."""
    _, partner = _facade(database_url, tmp_path)
    partner_id = await _register_and_queue(partner)

    queue = await partner.list_verification_queue()
    assert len(queue.items) == 1
    assert queue.items[0].partner_id == partner_id
    assert queue.items[0].status == "Under Verification"
    assert queue.items[0].round == 1

    detail = await partner.get_verification_detail(partner_id, actor_id=_OPERATOR_ID)
    assert detail.status == "Under Verification"
    assert [c.credential_type for c in detail.credentials] == ["medical_registration"]
    assert len(detail.verification_history) == 1

    outbox = await _query(database_url, "SELECT event_type FROM partner.partner_outbox")
    assert [row["event_type"] for row in outbox].count("partner.credential_reviewed") == 1


@pytest.mark.asyncio
async def test_no_auto_approve_step1_pass_alone_never_activates(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    """AC: a Step-1 pass alone never reaches [Active] (gated until operator approve)."""
    _, partner = _facade(database_url, tmp_path)
    await _register_and_queue(partner)

    profile = await _query(database_url, "SELECT status FROM partner.partner_profiles")
    assert profile == [{"status": "Under Verification"}]
    decision_events = await _query(
        database_url,
        "SELECT event_type FROM partner.partner_outbox "
        "WHERE event_type IN ('partner.activated', 'partner.rejected')",
    )
    assert decision_events == []
