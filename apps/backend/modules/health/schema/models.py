"""MOD-003: SQLAlchemy models for the ``health`` schema only (ADR-0003).

Table namespace rule (coding-standards §2, T6a checker #26): every table is
prefixed with ``health_`` and lives in the ``health`` schema. PHASE-3 T2
(#211) lands the longitudinal-record core: one ``health_patient_records``
shell per patient identity (created on ``patient.registered``), the clinical
``health_record_entries`` attached to it by later phases' events, and the
``health_record_access_history`` ledger that records counterparty read
attempts - partner reads and denied attempts, never the owner's own reads
(#665) - feeding FEAT-003's trust view. The transactional
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
    Numeric,
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

# The patient-authored health background snapshot (#534, US-21/US-22, ADR-0018).
# One row per patient identity, distinct from care-generated ``health_record_entries``:
# the patient fills it once and edits it, and the first acknowledged save records a
# ``health_background`` consent grant to every live-relationship doctor. ``acknowledged_at``
# is set exactly once, on that first flagged save; later edits never touch it. The list
# fields are JSONB arrays (empty by default) so the snapshot contract can evolve additively
# without a migration per new field. Height/weight time series are a separate table (ticket
# outside this one's scope).
health_background_snapshots = Table(
    "health_background_snapshots",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    # Patient identity id - no cross-schema FK (ADR-0003); the unique index is
    # the upsert arbiter that makes repeat saves converge on the one row.
    Column("identity_id", BigInteger, nullable=False),
    Column("acknowledged_at", DateTime(timezone=True), nullable=True),
    Column("blood_group", String(16), nullable=True),
    Column("conditions", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("allergies", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("medications", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("immunizations", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("family_history", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("identity_id", name="uq_health_background_snapshots_identity"),
)

# The height/weight time series the patient appends next to the snapshot (#535, US-23).
# One row per measurement, keyed to the patient identity (like the snapshot, never a
# cross-schema FK); append-only on this surface - no UPDATE/DELETE in v1, so a trend view
# can extend naturally. ``recorded_at`` is the patient-authored measurement timestamp (the
# trend anchor); the series read orders newest-first on ``(recorded_at, id)``. The range
# CHECKs mirror the API-boundary validation so a non-API writer cannot store an absurd
# value; at least one of the two values must be present (an empty row carries nothing).
health_background_metrics = Table(
    "health_background_metrics",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    # Patient identity id - no cross-schema FK (ADR-0003).
    Column("identity_id", BigInteger, nullable=False),
    Column("height_cm", Numeric(5, 1), nullable=True),
    Column("weight_kg", Numeric(5, 2), nullable=True),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint(
        "height_cm IS NULL OR (height_cm >= 30 AND height_cm <= 250)",
        name="ck_health_background_metrics_height_cm",
    ),
    CheckConstraint(
        "weight_kg IS NULL OR (weight_kg >= 1 AND weight_kg <= 500)",
        name="ck_health_background_metrics_weight_kg",
    ),
    CheckConstraint(
        "height_cm IS NOT NULL OR weight_kg IS NOT NULL",
        name="ck_health_background_metrics_has_value",
    ),
    Index(
        "ix_health_background_metrics_series",
        "identity_id",
        text("recorded_at DESC"),
        text("id DESC"),
    ),
)


health_outbox = outbox_table("health_outbox", "health", MODULE_METADATA)
