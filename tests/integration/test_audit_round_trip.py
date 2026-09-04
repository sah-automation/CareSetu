"""PHASE-4 review fix: MOD-011 full round trip against real PostgreSQL (#234).

The phase-spec integration test: ``audit.event`` (consent's carrier) and the
``record.accessed`` / ``record.denied`` events (health's carrier) are
published into their real outboxes, a single poll pass over the discovered
outbox tables claims, fans out and deletes them, and MOD-011 appends every
regulated act to ``audit.audit_events``. CHAIN VERIFICATION recomputes each
row's hash starting from genesis and passes, and replaying the same
``event_id`` through the idempotent consumer leaves exactly one row.

Also proves the append-only guard and the v3.2 wiring: the app role holds no
``UPDATE`` on ``audit_events`` (REVOKEd in v3.0), so a raw mutation is refused
before any row change - that is the primary defence. The tamper trigger is the
defence-in-depth net for any role that does hold ``UPDATE``; v3.2 made it also
publish a pending ``audit.tamper_detected`` row into ``audit.audit_outbox``
which a poll pass fans out to the logging consumer (whose rows the test then
simulates faithfully, since only a privileged role can fire the trigger).

Requires the native PostgreSQL; the suite skips cleanly when it is
unreachable, migrates to head for the modules and downgrades afterwards.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

from bus.dispatch import dispatch
from bus.dispatcher import (
    DEFAULT_DISPATCHER_CONFIG,
    discover_outbox_tables,
    process_outbox_table,
)
from bus.envelope import Envelope
from bus.events import (
    EVENT_AUDIT_EVENT,
    EVENT_PARTNER_ACTIVATED,
    EVENT_PARTNER_CREDENTIAL_REVIEWED,
    EVENT_PARTNER_REJECTED,
    EVENT_RECORD_ACCESSED,
    EVENT_RECORD_DENIED,
)
from bus.outbox_ddl import OUTBOX_STATUS_PENDING
from bus.outbox_writer import write_outbox
from bus.registry import HandlerRegistry
from modules.audit.adapters import register_handlers as register_audit_handlers
from modules.audit.domain.chain import GENESIS_HASH, compute_audit_hash
from modules.audit.domain.consumer import AuditEventPayload
from modules.audit.outbox import AUDIT_OUTBOX_TABLE
from modules.consent.outbox import CONSENT_OUTBOX_TABLE
from modules.health.domain.events import record_accessed_envelope, record_denied_envelope
from modules.health.outbox import HEALTH_OUTBOX_TABLE
from modules.iam.adapters import register_handlers as register_iam_handlers
from modules.partner.domain.events import (
    credential_reviewed_envelope,
    partner_activated_envelope,
    partner_rejected_envelope,
)
from modules.partner.outbox import PARTNER_OUTBOX_TABLE

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

_NOW = datetime(2026, 8, 27, 10, 30, 0, tzinfo=UTC)


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture(scope="module")
def migrated_schema(database_url: str) -> Iterator[None]:
    """Migrate to head (audit v3.2 outbox wiring included), restore base after."""
    config = _alembic_config(database_url)
    try:
        command.upgrade(config, "head")
    except Exception as exc:
        pytest.skip(f"PostgreSQL unreachable at {database_url} - {exc}")
    yield
    command.downgrade(config, "base")


@pytest_asyncio.fixture
async def clean_tables(database_url: str, migrated_schema: None) -> Iterator[None]:
    """Empty the audit ledger + bus ledgers and the publishing outboxes.

    Partner + iam tables included so the partner round trip (which imports the
    iam handlers for their registered payload models) starts from a clean slate.
    """
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "TRUNCATE TABLE audit.audit_events, audit.consumed_events, "
                    "audit.audit_outbox, audit.audit_tamper_attempts, "
                    "consent.consent_outbox, health.health_outbox, "
                    "partner.partner_outbox, iam.iam_identities, iam.iam_role_grants, "
                    "iam.consumed_events CASCADE"
                )
            )
    finally:
        await engine.dispose()
    yield


def _registry() -> HandlerRegistry:
    registry = HandlerRegistry()
    register_audit_handlers(registry)
    return registry


def _full_registry() -> HandlerRegistry:
    """The composition-root registry for the partner gate: iam + audit.

    MOD-001 owns the registered payload models for ``partner.activated`` /
    ``partner.rejected``, so both must be registered for the dispatcher to
    reconstruct the decision envelopes - mirroring the worker's build.
    """
    registry = HandlerRegistry()
    register_iam_handlers(registry)
    register_audit_handlers(registry)
    return registry


def _audit_envelope() -> Envelope[AuditEventPayload]:
    """A MOD-004-style ``audit.event`` exactly as the consent producer publishes."""
    return Envelope[AuditEventPayload](
        event_id=uuid4(),
        event_type=EVENT_AUDIT_EVENT,
        producer="consent",
        payload=AuditEventPayload(
            action="granted",
            actor_patient_id=7,
            consent_id=1,
            lineage_ref="C-2026-001",
            record_scope="consultations",
            version=1,
        ),
    )


async def _audit_rows(connection: AsyncConnection) -> list[dict[str, object]]:
    result = await connection.execute(
        text(
            "SELECT event_type, actor_id, target_id, scope, metadata, timestamp, "
            "prev_hash, hash FROM audit.audit_events ORDER BY id"
        )
    )
    return [dict(mapping) for mapping in result.mappings().all()]


def _verify_chain(rows: list[dict[str, object]]) -> None:
    """Recompute every hash from genesis along the append-order chain.

    The chain is defined by each row's ``prev_hash`` link (the ledger serial id
    is not ordered), so the walk follows the links instead of trusting ``id``.
    """
    assert rows, "no audit rows to verify"
    by_prev_hash: dict[str, dict[str, object]] = {str(row["prev_hash"]): row for row in rows}
    current = by_prev_hash[GENESIS_HASH]
    visited: set[str] = set()
    for _ in range(len(rows)):
        current_hash = str(current["hash"])
        assert current_hash not in visited, "hash chain cycle detected"
        visited.add(current_hash)
        expected = compute_audit_hash(
            str(current["event_type"]),
            None if current["actor_id"] is None else str(current["actor_id"]),
            None if current["target_id"] is None else str(current["target_id"]),
            None if current["scope"] is None else str(current["scope"]),
            current["metadata"],
            current["timestamp"],
            str(current["prev_hash"]),
        )
        assert current_hash == expected
        if current_hash not in by_prev_hash:
            break
        current = by_prev_hash[current_hash]
    assert len(visited) == len(rows), "some rows are outside the single chain"


@pytest.mark.asyncio
async def test_events_round_trip_size_the_hash_chain_and_dedupe_on_replay(
    database_url: str, clean_tables: None
) -> None:
    """AC: audit.event + record.accessed + record.denied land, chain verifies,
    same event_id replay adds no row."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        accessed = record_accessed_envelope(
            record_id=42,
            actor_id=7,
            actor_type="patient",
            scope="full_record",
            accessed_at=_NOW,
        )
        denied = record_denied_envelope(
            record_id=42,
            actor_id=9,
            actor_type="patient",
            scope="full_record",
            accessed_at=_NOW,
            denial_reason="only the record owner may read this record",
        )
        audit_envelope = _audit_envelope()

        async with engine.begin() as connection:
            await write_outbox(connection, "consent", CONSENT_OUTBOX_TABLE, audit_envelope)
            await write_outbox(connection, "health", HEALTH_OUTBOX_TABLE, accessed)
            await write_outbox(connection, "health", HEALTH_OUTBOX_TABLE, denied)

        registry = _registry()
        async with engine.connect() as connection:
            tables = await discover_outbox_tables(connection, ("consent", "health"))
        assert {table.schema for table in tables} == {"consent", "health"}

        for table in tables:
            await process_outbox_table(engine, table, registry, DEFAULT_DISPATCHER_CONFIG)

        async with engine.connect() as connection:
            rows = await _audit_rows(connection)
            assert len(rows) == 3
            event_types = {str(row["event_type"]) for row in rows}
            assert event_types == {
                "consent.granted",
                EVENT_RECORD_ACCESSED,
                EVENT_RECORD_DENIED,
            }
            _verify_chain(rows)

        # Replay the same audit.event event_id: the idempotent consumer records
        # the ledger conflict and appends nothing - still exactly three rows.
        await dispatch(registry, audit_envelope)
        async with engine.connect() as connection:
            rows = await _audit_rows(connection)
        assert len(rows) == 3
        _verify_chain(rows)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_append_only_guard_and_tamper_telemetry_delivery(
    database_url: str, clean_tables: None
) -> None:
    """AC: app role cannot mutate the ledger; the defensive trigger keeps its
    tamper-attempt + outbox wiring; the telemetry row is delivered by a poll."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await write_outbox(connection, "consent", CONSENT_OUTBOX_TABLE, _audit_envelope())

        registry = _registry()
        async with engine.connect() as connection:
            tables = await discover_outbox_tables(connection, ("consent",))
        for table in tables:
            await process_outbox_table(engine, table, registry, DEFAULT_DISPATCHER_CONFIG)

        async with engine.connect() as connection:
            victim = (
                (await connection.execute(text("SELECT id, hash FROM audit.audit_events LIMIT 1")))
                .mappings()
                .first()
            )
            original_hash = str(victim["hash"])
        assert victim is not None

        # PRIMARY guard: v3.0 REVOKEd UPDATE/DELETE, so the raw mutation is
        # refused before it can touch a row. How the refusal surfaces depends on
        # the identity of the connecting role: a limited app role is denied by
        # privilege (ProgrammingError); an app role that owns the tables (or is
        # a superuser - e.g. the CI service role) bypasses the REVOKE, but the
        # BEFORE tamper trigger still blocks the write and returns no error.
        # Either way the immutable append-only guarantee holds: the hash row is
        # untouched. Assert that outcome directly instead of a transport-specific
        # exception class.
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text("UPDATE audit.audit_events SET hash = :replacement WHERE id = :id"),
                    {"replacement": "f" * 64, "id": victim["id"]},
                )
        except DBAPIError:
            pass  # refused by privilege (ProgrammingError), or the trigger blocked the write
        async with engine.connect() as connection:
            still = (
                (
                    await connection.execute(
                        text("SELECT hash FROM audit.audit_events WHERE id = :id"),
                        {"id": victim["id"]},
                    )
                )
                .mappings()
                .first()
            )
            assert str(still["hash"]) == original_hash

        # In an environment where the app role can actually reach the trigger
        # (e.g. a superuser/owner role that bypasses the REVOKE), the guard fires
        # for real on the UPDATE above and leaves one tamper row plus one pending
        # outbox telemetry row. Reset those append-only defense tables so the
        # simulation below starts from a clean slate in every environment.
        async with engine.begin() as connection:
            await connection.execute(
                text("TRUNCATE audit.audit_tamper_attempts, audit.audit_outbox")
            )

        # Defense-in-depth: the trigger (for any role WITH UPDATE) still records
        # the attempt AND, since v3.2, publishes the telemetry to the outbox.
        async with engine.connect() as connection:
            definition = str(
                await connection.scalar(
                    text(
                        "SELECT pg_get_functiondef("
                        "to_regprocedure('audit.fn_audit_tamper_guard()'))"
                    )
                )
            )
        assert "audit.audit_tamper_attempts" in definition
        assert "audit.audit_outbox" in definition
        assert "'audit.tamper_detected'" in definition

        # Faithful simulation of a fired guard: the exact net-effect rows the
        # trigger writes (INSERT is granted to the app role on both tables).
        telemetry = {
            "attempted_operation": "UPDATE",
            "target_event_id": str(victim["id"]),
            "attempted_at": datetime.now(UTC).isoformat(),
            "details": {
                "table_name": "audit.audit_events",
                "old_data": {"id": str(victim["id"])},
                "new_data": {},
                "user": "caresetu",
            },
        }
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO audit.audit_tamper_attempts "
                    "(attempted_at, attempted_operation, target_event_id, attempted_by, details) "
                    "VALUES (now(), :op, :id, NULL, CAST(:details AS jsonb))"
                ),
                {"op": "UPDATE", "id": victim["id"], "details": json.dumps(telemetry["details"])},
            )
            await connection.execute(
                text(
                    "INSERT INTO audit.audit_outbox "
                    "(event_id, event_type, payload, occurred_at, status, attempts) "
                    "VALUES (gen_random_uuid(), 'audit.tamper_detected', "
                    "CAST(:payload AS jsonb), now(), :status, 0)"
                ),
                {"payload": json.dumps(telemetry), "status": OUTBOX_STATUS_PENDING},
            )

        async with engine.connect() as connection:
            pending = await connection.scalar(
                text("SELECT COUNT(*) FROM audit.audit_outbox WHERE status = :status"),
                {"status": OUTBOX_STATUS_PENDING},
            )
            assert pending == 1

        # The worker path: a poll pass claims the telemetry and fans it out to
        # the logging consumer - telemetry never enters the hash chain.
        async with engine.connect() as connection:
            tables = await discover_outbox_tables(connection, ("audit",))
        assert {table.table_name for table in tables} == {AUDIT_OUTBOX_TABLE}
        for table in tables:
            await process_outbox_table(engine, table, registry, DEFAULT_DISPATCHER_CONFIG)

        async with engine.connect() as connection:
            pending = await connection.scalar(
                text("SELECT COUNT(*) FROM audit.audit_outbox WHERE status = :status"),
                {"status": OUTBOX_STATUS_PENDING},
            )
            assert pending == 0
            delivered = await connection.scalar(
                text(
                    "SELECT COUNT(*) FROM audit.consumed_events "
                    "WHERE event_type = 'audit.tamper_detected'"
                )
            )
            assert delivered == 1
            rows = await _audit_rows(connection)
        assert len(rows) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_partner_gate_events_round_trip_into_the_audit_chain(
    database_url: str, clean_tables: None
) -> None:
    """AC (#256): partner.activated / partner.rejected / partner.credential_reviewed
    each yield a MOD-011 audit-chain append, terminal decisions and credential
    views coexist in one chain, and replaying the same event_id adds no row."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        activated_envelope = partner_activated_envelope(partner_id=5, identity_id=11, decision_by=3)
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO iam.iam_identities (id, phone_e164) VALUES "
                    "(11, '+919876543210'), (12, '+919876543211')"
                )
            )
            # MOD-002-style envelopes exactly as the partner facade publishes.
            await write_outbox(connection, "partner", PARTNER_OUTBOX_TABLE, activated_envelope)
            await write_outbox(
                connection,
                "partner",
                PARTNER_OUTBOX_TABLE,
                partner_rejected_envelope(
                    partner_id=5,
                    identity_id=12,
                    reason="documents did not match the recorded identity",
                    round=1,
                ),
            )
            await write_outbox(
                connection,
                "partner",
                PARTNER_OUTBOX_TABLE,
                credential_reviewed_envelope(partner_id=5, actor_id=3),
            )

        registry = _full_registry()
        async with engine.connect() as connection:
            tables = await discover_outbox_tables(connection, ("partner",))
        assert {table.table_name for table in tables} == {PARTNER_OUTBOX_TABLE}

        for table in tables:
            await process_outbox_table(engine, table, registry, DEFAULT_DISPATCHER_CONFIG)

        async with engine.connect() as connection:
            rows = await _audit_rows(connection)
            assert len(rows) == 3
            event_types = {str(row["event_type"]) for row in rows}
            assert event_types == {
                EVENT_PARTNER_ACTIVATED,
                EVENT_PARTNER_REJECTED,
                EVENT_PARTNER_CREDENTIAL_REVIEWED,
            }
            _verify_chain(rows)

            # Every decision/view is attributed: the operator who acted and the
            # partner acted upon ride the row's actor/target UUIDs.
            activated = next(
                row for row in rows if str(row["event_type"]) == EVENT_PARTNER_ACTIVATED
            )
            reviewed = next(
                row for row in rows if str(row["event_type"]) == EVENT_PARTNER_CREDENTIAL_REVIEWED
            )
        assert activated["actor_id"] is not None
        assert activated["target_id"] is not None
        assert reviewed["actor_id"] is not None
        assert reviewed["target_id"] is not None

        # Replay the activated event_id: the idempotent consumer records the
        # ledger conflict and appends nothing - still exactly three rows.
        await dispatch(registry, activated_envelope)
        async with engine.connect() as connection:
            rows = await _audit_rows(connection)
        assert len(rows) == 3
        _verify_chain(rows)
    finally:
        await engine.dispose()
