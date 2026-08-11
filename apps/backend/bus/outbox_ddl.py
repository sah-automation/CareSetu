"""Outbox + consumed_events DDL template (PHASE-1 T1b, ticket #18).

The transactional-outbox async seam (ADR-0002) uses a shared, versioned table
shape: each module materializes its own ``<module>_outbox`` table and its own
``consumed_events`` ledger, both in its own private schema (ADR-0003). This
module is the single source of that shape so the round-trip harness (T2c) and
later module migrations (Phase 2+) materialize identical tables.

Outbox row contract (issue #16): ``id`` (UUID PK), ``event_id``,
``event_type``, ``payload`` (JSONB), ``occurred_at``, ``status``, ``attempts``,
``next_attempt_at``. The status machine is ``pending -> inflight``; only the
dispatcher moves a row out of ``pending``. A row whose fan-out fully succeeds is
deleted - delete-on-success per ADR-0002, no tombstone, the subscriber's
``consumed_events`` ledger is the delivery record. A partial fan-out returns the
row to ``pending`` on an exponential-backoff schedule and, once ``attempts``
reaches the cap, ``dead_letter`` is terminal.

Ledger contract: ``event_id`` (UUID PK), ``event_type``, ``processed_at``,
``handler_result``. It lives with the subscriber in its own schema, never
shared across modules.
"""

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.ext.asyncio import AsyncConnection

OUTBOX_STATUSES: tuple[str, ...] = (
    "pending",
    "inflight",
    "dead_letter",
)

OUTBOX_STATUS_PENDING = "pending"
OUTBOX_STATUS_INFLIGHT = "inflight"
OUTBOX_STATUS_DEAD_LETTER = "dead_letter"

_OUTBOX_STATUS_LIST = ", ".join(f"'{status}'" for status in OUTBOX_STATUSES)


def outbox_table(table_name: str, schema: str) -> Table:
    """Build the transactional-outbox ``Table`` for ``schema``."""
    metadata = MetaData()
    return Table(
        table_name,
        metadata,
        Column(
            "id",
            PgUUID(as_uuid=True),
            primary_key=True,
            server_default=text("gen_random_uuid()"),
        ),
        Column("event_id", PgUUID(as_uuid=True), nullable=False),
        Column("event_type", String(100), nullable=False),
        Column("payload", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
        Column("occurred_at", DateTime(timezone=True), nullable=False),
        Column("status", String(20), nullable=False, server_default=OUTBOX_STATUS_PENDING),
        Column("attempts", Integer, nullable=False, server_default=text("0")),
        Column("next_attempt_at", DateTime(timezone=True), nullable=True),
        CheckConstraint(
            f"status IN ({_OUTBOX_STATUS_LIST})",
            name=f"ck_{table_name}_status",
        ),
        Index(f"ix_{table_name}_poll", "status", "next_attempt_at"),
        schema=schema,
    )


def consumed_events_table(schema: str) -> Table:
    """Build the idempotent-subscriber ``consumed_events`` ``Table`` for ``schema``."""
    metadata = MetaData()
    return Table(
        "consumed_events",
        metadata,
        Column("event_id", PgUUID(as_uuid=True), primary_key=True),
        Column("event_type", String(100), nullable=False),
        Column("processed_at", DateTime(timezone=True), nullable=False),
        Column("handler_result", JSON, nullable=True),
        schema=schema,
    )


async def materialize_outbox(connection: AsyncConnection, schema: str, table_name: str) -> None:
    """Create the outbox table in ``schema``, no-op if it already exists."""
    table = outbox_table(table_name, schema)
    await connection.run_sync(table.create, checkfirst=True)


async def materialize_consumed_events(connection: AsyncConnection, schema: str) -> None:
    """Create the ``consumed_events`` ledger in ``schema``, no-op if it exists."""
    table = consumed_events_table(schema)
    await connection.run_sync(table.create, checkfirst=True)
