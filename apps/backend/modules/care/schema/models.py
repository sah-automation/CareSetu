"""MOD-006: SQLAlchemy models for the ``care`` schema only (ADR-0003).

Table namespace rule (coding-standards S2, T6a checker #26):
every table is prefixed with ``care_`` and lives in
the ``care`` schema. Models are added incrementally
as Phase 8 tickets land.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

MODULE_METADATA = MetaData(schema="care")

#: Canonical vocabulary mirrored by the CHECK constraints below - the single
#: source of truth for the ``care`` namespace. DTO result views in
#: ``care_models.py`` import these frozensets so the DB vocabulary and the
#: typed boundary never drift apart.
STAGE_PRE_SUMMARY = "pre_summary"
STAGE_CONSULT_COMPLETE = "consult_complete"
STAGE_PRESCRIPTION_PENDING = "prescription_pending"
STAGE_CLOSED = "closed"
CANONICAL_STAGES = frozenset(
    {
        STAGE_PRE_SUMMARY,
        STAGE_CONSULT_COMPLETE,
        STAGE_PRESCRIPTION_PENDING,
        STAGE_CLOSED,
    }
)

CLOSE_REASON_PATIENT_WITHDRAWN = "patient_withdrawn"
CLOSE_REASON_DOCTOR_REJECTED = "doctor_rejected"
CLOSE_REASON_NO_SHOW = "no_show"
CLOSE_REASON_DUPLICATE = "duplicate"
CLOSE_REASON_SYSTEM = "system"
CANONICAL_CLOSE_REASONS = frozenset(
    {
        CLOSE_REASON_PATIENT_WITHDRAWN,
        CLOSE_REASON_DOCTOR_REJECTED,
        CLOSE_REASON_NO_SHOW,
        CLOSE_REASON_DUPLICATE,
        CLOSE_REASON_SYSTEM,
    }
)

RX_STATUS_DRAFT = "draft"
RX_STATUS_DOCTOR_REVIEWED = "doctor_reviewed"
RX_STATUS_APPROVED = "approved"
RX_STATUS_REJECTED = "rejected"
RX_STATUS_ISSUED = "issued"
RX_STATUS_FULFILLED = "fulfilled"
CANONICAL_RX_STATUSES = frozenset(
    {
        RX_STATUS_DRAFT,
        RX_STATUS_DOCTOR_REVIEWED,
        RX_STATUS_APPROVED,
        RX_STATUS_REJECTED,
        RX_STATUS_ISSUED,
        RX_STATUS_FULFILLED,
    }
)

RX_SOURCE_AI_DRAFT = "ai_draft"
RX_SOURCE_MANUAL = "manual"
CANONICAL_RX_SOURCES = frozenset({RX_SOURCE_AI_DRAFT, RX_SOURCE_MANUAL})

DECISION_APPROVED = "approved"
DECISION_REJECTED = "rejected"
CANONICAL_DECISIONS = frozenset({DECISION_APPROVED, DECISION_REJECTED})

INPUT_TYPE_VOICE = "voice"
INPUT_TYPE_PHOTO = "photo"
CANONICAL_INPUT_TYPES = frozenset({INPUT_TYPE_VOICE, INPUT_TYPE_PHOTO})

SENSITIVE_CLASS_NORMAL = "normal"
SENSITIVE_CLASS_SENSITIVE = "sensitive"
SENSITIVE_CLASS_RESTRICTED = "restricted"
CANONICAL_SENSITIVE_CLASSES = frozenset(
    {
        SENSITIVE_CLASS_NORMAL,
        SENSITIVE_CLASS_SENSITIVE,
        SENSITIVE_CLASS_RESTRICTED,
    }
)


care_cases = Table(
    "care_cases",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    Column("patient_id", BigInteger, nullable=False),
    Column("doctor_id", BigInteger, nullable=True),
    Column("pre_summary_id", BigInteger, nullable=True),
    Column("stage", String(30), nullable=False, server_default=text("'pre_summary'")),
    Column("closed_at", DateTime(timezone=True), nullable=True),
    Column("close_reason", String(50), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint(
        "stage IN ('pre_summary', 'consult_complete', 'prescription_pending', 'closed')",
        name="ck_care_cases_stage",
    ),
    CheckConstraint(
        "close_reason IS NULL OR close_reason IN ("
        "'patient_withdrawn', 'doctor_rejected', "
        "'no_show', 'duplicate', 'system')",
        name="ck_care_cases_close_reason",
    ),
    Index("ix_care_cases_patient", "patient_id", "created_at"),
    Index("ix_care_cases_doctor", "doctor_id", "stage"),
)


care_prescriptions = Table(
    "care_prescriptions",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    Column(
        "case_id",
        BigInteger,
        ForeignKey("care_cases.id", name="fk_care_prescriptions_case"),
        nullable=False,
    ),
    Column("status", String(30), nullable=False, server_default=text("'draft'")),
    Column("source", String(20), nullable=False, server_default=text("'ai_draft'")),
    Column("attempt_no", Integer, nullable=False, server_default=text("1")),
    Column("draft_snapshot", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("issued_at", DateTime(timezone=True), nullable=True),
    Column("attributed_doctor", BigInteger, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint(
        "status IN ('draft', 'doctor_reviewed', 'approved', 'rejected', 'issued', 'fulfilled')",
        name="ck_care_prescriptions_status",
    ),
    CheckConstraint(
        "source IN ('ai_draft', 'manual')",
        name="ck_care_prescriptions_source",
    ),
    Index("ix_care_prescriptions_case", "case_id"),
)


care_rx_items = Table(
    "care_rx_items",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    Column(
        "prescription_id",
        BigInteger,
        ForeignKey("care_prescriptions.id", name="fk_care_rx_items_prescription"),
        nullable=False,
    ),
    Column("sequence", Integer, nullable=False, server_default=text("1")),
    Column("name", String(200), nullable=False),
    Column("dose", String(100), nullable=True),
    Column("duration", String(100), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Index("ix_care_rx_items_prescription", "prescription_id"),
)


care_rx_approvals = Table(
    "care_rx_approvals",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    Column(
        "prescription_id",
        BigInteger,
        ForeignKey("care_prescriptions.id", name="fk_care_rx_approvals_prescription"),
        nullable=False,
    ),
    Column("doctor_id", BigInteger, nullable=False),
    Column("decision", String(20), nullable=False),
    Column("edited_yn", Boolean, nullable=False, server_default=text("false")),
    Column("reason", Text, nullable=True),
    Column("verification_declaration", Text, nullable=True),
    Column("declared_at", DateTime(timezone=True), nullable=True),
    Column("approved_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint(
        "decision IN ('approved', 'rejected')",
        name="ck_care_rx_approvals_decision",
    ),
    Index("ix_care_rx_approvals_prescription", "prescription_id"),
)


care_doctor_inputs = Table(
    "care_doctor_inputs",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    Column(
        "case_id",
        BigInteger,
        ForeignKey("care_cases.id", name="fk_care_doctor_inputs_case"),
        nullable=False,
    ),
    Column("input_type", String(10), nullable=False),
    Column("media_ref", Text, nullable=False),
    Column("sensitive_class", String(30), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint(
        "input_type IN ('voice', 'photo')",
        name="ck_care_doctor_inputs_input_type",
    ),
    CheckConstraint(
        "sensitive_class IS NULL OR sensitive_class IN ('normal', 'sensitive', 'restricted')",
        name="ck_care_doctor_inputs_sensitive_class",
    ),
    Index("ix_care_doctor_inputs_case", "case_id"),
)


from bus.outbox_ddl import outbox_table  # noqa: E402

care_outbox = outbox_table("care_outbox", "care", MODULE_METADATA)
