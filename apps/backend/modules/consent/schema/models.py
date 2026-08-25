"""MOD-004: SQLAlchemy models for the ``consent`` schema only (ADR-0003).

Table namespace rule (coding-standards §2, T6a checker #26): every table is
prefixed with ``consent_`` and lives in the ``consent`` schema. PHASE-3 T3
(#212) lands the consent-schema core: ``consent_consents`` - one row per
grant lineage, the unique ``(patient_id, counterparty_type, counterparty_id,
record_scope)`` key IS the lineage identity and carries status + version -
and ``consent_events``, the immutable lifecycle ledger (requested/granted/
revoked/declined, append-only: versions never rewrite once terminal). The
transactional outbox mirrors the shared ``bus/outbox_ddl.py`` shape (single
source of truth, ADR-0002); ``consent.consumed_events`` is deferred until
the module's first subscription arrives (MOD-003 consumes ``consent.*``
from T5 on), so this metadata declares no subscriber ledger.
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

MODULE_METADATA = MetaData(schema="consent")


consent_consents = Table(
    "consent_consents",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    # The patient who owns the lineage; identity ids come from MOD-001 via
    # the gateway principal. No cross-schema FK (ADR-0003 module isolation).
    Column("patient_id", BigInteger, nullable=False),
    # Phase 3 carries whatever caller-supplied reference the patient names;
    # directory resolution replaces free text in later phases.
    Column("counterparty_type", String(20), nullable=False),
    Column("counterparty_id", Text, nullable=False),
    Column("record_scope", String(30), nullable=False),
    # status + version ARE the lineage state; version counts grants minted
    # inside the lineage (0 = requested/declined, never granted).
    Column("status", String(20), nullable=False),
    Column("version", BigInteger, nullable=False, server_default=text("0")),
    # Human lineage reference C-YYYY-NNN minted at insert from the row id;
    # briefly NULL inside the creating transaction (NULLs never collide in a
    # unique index, so concurrent creations of different triples are safe).
    Column("lineage_ref", String(24), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint(
        "counterparty_type IN ('doctor', 'lab', 'chemist')",
        name="ck_consent_consents_counterparty_type",
    ),
    CheckConstraint(
        "record_scope IN ('consultations', 'prescriptions', 'lab_results', 'metrics', "
        "'full_record')",
        name="ck_consent_consents_record_scope",
    ),
    CheckConstraint(
        "status IN ('requested', 'granted', 'revoked', 'declined')",
        name="ck_consent_consents_status",
    ),
    CheckConstraint("version >= 0", name="ck_consent_consents_version"),
    UniqueConstraint(
        "patient_id",
        "counterparty_type",
        "counterparty_id",
        "record_scope",
        name="uq_consent_consents_lineage",
    ),
    UniqueConstraint("lineage_ref", name="uq_consent_consents_lineage_ref"),
    Index("ix_consent_consents_patient_log", "patient_id", text("updated_at DESC")),
)


consent_events = Table(
    "consent_events",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    Column(
        "consent_id",
        BigInteger,
        ForeignKey("consent_consents.id", name="fk_consent_events_consent"),
        nullable=False,
    ),
    Column("kind", String(20), nullable=False),
    Column("version", BigInteger, nullable=False, server_default=text("0")),
    Column("actor_patient_id", BigInteger, nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint(
        "kind IN ('requested', 'granted', 'revoked', 'declined')",
        name="ck_consent_events_kind",
    ),
    Index("ix_consent_events_lineage", "consent_id", text("occurred_at DESC"), text("id DESC")),
)


consent_outbox = outbox_table("consent_outbox", "consent", MODULE_METADATA)


consent_egress_log = Table(
    "consent_egress_log",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    Column("patient_id", BigInteger, nullable=False),
    Column("consent_id", BigInteger, nullable=False),
    Column("lineage_ref", String(24), nullable=False),
    Column("version", BigInteger, nullable=False),
    Column("counterparty_type", String(20), nullable=False),
    Column("counterparty_id", Text, nullable=False),
    Column("record_scope", String(30), nullable=False),
    Column("disclosed_entry_ids", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("disclosed_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint(
        "counterparty_type IN ('doctor', 'lab', 'chemist')",
        name="ck_consent_egress_log_counterparty_type",
    ),
    CheckConstraint(
        "record_scope IN ('consultations', 'prescriptions', 'lab_results', 'metrics', "
        "'full_record')",
        name="ck_consent_egress_log_record_scope",
    ),
    Index("ix_consent_egress_log_patient", "patient_id", text("disclosed_at DESC")),
    Index("ix_consent_egress_log_consent", "consent_id", text("disclosed_at DESC")),
)
