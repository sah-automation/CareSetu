"""PHASE-5 T06: credential submission + Step-1 pre-filter against real Postgres (#251).

Exercises the ``PartnerFacade.submit_credentials`` seam (with a real
``CredentialArtifactStore`` over a temp dir) against live PostgreSQL, mirroring
``test_partner_registration.py``:

- A ``[Registered]`` doctor submits a medical registration with a document: the
  bytes are AES-encrypted into the ``partner/`` prefix (ref stored, plaintext
  never), a ``partner_credentials`` row opens, the partner moves to
  ``[Under Verification]`` round 1 and ``partner.verification_started`` lands in
  the outbox.
- Step-1 auto-fails (duplicate, credential-type mismatch, missing artifacts)
  return the partner to ``[Rejected]`` with a specific reason and open NO
  verification round - never queued (ADR-0008).

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
from modules.partner.facade import CredentialSubmission, PartnerFacade

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

_PHONE = "+919876543210"
_DOC_BYTES = b"medical registration certificate image"


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
                    "iam.iam_identities CASCADE"
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


async def _register_doctor(partner: PartnerFacade) -> int:
    result = await partner.register(
        phone="9876543210",
        partner_type="doctor",
        practice_address="Station Road, Daltonganj",
        practice_latitude=24.04,
        practice_longitude=84.07,
    )
    assert result.status == "Registered"
    return result.partner_id


def _medical_submission(**overrides: Any) -> list[CredentialSubmission]:
    submission: dict[str, Any] = {
        "credential_type": CredentialType.MEDICAL_REGISTRATION,
        "artifacts": [_DOC_BYTES],
    }
    submission.update(overrides)
    return [CredentialSubmission(**submission)]


async def test_step1_pass_encrypts_artifact_queues_and_emits_verification_started(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    _, partner = _facade(database_url, tmp_path)
    partner_id = await _register_doctor(partner)

    result = await partner.submit_credentials(partner_id, credentials=_medical_submission())

    assert result.status == "Under Verification"
    assert result.round == 1
    assert result.reason is None

    profiles = await _query(database_url, "SELECT status FROM partner.partner_profiles")
    assert profiles == [{"status": "Under Verification"}]

    credentials_rows = await _query(
        database_url,
        "SELECT credential_type, verified, artifact_refs FROM partner.partner_credentials",
    )
    assert len(credentials_rows) == 1
    row = credentials_rows[0]
    assert row["credential_type"] == "medical_registration"
    assert row["verified"] is False
    refs = row["artifact_refs"]
    assert refs == {"medical_registration_0": "partner/1/medical_registration_0.enc"}

    # The artifact exists on disk, encrypted (not the plaintext).
    artifact_path = tmp_path / "partner" / "1" / "medical_registration_0.enc"
    assert artifact_path.exists()
    assert _DOC_BYTES not in artifact_path.read_bytes()

    verifications = await _query(
        database_url, "SELECT round, status FROM partner.partner_verifications"
    )
    assert verifications == [{"round": 1, "status": "queued"}]

    outbox = await _query(
        database_url,
        "SELECT event_type, payload FROM partner.partner_outbox ORDER BY event_type",
    )
    assert [r["event_type"] for r in outbox] == [
        "partner.registered",
        "partner.verification_started",
    ]
    started = next(r for r in outbox if r["event_type"] == "partner.verification_started")
    assert started["payload"] == {"partner_id": partner_id, "round": 1}


async def test_duplicate_submission_auto_fails_never_queued(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    _, partner = _facade(database_url, tmp_path)
    partner_id = await _register_doctor(partner)
    await partner.submit_credentials(partner_id, credentials=_medical_submission())

    result = await partner.submit_credentials(partner_id, credentials=_medical_submission())

    assert result.status == "Rejected"
    assert result.reason == "duplicate_credential"

    profiles = await _query(database_url, "SELECT status FROM partner.partner_profiles")
    assert profiles == [{"status": "Rejected"}]

    # The auto-fail opened NO new verification round - the queue holds only the
    # original round 1, proving the duplicate was never requeued (ADR-0008).
    verifications = await _query(
        database_url, "SELECT round, status FROM partner.partner_verifications"
    )
    assert verifications == [{"round": 1, "status": "queued"}]

    outbox_types = await _query(database_url, "SELECT event_type FROM partner.partner_outbox")
    assert [r["event_type"] for r in outbox_types] == [
        "partner.registered",
        "partner.verification_started",
        "partner.rejected",
    ]


async def test_credential_type_mismatch_auto_fails_with_specific_reason(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    _, partner = _facade(database_url, tmp_path)
    partner_id = await _register_doctor(partner)

    result = await partner.submit_credentials(
        partner_id, credentials=_medical_submission(credential_type=CredentialType.DRUG_LICENSE)
    )

    assert result.status == "Rejected"
    assert result.reason == "invalid_credential_type"
    verifications = await _query(
        database_url, "SELECT COUNT(*) AS n FROM partner.partner_verifications"
    )
    assert verifications == [{"n": 0}]


async def test_missing_artifacts_auto_fails_with_specific_reason(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    _, partner = _facade(database_url, tmp_path)
    partner_id = await _register_doctor(partner)

    result = await partner.submit_credentials(
        partner_id, credentials=_medical_submission(artifacts=[])
    )

    assert result.status == "Rejected"
    assert result.reason == "missing_artifacts"
    verifications = await _query(
        database_url, "SELECT COUNT(*) AS n FROM partner.partner_verifications"
    )
    assert verifications == [{"n": 0}]


async def test_rejected_partner_resubmits_same_type_as_new_round(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    _, partner = _facade(database_url, tmp_path)
    partner_id = await _register_doctor(partner)

    # First submission passes Step-1 and enters the queue (round 1)...
    first = await partner.submit_credentials(partner_id, credentials=_medical_submission())
    assert first.status == "Under Verification"
    assert first.round == 1

    # ...the operator rejects it at Step-2 (T08's manual gate)...
    await partner.operator_decision(
        partner_id, decision_by=99, approve=False, reason="docs unclear"
    )

    status = await _query(database_url, "SELECT status FROM partner.partner_profiles")
    assert status == [{"status": "Rejected"}]

    # ...a re-submission of the SAME type is a NEW round, not a duplicate.
    result = await partner.submit_credentials(partner_id, credentials=_medical_submission())
    assert result.status == "Under Verification"
    assert result.round == 2
    assert result.reason is None

    rounds = await _query(
        database_url, "SELECT round, status FROM partner.partner_verifications ORDER BY round"
    )
    # Round 1 was rejected at Step-2 (the operator's decision is recorded on it),
    # the re-submission opens round 2 back in the queue.
    assert rounds == [{"round": 1, "status": "rejected"}, {"round": 2, "status": "queued"}]


async def test_rejected_credential_cleanup_due_at_excludes_from_duplicate_gate(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    """S14: a credential with ``cleanup_due_at`` set must not trip the duplicate gate.

    After a permanent rejection schedules ``cleanup_due_at`` on the old credential,
    a fresh submission of the same type must pass Step-1 (not rejected as duplicate).
    Only credentials with ``cleanup_due_at IS NULL`` count toward the gate (#267).
    """
    _, partner = _facade(database_url, tmp_path)
    partner_id = await _register_doctor(partner)

    # Round 1: submit, then operator rejects - schedules cleanup on the credential.
    first = await partner.submit_credentials(partner_id, credentials=_medical_submission())
    assert first.status == "Under Verification"
    await partner.operator_decision(
        partner_id, decision_by=99, approve=False, reason="docs unclear"
    )

    # Verify cleanup_due_at was set on the old credential after rejection.
    old_cred = await _query(
        database_url,
        "SELECT cleanup_due_at FROM partner.partner_credentials WHERE round = 1",
    )
    assert len(old_cred) == 1
    assert old_cred[0]["cleanup_due_at"] is not None

    # Round 2: re-submit the SAME type - must NOT be rejected as duplicate.
    result = await partner.submit_credentials(partner_id, credentials=_medical_submission())
    assert result.status == "Under Verification"
    assert result.round == 2
    assert result.reason is None


async def test_under_verification_can_reoffer_old_rejected_round_type(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    """S13: the duplicate gate scopes to the current round, not all history.

    A partner whose round-1 type X was rejected, then re-submits a DIFFERENT type Y
    (round 2, now ``[Under Verification]``), can re-offer the old rejected type X
    in round 2 without tripping the duplicate gate. Only the current round's types
    (Y) are live for the gate - the rejected round-1 type X is a new round, not a
    duplicate (ADR-0008 recovery).
    """
    _, partner = _facade(database_url, tmp_path)
    partner_id = await _register_doctor(partner)

    # Round 1: submit qualification_certificate, then the operator rejects it.
    first = await partner.submit_credentials(
        partner_id,
        credentials=_medical_submission(credential_type=CredentialType.QUALIFICATION_CERTIFICATE),
    )
    assert first.status == "Under Verification"
    assert first.round == 1
    await partner.operator_decision(
        partner_id, decision_by=99, approve=False, reason="docs unclear"
    )

    # Round 2: re-submit a DIFFERENT type (medical_registration) - becomes round 2.
    second = await partner.submit_credentials(partner_id, credentials=_medical_submission())
    assert second.status == "Under Verification"
    assert second.round == 2

    # Now while [Under Verification] round 2, re-offer the OLD rejected round-1
    # type: this is a fresh offer of a previously-rejected type, not a duplicate.
    # Opening it starts the next verification round (round 3) - the key assertion
    # is that the gate does NOT reject it as a duplicate of the round-1 offer.
    third = await partner.submit_credentials(
        partner_id,
        credentials=[
            CredentialSubmission(
                credential_type=CredentialType.QUALIFICATION_CERTIFICATE,
                artifacts=[_DOC_BYTES],
            )
        ],
    )
    assert third.status == "Under Verification"
    assert third.round == 3
    assert third.reason is None

    rounds = await _query(
        database_url, "SELECT round, status FROM partner.partner_verifications ORDER BY round"
    )
    # Round 1 rejected; round 2 (medical_registration) queued; round 3 re-offers the
    # rejected round-1 type - all in the queue, never duplicate-rejected.
    assert rounds == [
        {"round": 1, "status": "rejected"},
        {"round": 2, "status": "queued"},
        {"round": 3, "status": "queued"},
    ]

    credentials_rows = await _query(
        database_url,
        "SELECT credential_type FROM partner.partner_credentials ORDER BY credential_type",
    )
    assert {r["credential_type"] for r in credentials_rows} == {
        "medical_registration",
        "qualification_certificate",
    }
