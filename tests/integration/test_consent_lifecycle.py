"""PHASE-3 T3: consent lifecycle + event round-trip against native PostgreSQL (#212, FEAT-002).

Proves the ticket's acceptance criteria on the real database:

1. Lineage rules (facade-over-schema): a direct grant mints live standing
   grant v1, a re-grant mints vN+1 inside the SAME ``(patient,
   counterparty type, counterparty id, record scope)`` lineage, and a
   different scope opens a separate lineage at v1 whose versions never
   rewrite the earlier ones.
2. Revocation is terminal per version and durable-before-inactive: once the
   call commits, fresh readers see ``revoked``; revoking again is refused;
   the revoked grant stays listed with its expandable history.
3. Decline closes a request without creating any grant.
4. ``consent.requested/granted/revoked`` plus ``audit.event`` fan out
   through the REAL composition-root registry and dispatcher poll loop, an
   exact audit row lands for 100% of consent actions (KPI-006), and replay
   of the same ``event_id`` is a no-op (coding-standards §6).
5. Ownership: non-owner actions are refused; unknown ids answer not-found.

Requires the native PostgreSQL; the suite skips cleanly when it is
unreachable, migrates to head for the module and downgrades afterwards,
leaving the database as it was found.
"""

from __future__ import annotations

import asyncio
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

from bus.dispatcher import DispatcherConfig, discover_outbox_tables, run_poll_loop
from bus.envelope import Envelope
from bus.ledger import record_consumed_event
from bus.outbox_ddl import materialize_consumed_events
from bus.outbox_writer import write_outbox
from bus.registry import Handler
from modules.consent.domain.events import consent_granted_envelope
from modules.consent.domain.exceptions import (
    ConsentAccessDeniedError,
    ConsentNotFoundError,
    IllegalConsentTransitionError,
)
from modules.consent.facade import ConsentFacade
from worker.main import build_registry

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

_PATIENT = 701
_OTHER_PATIENT = 702


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture(scope="module")
def migrated_schema(database_url: str) -> Iterator[None]:
    """Migrate to head (iam + health + consent deltas) for the module."""
    config = _alembic_config(database_url)
    try:
        command.upgrade(config, "head")
    except Exception as exc:
        pytest.skip(f"PostgreSQL unreachable at {database_url} - {exc}")
    yield
    command.downgrade(config, "base")


@pytest_asyncio.fixture
async def clean_tables(database_url: str, migrated_schema: None) -> AsyncIterator[None]:
    """Empty the consent tables before every test."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "TRUNCATE TABLE consent.consent_consents, "
                    "consent.consent_events, consent.consent_outbox CASCADE"
                )
            )
    finally:
        await engine.dispose()
    yield


def _facade(database_url: str) -> ConsentFacade:
    return ConsentFacade(create_async_engine(database_url, poolclass=NullPool))


async def _query(database_url: str, sql: str) -> list[dict[str, Any]]:
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text(sql))
            return [dict(row) for row in result.mappings().all()]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_regrant_mints_versions_in_one_lineage_and_new_scope_opens_another(
    database_url: str, clean_tables: None
) -> None:
    """AC1: v1 on first grant, vN+1 within the lineage, new scope = new lineage."""
    facade = _facade(database_url)

    first = await facade.grant_consent(_PATIENT, "doctor", "dr-77", "consultations")
    regrant = await facade.grant_consent(_PATIENT, "doctor", "dr-77", "consultations")
    other_scope = await facade.grant_consent(_PATIENT, "doctor", "dr-77", "prescriptions")

    # Same triple: one lineage, version minted forward, reference unchanged.
    assert (first.status, first.version) == ("granted", 1)
    assert (regrant.consent_id, regrant.version) == (first.consent_id, 2)
    assert (
        regrant.lineage_ref
        == first.lineage_ref
        == f"C-{first.created_at.year}-{first.consent_id:03d}"
    )
    # Different scope to the same counterparty: separate lineage back at v1.
    assert other_scope.consent_id != first.consent_id
    assert other_scope.record_scope == "prescriptions"
    assert (other_scope.status, other_scope.version) == ("granted", 1)
    assert other_scope.lineage_ref.startswith("C-")

    ledger = await _query(
        database_url,
        f"SELECT kind, version FROM consent.consent_events WHERE consent_id = {first.consent_id} "
        "ORDER BY occurred_at DESC, id DESC",
    )
    # Both grants are in the immutable ledger; the earlier version survives.
    assert ledger == [{"kind": "granted", "version": 2}, {"kind": "granted", "version": 1}]


@pytest.mark.asyncio
async def test_revocation_is_durable_terminal_and_still_listed(
    database_url: str, clean_tables: None
) -> None:
    """AC2 + AC18: revoked stays listed with expandable receipts; no re-revoke."""
    facade = _facade(database_url)
    granted = await facade.grant_consent(_PATIENT, "lab", "lab-9", "metrics")

    revoked = await facade.revoke_consent(_PATIENT, granted.consent_id)

    assert (revoked.status, revoked.version) == ("revoked", 1)
    # Durable-before-inactive: a completely fresh reader sees the terminal
    # state immediately after the commit that wrote it.
    fresh = _facade(database_url)
    log = await fresh.list_consents(_PATIENT)
    listed = [item for item in log.items if item.consent_id == granted.consent_id]
    assert len(listed) == 1
    assert listed[0].status == "revoked"
    assert [(event.kind, event.version) for event in listed[0].events] == [
        ("revoked", 1),
        ("granted", 1),
    ]

    with pytest.raises(IllegalConsentTransitionError):
        await fresh.revoke_consent(_PATIENT, granted.consent_id)


@pytest.mark.asyncio
async def test_decline_closes_a_request_without_creating_a_grant(
    database_url: str, clean_tables: None
) -> None:
    """AC3 + AC12: declining is respected; no version is ever minted."""
    facade = _facade(database_url)
    asked = await facade.request_consent(_PATIENT, "chemist", "ch-2", "full_record")

    assert (asked.status, asked.version) == ("requested", 0)

    declined = await facade.decline_consent(_PATIENT, asked.consent_id)

    assert (declined.status, declined.version) == ("declined", 0)
    ledger = await _query(
        database_url,
        "SELECT kind, version FROM consent.consent_events "
        f"WHERE consent_id = {asked.consent_id} ORDER BY occurred_at DESC, id DESC",
    )
    assert ledger == [
        {"kind": "declined", "version": 0},
        {"kind": "requested", "version": 0},
    ]
    # A declined lineage carries no grant receipt anywhere.
    grants = await _query(
        database_url,
        f"SELECT COUNT(*) AS n FROM consent.consent_events WHERE consent_id = {asked.consent_id} "
        "AND kind = 'granted'",
    )
    assert grants[0]["n"] == 0


@pytest.mark.asyncio
async def test_duplicate_request_and_illegal_transitions_are_refused(
    database_url: str, clean_tables: None
) -> None:
    """The machine rejects edges outside the binding diagram for real rows."""
    facade = _facade(database_url)
    await facade.request_consent(_PATIENT, "doctor", "dr-5", "lab_results")

    with pytest.raises(IllegalConsentTransitionError):
        await facade.request_consent(_PATIENT, "doctor", "dr-5", "lab_results")


@pytest.mark.asyncio
async def test_non_owner_and_unknown_actions_are_refused(
    database_url: str, clean_tables: None
) -> None:
    facade = _facade(database_url)
    granted = await facade.grant_consent(_PATIENT, "doctor", "dr-8", "metrics")

    with pytest.raises(ConsentAccessDeniedError):
        await _facade(database_url).revoke_consent(_OTHER_PATIENT, granted.consent_id)
    with pytest.raises(ConsentNotFoundError):
        await facade.revoke_consent(_PATIENT, 424242)


def _ledger_subscriber(database_url: str, schema: str) -> Handler:
    """An idempotent stand-in subscriber writing its ledger row first.

    Mirrors the production adapter contract: ``if not delivered: return`` -
    a redelivered ``event_id`` is a no-op, never an error.
    """

    async def handler(envelope: Envelope[Any]) -> None:
        engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
        try:
            async with engine.begin() as connection:
                delivered = await record_consumed_event(
                    connection, schema, envelope, handler_result={"handler": "t3_probe"}
                )
                if not delivered:
                    return
        finally:
            await engine.dispose()

    return handler


async def _drive_dispatcher(database_url: str, ledger_schema: str, expected_rows: int) -> None:
    """Drive the real composition-root registry until the ledger is full."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        registry = build_registry()
        for event_type in (
            "consent.requested",
            "consent.granted",
            "consent.revoked",
            "audit.event",
        ):
            registry.register(event_type, _ledger_subscriber(database_url, ledger_schema))
        async with engine.begin() as connection:
            await materialize_consumed_events(connection, ledger_schema)

        async def probe() -> int:
            async with engine.connect() as connection:
                count = await connection.scalar(
                    text(f'SELECT COUNT(*) FROM "{ledger_schema}".consumed_events')
                )
            return int(count or 0)

        async def drive() -> None:
            async with engine.connect() as connection:
                tables = await discover_outbox_tables(connection, ("iam", "health", "consent"))
            stop_event = asyncio.Event()
            task = asyncio.create_task(
                run_poll_loop(
                    engine,
                    tables,
                    registry,
                    DispatcherConfig(poll_interval_seconds=0.05),
                    stop_event=stop_event,
                )
            )
            for _ in range(400):
                if await probe() >= expected_rows:
                    break
                await asyncio.sleep(0.05)
            stop_event.set()
            await task

        await drive()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_every_action_fans_out_with_exact_audit_coverage_and_dedupes(
    database_url: str, clean_tables: None, throwaway_schema: str
) -> None:
    """AC5: consent.* + audit fan-out through the dispatcher; KPI-006 holds."""
    facade = _facade(database_url)
    asked = await facade.request_consent(_PATIENT, "doctor", "dr-1", "consultations")
    await facade.grant_requested(_PATIENT, asked.consent_id)
    granted = await facade.grant_consent(_PATIENT, "lab", "lab-3", "consultations")
    await facade.revoke_consent(_PATIENT, granted.consent_id)
    to_decline = await facade.request_consent(_PATIENT, "chemist", "ch-7", "metrics")
    await facade.decline_consent(_PATIENT, to_decline.consent_id)

    # Six actions: two requests, two grants, one revoke, one decline.
    # Coverage is exact: an audit row for EVERY action, lifecycle rows only
    # where the §4.2 registry defines them (no consent.declined exists).
    coverage = {
        row["event_type"]: row["n"]
        for row in await _query(
            database_url,
            "SELECT event_type, COUNT(*) AS n FROM consent.consent_outbox GROUP BY event_type",
        )
    }
    assert coverage == {
        "audit.event": 6,
        "consent.requested": 2,
        "consent.granted": 2,
        "consent.revoked": 1,
    }

    # Replay proof: the same event_id published twice is delivered twice by
    # the loop and recorded ONCE by the subscriber's ledger PK.
    replay_envelope = consent_granted_envelope(
        granted.consent_id, granted.lineage_ref, _PATIENT, "lab", "lab-3", "consultations", 1
    )
    for _ in range(2):
        engine = create_async_engine(database_url, poolclass=NullPool)
        try:
            async with engine.begin() as connection:
                await write_outbox(connection, "consent", "consent_outbox", replay_envelope)
        finally:
            await engine.dispose()

    # 11 lifecycle/audit rows + 2 duplicate rows = 13 claimed deliveries,
    # 12 distinct event_ids in the ledger (the duplicated pair dedupes to one).
    await _drive_dispatcher(database_url, throwaway_schema, expected_rows=12)

    ledger = await _query(
        database_url,
        f'SELECT event_type, COUNT(*) AS n FROM "{throwaway_schema}".consumed_events '
        "GROUP BY event_type",
    )
    by_type = {row["event_type"]: row["n"] for row in ledger}
    assert by_type == {
        "audit.event": 6,
        "consent.requested": 2,
        "consent.granted": 3,
        "consent.revoked": 1,
    }
    remaining = await _query(database_url, "SELECT COUNT(*) AS n FROM consent.consent_outbox")
    assert remaining[0]["n"] == 0
