"""MOD-003: SQLAlchemy models for the ``health`` schema only (ADR-0003).

Table namespace rule (coding-standards §2, T6a checker #26): every table is
prefixed with ``health_`` and lives in the ``health`` schema. PHASE-3 T2
(#211) lands the longitudinal-record core: one ``health_patient_records``
shell per patient identity (created on ``patient.registered``), the clinical
``health_record_entries`` attached to it by later phases' events, and the
``health_record_access_history`` ledger that records EVERY read attempt -
owner reads included - feeding FEAT-003's trust view. The transactional
outbox mirrors the shared ``bus/outbox_ddl.py`` shape (single source of
truth, ADR-0002); the ``consumed_events`` subscriber ledger lives in the
same schema but is materialized only by the migration and addressed through
``bus.outbox_ddl.consumed_events_table``, never this metadata (its name
carries no module prefix by shared contract).
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from bus.outbox_ddl import outbox_table

MODULE_METADATA = MetaData(schema="health")


health_patient_records = Table(
    "health_patient_records",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    Column("identity_id", BigInteger, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    # One shell per patient identity - the unique index is the concurrency
    # arbiter that makes subscriber replay and lazy ensure idempotent.
    UniqueConstraint("identity_id", name="uq_health_patient_records_identity"),
)

# Initial entry vocabulary; later filing phases extend it by additive migration
# (roadmap PHASE-3 §2 deferred items: prescriptions/reports/metrics/settlements).
health_record_entries = Table(
    "health_record_entries",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    Column(
        "record_id",
        BigInteger,
        ForeignKey("health_patient_records.id", name="fk_health_record_entries_record"),
        nullable=False,
    ),
    Column("entry_type", String(40), nullable=False),
    Column("payload", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint(
        "entry_type IN ('consultation', 'prescription', 'lab_report', 'metric', 'settlement')",
        name="ck_health_record_entries_entry_type",
    ),
    Index("ix_health_record_entries_timeline", "record_id", text("occurred_at DESC")),
)

health_record_access_history = Table(
    "health_record_access_history",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    Column(
        "record_id",
        BigInteger,
        ForeignKey("health_patient_records.id", name="fk_health_record_access_history_record"),
        nullable=False,
    ),
    # The caller whose read attempt this row records; denials name who tried.
    # Every read arrives behind the gateway, so the accessor is always known.
    Column("accessor_identity_id", BigInteger, nullable=False),
    Column("outcome", String(20), nullable=False),
    Column("accessed_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    # PHASE-4 T7 (#241): actor_type / scope / denial_reason join the ledger so
    # the patient access-history view answers FEAT-003's "who / how / why"
    # from the fast health ledger alone. NULLABLE because rows written before
    # the enrichment migration have no values; ``_log_access`` populates them
    # on every fresh write (additive migration v3.1). actor_type is pinned to
    # the counterparty vocabulary; scope deliberately is not - denied attempts
    # record caller-supplied scopes the consent gate fails closed against.
    Column("actor_type", String(20), nullable=True),
    Column("scope", String(40), nullable=True),
    Column("denial_reason", Text, nullable=True),
    CheckConstraint(
        "outcome IN ('allowed', 'denied')",
        name="ck_health_record_access_history_outcome",
    ),
    CheckConstraint(
        "actor_type IN ('patient', 'doctor', 'lab', 'chemist')",
        name="ck_health_record_access_history_actor_type",
    ),
    Index("ix_health_record_access_history_record", "record_id", text("accessed_at DESC")),
)

health_outbox = outbox_table("health_outbox", "health", MODULE_METADATA)
