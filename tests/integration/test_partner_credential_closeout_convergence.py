"""#331 (WI-1): the four close-out paths converge on an identical outcome.

Pins the convergent close-out contract from the credential-validity deep module:
every path that invalidates a credential - operator reject of an ``[Active]``
partner, credential revocation, the daily expiry sweep, and the permanent-
rejection purge - must produce an *indistinguishable* ``credential.invalidated``
outcome through ``close_out_credentials``: the same envelope payload shape
(``partner_id`` + ``identity_id`` + ``credential_id`` + a ``reason`` from the
vocabulary), the same ``partner_directory_index`` deindex (``is_active`` false),
and the same best-effort directory-cache flush.

Mirrors ``test_partner_credential_cleanup.py`` (alembic head + native
PostgreSQL, skips when unreachable). Each test drives ONE path end to end and
asserts the same shape against the same helpers, so the four paths are compared
side by side. The index row and the ``verified`` flag seam are injected as raw
SQL exactly like ``test_directory_search.py`` does; the close-outs themselves go
through the real facade.

Requires the native PostgreSQL; the suite skips cleanly when unreachable.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
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

from modules.iam.adapters.sms import MockSmsAdapter
from modules.iam.facade import IamFacade
from modules.partner.adapters.artifact_store import CredentialArtifactStore
from modules.partner.domain.credentials import CredentialType
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
_NOW = datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)
_PAST = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
_INVALIDATED_KEYS = {"partner_id", "identity_id", "credential_id", "reason"}


class MutableClock:
    """Clock stand-in tests advance to walk the 30-day cleanup window."""

    def __init__(self, now: datetime) -> None:
        self._now = now

    def set(self, now: datetime) -> None:
        self._now = now

    def __call__(self) -> datetime:
        return self._now


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


async def _query(
    database_url: str, sql: str, params: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text(sql), params or {})
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


def _facade(
    database_url: str, tmp_path: Path, clock: MutableClock | None = None
) -> tuple[IamFacade, PartnerFacade]:
    engine = create_async_engine(database_url, poolclass=NullPool)
    iam = IamFacade(engine=engine, sms_adapter=MockSmsAdapter())
    store = CredentialArtifactStore(root=tmp_path, key_bytes=bytes(32))
    kwargs: dict[str, Any] = {"credential_cleanup_days": 30}
    if clock is not None:
        kwargs["clock"] = clock
    partner = PartnerFacade(engine=engine, iam_facade=iam, artifact_store=store, **kwargs)
    return iam, partner


async def _approve_active_partner(partner: PartnerFacade, phone: str) -> int:
    """Run the real Phase-5 flow to an ``[Active]``, directory-visible partner."""
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


async def _credential_id(database_url: str, partner_id: int) -> dict[str, Any]:
    return (
        await _query(
            database_url,
            "SELECT c.id, c.profile_id AS partner_id, profile.identity_id "
            "FROM partner.partner_credentials c "
            "JOIN partner.partner_profiles profile ON profile.id = c.profile_id "
            "WHERE c.profile_id = :partner_id",
            {"partner_id": partner_id},
        )
    )[0]


async def _invalidated_events(database_url: str) -> list[dict[str, Any]]:
    return await _query(
        database_url,
        "SELECT payload FROM partner.partner_outbox WHERE event_type = 'credential.invalidated'",
    )


def _assert_convergent_outcome(
    events: list[dict[str, Any]],
    *,
    partner_id: int,
    identity_id: int,
    credential_id: int,
    expected_reason: str,
    expected_event_count: int = 1,
    index_present: bool = True,
) -> None:
    """Assert the common close-out shape shared by all four paths."""
    assert len(events) == expected_event_count
    for event in events:
        payload = event["payload"]
        assert set(payload.keys()) == _INVALIDATED_KEYS
        assert payload["partner_id"] == partner_id
        assert payload["identity_id"] == identity_id
        assert payload["credential_id"] == credential_id
        assert payload["reason"] == expected_reason


async def _assert_deindexed(database_url: str, partner_id: int) -> None:
    rows = await _query(
        database_url,
        "SELECT is_active FROM partner.partner_directory_index WHERE partner_id = :partner_id",
        {"partner_id": partner_id},
    )
    assert rows == [{"is_active": False}]


@pytest.mark.asyncio
async def test_path1_operator_reject_of_active_partner_emits_indistinguishable_event(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    """Path 1 (#331): rejecting an ``[Active]`` partner routes through close-out."""
    _, partner = _facade(database_url, tmp_path)
    partner_id = await _approve_active_partner(partner, "9876543301")
    await _make_visible(database_url, partner_id)
    credential = await _credential_id(database_url, partner_id)

    await partner.operator_decision(
        partner_id, decision_by=_OPERATOR_ID, approve=False, reason="license lapsed"
    )

    _assert_convergent_outcome(
        await _invalidated_events(database_url),
        partner_id=partner_id,
        identity_id=credential["identity_id"],
        credential_id=credential["id"],
        expected_reason="license lapsed",
    )
    await _assert_deindexed(database_url, partner_id)
    assert [e.partner_id for e in (await partner.search_directory()).items] == []


@pytest.mark.asyncio
async def test_path2_revocation_emits_indistinguishable_event(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    """Path 2 (#331): ``invalidate_credential`` routes through the same close-out."""
    _, partner = _facade(database_url, tmp_path)
    partner_id = await _approve_active_partner(partner, "9876543302")
    await _make_visible(database_url, partner_id)
    credential = await _credential_id(database_url, partner_id)

    await partner.invalidate_credential(partner_id, revoked_by=uuid4())

    _assert_convergent_outcome(
        await _invalidated_events(database_url),
        partner_id=partner_id,
        identity_id=credential["identity_id"],
        credential_id=credential["id"],
        expected_reason="revoked",
    )
    await _assert_deindexed(database_url, partner_id)
    assert [e.partner_id for e in (await partner.search_directory()).items] == []


@pytest.mark.asyncio
async def test_path3_expiry_sweep_emits_indistinguishable_event(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    """Path 3 (#331): the daily expiry sweep routes through the same close-out."""
    _, partner = _facade(database_url, tmp_path)
    partner_id = await _approve_active_partner(partner, "9876543303")
    await _make_visible(database_url, partner_id)
    await _execute(
        database_url,
        "UPDATE partner.partner_credentials SET expires_at = :expires "
        "WHERE profile_id = :partner_id",
        {"partner_id": partner_id, "expires": _PAST},
    )
    credential = await _credential_id(database_url, partner_id)

    closed = await partner.close_out_expired_credentials()

    assert closed == [credential["id"]]
    _assert_convergent_outcome(
        await _invalidated_events(database_url),
        partner_id=partner_id,
        identity_id=credential["identity_id"],
        credential_id=credential["id"],
        expected_reason="expired",
    )
    await _assert_deindexed(database_url, partner_id)
    assert [e.partner_id for e in (await partner.search_directory()).items] == []


@pytest.mark.asyncio
async def test_path4_purge_emits_indistinguishable_event(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    """Path 4 (#331): the permanent-rejection purge routes through the same close-out.

    Uses a FIRST-TIME rejection (reject of an Under Verification partner), which
    does not close out any credential (only an ``[Active]`` partner's rejection
    deindexes) but schedules the 30-day cleanup window - so the purge is the sole
    ``credential.invalidated`` emitter for this partner, isolating path 4 exactly
    like ``test_partner_credential_cleanup.py`` does.
    """
    clock = MutableClock(_NOW)
    _, partner = _facade(database_url, tmp_path, clock=clock)
    registered = await partner.register(
        phone="9876543304",
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
    await partner.operator_decision(
        registered.partner_id, decision_by=_OPERATOR_ID, approve=False, reason="fraud signal"
    )
    credential = await _credential_id(database_url, registered.partner_id)
    clock.set(_NOW + timedelta(days=30))

    deleted = await partner.purge_expired_credentials()

    assert deleted == [credential["id"]]
    events = await _invalidated_events(database_url)
    # The first-time reject leaves no credential.invalidated behind - the purge
    # wrote the ONLY event, in the same shape as the three Active-path events.
    _assert_convergent_outcome(
        events,
        partner_id=registered.partner_id,
        identity_id=credential["identity_id"],
        credential_id=credential["id"],
        expected_reason="permanent_rejection_cleanup",
    )


@pytest.mark.asyncio
async def test_purge_of_two_partners_emits_event_per_credential_with_own_id(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    """Multi-row purge: one ``credential.invalidated`` per credential, own id.

    Regression pin for the prefactor: each close-out envelope must carry its own
    row's ``credential_id`` (never the last purged row's) while preserving the
    correct partner/identity mapping, so an event never names a credential that
    belongs to another partner.
    """
    clock = MutableClock(_NOW)
    _, partner = _facade(database_url, tmp_path, clock=clock)
    ids: list[int] = []
    for phone in ("9876543305", "9876543306"):
        registered = await partner.register(
            phone=phone,
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
        await partner.operator_decision(
            registered.partner_id, decision_by=_OPERATOR_ID, approve=False, reason="fraud signal"
        )
        ids.append((await _credential_id(database_url, registered.partner_id))["id"])
    clock.set(_NOW + timedelta(days=30))

    deleted = await partner.purge_expired_credentials()

    assert sorted(deleted) == sorted(ids)
    events = await _invalidated_events(database_url)
    assert len(events) == 2
    emitted_ids = {event["payload"]["credential_id"] for event in events}
    assert emitted_ids == set(ids)


@pytest.mark.asyncio
async def test_all_four_paths_produce_identical_payload_shape(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    """#331 AC: one per-credential event, identical ``credential.invalidated`` shape.

    Drives all four paths against separate partners in one database and verifies
    every emitted ``credential.invalidated`` payload has the SAME key set and
    key types - the indistinguishable outcome the ticket demands - and every
    affected directory entry is deindexed.
    """
    clock = MutableClock(_NOW)
    _, partner = _facade(database_url, tmp_path, clock=clock)

    # 4. Permanent-rejection purge first, so it is the only Rejected partner when
    #    the clock advances to the 30-day boundary (the purge selects every
    #    Rejected partner past cleanup_due_at; p1 below is also Rejected by then).
    registered_4 = await partner.register(
        phone="9876543314",
        partner_type="doctor",
        practice_address="Station Road, Daltonganj",
        practice_latitude=DALTONGANJ_LATITUDE,
        practice_longitude=DALTONGANJ_LONGITUDE,
    )
    await partner.submit_credentials(
        registered_4.partner_id,
        credentials=[
            CredentialSubmission(
                credential_type=CredentialType.MEDICAL_REGISTRATION, artifacts=[_DOC_BYTES]
            )
        ],
    )
    await partner.operator_decision(
        registered_4.partner_id, decision_by=_OPERATOR_ID, approve=False, reason="fraud"
    )
    clock.set(_NOW + timedelta(days=30))
    await partner.purge_expired_credentials()
    clock.set(_NOW)

    # 1. Operator reject of an Active partner (deactivation path).
    p1 = await _approve_active_partner(partner, "9876543311")
    await _make_visible(database_url, p1)
    await partner.operator_decision(p1, decision_by=_OPERATOR_ID, approve=False, reason="bad docs")

    # 2. Revocation.
    p2 = await _approve_active_partner(partner, "9876543312")
    await _make_visible(database_url, p2)
    await partner.invalidate_credential(p2, revoked_by=uuid4())

    # 3. Expiry sweep.
    p3 = await _approve_active_partner(partner, "9876543313")
    await _make_visible(database_url, p3)
    await _execute(
        database_url,
        "UPDATE partner.partner_credentials SET expires_at = :expires "
        "WHERE profile_id = :partner_id",
        {"partner_id": p3, "expires": _PAST},
    )
    await partner.close_out_expired_credentials()

    events = await _invalidated_events(database_url)
    # Paths 1-3 each emit one event; path 4 emits one via purge = 4 total.
    assert len(events) == 4
    payloads = [event["payload"] for event in events]
    assert all(set(p.keys()) == _INVALIDATED_KEYS for p in payloads)
    assert all(isinstance(p["partner_id"], int) for p in payloads)
    assert all(isinstance(p["identity_id"], int) for p in payloads)
    assert all(p["credential_id"] is not None for p in payloads)
    assert all(
        p["reason"] in {"revoked", "expired", "permanent_rejection_cleanup", "bad docs"}
        for p in payloads
    )

    # Paths 1-3 are Active with index rows → deindexed.
    for active_partner in (p1, p2, p3):
        await _assert_deindexed(database_url, active_partner)
