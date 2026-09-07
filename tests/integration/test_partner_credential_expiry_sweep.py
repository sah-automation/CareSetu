"""PHASE-6 T04b (#316): the daily credential-expiry close-out sweep.

Exercises the ``close_out_expired_credentials`` pass end to end, mirroring
``test_partner_credential_revocation.py`` (alembic head + native PostgreSQL,
skips when unreachable):

- A live partner's credential whose recorded ``expires_at`` has passed is closed
  out: ``revoked_at`` + ``invalidation_reason = 'expired'`` stamped (actor NULL -
  the sweep is a system actor), the ``partner_directory_index`` entry flipped to
  ``is_active`` false, and exactly ONE ``credential.invalidated`` (reason
  ``expired``, with the real ``credential_id``) written in the same transaction.
- Replaying the pass selects nothing (the close-out marker is the idempotency
  key): a second sweep emits no additional events.
- Lazy read-hide (ADR-0011) is correct BEFORE the sweep runs: as soon as
  ``expires_at`` passes, directory search drops the partner and the public
  profile 404s, and NOTHING is emitted - lazy reads never emit events.
- The sweep does not disturb the T04a immediate-revocation reach
  (``invalidate_credential``) nor the permanent-rejection cleanup territory:
  already-revoked and permanently-rejected partners' credentials are never
  revisited, so no double-fire and no interference with ``purge_expired_credentials``.
- Not-yet-expired and unverified (undecided operator-gate round) credentials are
  not candidates.

The expiry field is injected as raw SQL exactly like ``test_directory_search.py``
injects the index row / verified flag: the review-acceptance expiry writer lives
in the Phase-6 verification wiring (not this ticket's scope). The sweep itself
goes through the real facade.

Requires the native PostgreSQL; the suite skips cleanly when unreachable.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from conftest import seed_daltonganj_service_area
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

import worker.main as worker_main
from app.config import Settings
from modules.iam.adapters.sms import MockSmsAdapter
from modules.iam.facade import IamFacade
from modules.partner.adapters.artifact_store import CredentialArtifactStore
from modules.partner.domain.credentials import CredentialType
from modules.partner.domain.exceptions import (
    PartnerIamUnavailableError,
    ProviderProfileNotFoundError,
)
from modules.partner.facade import (
    DALTONGANJ_LATITUDE,
    DALTONGANJ_LONGITUDE,
    CredentialSubmission,
    PartnerFacade,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

_OPERATOR_ID = 77
_DOC_BYTES = b"medical registration certificate image"
_PAST = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)


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
                    "partner.partner_directory_index, partner.partner_outbox, "
                    "partner.partner_service_areas, iam.iam_role_grants, "
                    "iam.iam_sessions, iam.iam_otp_challenges, iam.iam_outbox, "
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


async def _execute(database_url: str, sql: str, params: dict[str, Any]) -> None:
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(sql), params)
    finally:
        await engine.dispose()


def _facade(database_url: str, tmp_path: Path) -> tuple[IamFacade, PartnerFacade]:
    engine = create_async_engine(database_url, poolclass=NullPool)
    iam = IamFacade(engine=engine, sms_adapter=MockSmsAdapter())
    store = CredentialArtifactStore(root=tmp_path, key_bytes=bytes(32))
    partner = PartnerFacade(engine=engine, iam_facade=iam, artifact_store=store)
    return iam, partner


async def _approve_active_partner(partner: PartnerFacade, phone: str) -> int:
    """Run the real Phase-5 flow to a visible ``[Active]`` partner."""
    registered = await partner.register(
        phone=phone,
        partner_type="doctor",
        practice_address="Station Road, Daltonganj",
        practice_latitude=DALTONGANJ_LATITUDE,
        practice_longitude=DALTONGANJ_LONGITUDE,
    )
    assert registered.status == "Registered"
    partner_id = registered.partner_id
    await partner.submit_credentials(
        partner_id,
        credentials=[
            CredentialSubmission(
                credential_type=CredentialType.MEDICAL_REGISTRATION, artifacts=[_DOC_BYTES]
            )
        ],
    )
    await partner.operator_decision(partner_id, decision_by=_OPERATOR_ID, approve=True)
    return partner_id


async def _make_visible(database_url: str, partner_id: int) -> None:
    """Inject the index row + verified flag the Phase-6 writer seams still own."""
    await _execute(
        database_url,
        "INSERT INTO partner.partner_directory_index "
        "(partner_id, practice_latitude, practice_longitude, "
        " partner_type, is_active) "
        "VALUES (:partner_id, :lat, :lon, 'doctor', true)",
        {
            "partner_id": partner_id,
            "lat": DALTONGANJ_LATITUDE,
            "lon": DALTONGANJ_LONGITUDE,
        },
    )
    await _execute(
        database_url,
        "UPDATE partner.partner_credentials SET verified = true WHERE profile_id = :partner_id",
        {"partner_id": partner_id},
    )


async def _expire_credentials(database_url: str, partner_id: int) -> int:
    """Stamp ``expires_at`` in the past on the partner's credentials (raw SQL seam)."""
    await _execute(
        database_url,
        "UPDATE partner.partner_credentials SET expires_at = :expires "
        "WHERE profile_id = :partner_id",
        {"partner_id": partner_id, "expires": _PAST},
    )
    return int((await _query(database_url, "SELECT id FROM partner.partner_credentials"))[0]["id"])


async def _credential_state(database_url: str) -> list[dict[str, Any]]:
    return await _query(
        database_url,
        "SELECT revoked_at, revoked_by, invalidation_reason, verified, expires_at "
        "FROM partner.partner_credentials",
    )


async def _invalidated_events(database_url: str) -> list[dict[str, Any]]:
    return await _query(
        database_url,
        "SELECT payload FROM partner.partner_outbox WHERE event_type = 'credential.invalidated'",
    )


@pytest.mark.asyncio
async def test_sweep_closes_out_expired_credential_deindexes_and_emits_once(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    """#316 AC: one event per expired credential + deindex, in one transaction.

    A live, visible Active partner's credential that has passed its recorded
    ``expires_at`` is closed out by one sweep pass: the close-out marker
    (``invalidation_reason = 'expired'``, ``revoked_at`` stamped, no actor),
    the directory entry flipped inactive, and exactly one ``credential.invalidated``
    with the real ``credential_id`` and reason ``expired``.
    """
    _, partner = _facade(database_url, tmp_path)
    partner_id = await _approve_active_partner(partner, "9876543201")
    await _make_visible(database_url, partner_id)
    credential_id = await _expire_credentials(database_url, partner_id)

    closed = await partner.close_out_expired_credentials()

    assert closed == [credential_id]
    assert await _query(database_url, "SELECT is_active FROM partner.partner_directory_index") == [
        {"is_active": False}
    ]

    state = await _credential_state(database_url)
    assert len(state) == 1
    assert state[0]["revoked_at"] is not None
    assert state[0]["revoked_by"] is None
    assert state[0]["invalidation_reason"] == "expired"

    events = await _invalidated_events(database_url)
    assert len(events) == 1
    assert events[0]["payload"]["credential_id"] == credential_id
    assert events[0]["payload"]["reason"] == "expired"

    assert [entry.partner_id for entry in (await partner.search_directory()).items] == []


@pytest.mark.asyncio
async def test_sweep_is_idempotent_on_replay(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    """#316 AC: replaying the sweep (at-least-once job) emits nothing more.

    The close-out marker is the idempotency key: a second pass selects no
    candidate rows, so the event registry sees exactly the one event from the
    first pass.
    """
    _, partner = _facade(database_url, tmp_path)
    partner_id = await _approve_active_partner(partner, "9876543202")
    await _make_visible(database_url, partner_id)
    await _expire_credentials(database_url, partner_id)

    assert await partner.close_out_expired_credentials() != []
    assert await partner.close_out_expired_credentials() == []

    assert len(await _invalidated_events(database_url)) == 1


@pytest.mark.asyncio
async def test_expired_partner_hidden_on_reads_before_the_sweep_runs(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    """#316 AC: correctness is lazy - no job needed to hide an expired partner.

    The moment ``expires_at`` passes, search drops the partner and the public
    profile 404s, and NO ``credential.invalidated`` is emitted - lazy reads never
    write events.
    """
    _, partner = _facade(database_url, tmp_path)
    partner_id = await _approve_active_partner(partner, "9876543203")
    await _make_visible(database_url, partner_id)

    assert [entry.partner_id for entry in (await partner.search_directory()).items] == [partner_id]
    await partner.get_provider_profile(partner_id)  # reachable while valid

    await _expire_credentials(database_url, partner_id)

    assert [entry.partner_id for entry in (await partner.search_directory()).items] == []
    with pytest.raises(ProviderProfileNotFoundError):
        await partner.get_provider_profile(partner_id)

    assert await _invalidated_events(database_url) == []


@pytest.mark.asyncio
async def test_sweep_does_not_disturb_revoked_credential(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    """#316 AC: the sweep never revisits a T04a-revoked credential.

    A credential the immediate revocation reach already closed out
    (``invalidation_reason = 'revoked'``) - even one whose ``expires_at`` has also
    passed - is not a candidate: its close-out marker is set, so the sweep skips
    it and emits no second event.
    """
    _, partner = _facade(database_url, tmp_path)
    partner_id = await _approve_active_partner(partner, "9876543204")
    acting_principal = uuid4()
    await partner.invalidate_credential(partner_id, revoked_by=acting_principal)
    await _expire_credentials(database_url, partner_id)

    assert await partner.close_out_expired_credentials() == []

    state = await _credential_state(database_url)
    assert state[0]["revoked_by"] == acting_principal
    assert state[0]["invalidation_reason"] == "revoked"
    assert state[0]["revoked_at"] is not None

    events = await _invalidated_events(database_url)
    assert len(events) == 1
    assert events[0]["payload"]["reason"] == "revoked"


@pytest.mark.asyncio
async def test_sweep_skips_rejected_partner_cleanup_rows(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    """#316: permanent-rejection cleanup territory stays with purge.

    A permanently-rejected partner's expired credential - which the rejection
    path scheduled for the ``purge_expired_credentials`` seam - is not a sweep
    candidate: no additional close-out marker, no additional event. The moment a
    rejection of an ``[Active]`` partner already fired the single
    ``credential.invalidated`` (reason ``reverification_failed``), the expiry
    sweep must not double-fire the chain.
    """
    _, partner = _facade(database_url, tmp_path)
    partner_id = await _approve_active_partner(partner, "9876543205")
    await partner.operator_decision(
        partner_id, decision_by=_OPERATOR_ID, approve=False, reason="license lapsed"
    )
    await _expire_credentials(database_url, partner_id)

    assert await partner.close_out_expired_credentials() == []

    state = await _credential_state(database_url)
    assert len(state) == 1
    assert state[0]["invalidation_reason"] is None
    assert state[0]["revoked_at"] is None

    events = await _invalidated_events(database_url)
    assert len(events) == 1
    assert events[0]["payload"]["reason"] != "expired"


@pytest.mark.asyncio
async def test_sweep_skips_unverified_round(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    """#316: an undecided operator-gate round's expiry is the gate, not the sweep.

    A credential from a non-Active round (under verification, ``verified = false``)
    whose ``expires_at`` has passed is not closed out - its fate belongs to the
    operator decision, and the sweep never fires the event chain for it.
    """
    _, partner = _facade(database_url, tmp_path)
    registered = await partner.register(
        phone="9876543206",
        partner_type="doctor",
        practice_address="Station Road, Daltonganj",
        practice_latitude=DALTONGANJ_LATITUDE,
        practice_longitude=DALTONGANJ_LONGITUDE,
    )
    await partner.submit_credentials(
        registered.partner_id,
        credentials=[
            CredentialSubmission(
                credential_type=CredentialType.MEDICAL_REGISTRATION, artifacts=[_DOC_BYTES]
            )
        ],
    )
    await _execute(
        database_url,
        "UPDATE partner.partner_credentials SET expires_at = :expires "
        "WHERE profile_id = :partner_id",
        {"partner_id": registered.partner_id, "expires": _PAST},
    )

    assert await partner.close_out_expired_credentials() == []
    assert await _invalidated_events(database_url) == []


@pytest.mark.asyncio
async def test_sweep_leaves_unexpired_active_partner_untouched(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    """#316: a valid credential is never a candidate - no-op pass, no event."""
    _, partner = _facade(database_url, tmp_path)
    partner_id = await _approve_active_partner(partner, "9876543207")
    await _make_visible(database_url, partner_id)

    assert await partner.close_out_expired_credentials() == []
    assert await _invalidated_events(database_url) == []
    assert await _query(database_url, "SELECT is_active FROM partner.partner_directory_index") == [
        {"is_active": True}
    ]


@pytest.mark.asyncio
async def test_sweep_runs_on_a_facade_composed_without_iam(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    """WI-3 (#336): the worker's sweep stack is iam-free and still closes out.

    ``worker_main._build_sweep_facade`` composes a ``PartnerFacade`` on a bare
    engine - no iam facade, no SMS adapter, no MFA secret. Against a real
    database that is enough to run the daily close-out: an Active partner whose
    credential has expired is deindexed and emits exactly the one
    ``credential.invalidated`` event.
    """
    _, setup_partner = _facade(database_url, tmp_path)
    partner_id = await _approve_active_partner(setup_partner, "9876543208")
    await _make_visible(database_url, partner_id)
    credential_id = await _expire_credentials(database_url, partner_id)

    engine = create_async_engine(database_url, poolclass=NullPool)
    sweep_facade = worker_main._build_sweep_facade(Settings(), engine)
    assert sweep_facade._registration._iam is None

    closed = await sweep_facade.close_out_expired_credentials()
    await engine.dispose()

    assert closed == [credential_id]
    assert await _query(database_url, "SELECT is_active FROM partner.partner_directory_index") == [
        {"is_active": False}
    ]

    events = await _invalidated_events(database_url)
    assert len(events) == 1
    assert events[0]["payload"]["credential_id"] == credential_id
    assert events[0]["payload"]["reason"] == "expired"


@pytest.mark.asyncio
async def test_register_fails_loudly_when_the_composed_facade_lacks_iam(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    """WI-3 (#336): an iam-free partner facade is unusable for registration.

    The sweep stack never registers, but a caller that tries to register with a
    facade that was composed without the iam seam gets a typed
    ``PartnerIamUnavailableError`` before the transaction opens - the profile
    cannot be written because the sync credential account would be silently
    missing (ADR-0010 atomicity).
    """
    engine = create_async_engine(database_url, poolclass=NullPool)
    sweep_facade = worker_main._build_sweep_facade(Settings(), engine)

    with pytest.raises(PartnerIamUnavailableError):
        await sweep_facade.register(
            phone="9876543209",
            partner_type="doctor",
            practice_address="Station Road, Daltonganj",
            practice_latitude=DALTONGANJ_LATITUDE,
            practice_longitude=DALTONGANJ_LONGITUDE,
        )
    await engine.dispose()
