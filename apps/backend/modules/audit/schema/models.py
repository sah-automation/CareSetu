"""MOD-011: SQLAlchemy models for the ``audit`` schema only (ADR-0003).

Table namespace rule (coding-standards §2, T6a checker #26):
every table is prefixed with ``audit_`` and lives in
the ``audit`` schema. Models are added incrementally
as Phase 2 tickets land.

PHASE-4 T1 (#235): ``audit_events`` is the append-only, hash-chained
audit ledger covering all regulated acts. ``tamper_attempts`` records
any defense-in-depth UPDATE/DELETE attempts that bypass REVOKE.
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Column, DateTime, Index, MetaData, Table, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID

from bus.outbox_ddl import consumed_events_table, outbox_table

MODULE_METADATA = MetaData(schema="audit")


audit_identities = Table(
    "audit_identities",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
)


audit_events = Table(
    "audit_events",
    MODULE_METADATA,
    Column(
        "id",
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    ),
    Column("event_type", Text, nullable=False),
    Column("actor_id", PgUUID(as_uuid=True), nullable=True),
    Column("target_id", PgUUID(as_uuid=True), nullable=True),
    Column("scope", Text, nullable=True),
    Column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("timestamp", DateTime(timezone=True), nullable=False),
    Column("prev_hash", Text, nullable=False),
    Column("hash", Text, nullable=False),
    Index("ix_audit_events_timestamp", "timestamp"),
    Index("ix_audit_events_actor", "actor_id", "timestamp"),
    Index("ix_audit_events_target", "target_id", "timestamp"),
    Index("ix_audit_events_type", "event_type", "timestamp"),
)


audit_tamper_attempts = Table(
    "audit_tamper_attempts",
    MODULE_METADATA,
    Column(
        "id",
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    ),
    Column("attempted_at", DateTime(timezone=True), nullable=False),
    Column("attempted_operation", Text, nullable=False),
    Column("target_event_id", PgUUID(as_uuid=True), nullable=True),
    Column("attempted_by", PgUUID(as_uuid=True), nullable=True),
    Column("details", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
)


audit_outbox = outbox_table("audit_outbox", "audit", MODULE_METADATA)
audit_consumed_events = consumed_events_table("audit")
