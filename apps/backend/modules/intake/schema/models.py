"""MOD-005: SQLAlchemy models for the ``intake`` schema only (ADR-0003).

Table namespace rule (coding-standards §2, T6a checker #26):
every table is prefixed with ``intake_`` and lives in
the ``intake`` schema. PHASE-7 T01 (#345) lands the storage
foundation the symptom intake and AI orchestration module builds on:
``intake_intakes`` (mode, language, status, record attempts, text,
transcript, transcript-usability, forced-text, timestamps),
``intake_pre_summaries`` (structured fields JSONB, confidence,
low-confidence, review state, patient edits, doctor corrections, review
attribution + timestamp), ``intake_ai_jobs`` (task type, provider, model,
tokens, cost paise, status, error, confidence, duration, attempts),
``intake_media_refs`` (audio duration, size, record attempt), and the
module's transactional outbox + consumed-events ledger. The transactional
outbox mirrors the shared ``bus/outbox_ddl.py`` shape (single source of
truth, ADR-0002); the ``consumed_events`` subscriber ledger lives in the
same schema but is materialized only by the migration and addressed
through ``bus.outbox_ddl.consumed_events_table``, never this metadata (its
name carries no module prefix by shared contract).
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
    Numeric,
    String,
    Table,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from bus.outbox_ddl import outbox_table

MODULE_METADATA = MetaData(schema="intake")


intake_intakes = Table(
    "intake_intakes",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    # The owning patient identity from MOD-001. No cross-schema FK -
    # identity ids are gateway principals (ADR-0003 module isolation).
    Column("patient_id", BigInteger, nullable=False),
    # voice or text intake mode (FEAT-006)
    Column("mode", String(10), nullable=False),
    # Hindi or English (REQ-006)
    Column("language", String(5), nullable=False),
    # Intake lifecycle: captured -> structuring -> ready_for_review |
    # re_record | failed (FEAT-006, NFR-PERF-002)
    Column("status", String(30), nullable=False, server_default=text("'captured'")),
    # Auto-retry counter for voice uploads (NFR-PERF-002)
    Column("record_attempts", Integer, nullable=False, server_default=text("0")),
    # Free-text input (text mode) or transcript after ASR
    Column("text", Text, nullable=True),
    Column("transcript", Text, nullable=True),
    # ASR quality flag: usable | partial | unusable
    Column("transcript_usability", String(20), nullable=True),
    # Forced-text flag: when voice fails too many times, patient is
    # switched to text input (FEAT-006 re-record rule)
    Column("forced_text", Boolean, nullable=False, server_default=text("false")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint(
        "mode IN ('voice', 'text')",
        name="ck_intake_intakes_mode",
    ),
    CheckConstraint(
        "language IN ('hi', 'en')",
        name="ck_intake_intakes_language",
    ),
    CheckConstraint(
        "status IN ('captured', 'structuring', 'ready_for_review', 're_record', 'failed')",
        name="ck_intake_intakes_status",
    ),
    CheckConstraint(
        "transcript_usability IS NULL OR transcript_usability IN ('usable', 'partial', 'unusable')",
        name="ck_intake_intakes_transcript_usability",
    ),
    Index("ix_intake_intakes_patient", "patient_id", "created_at"),
)


intake_pre_summaries = Table(
    "intake_pre_summaries",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    Column(
        "intake_id",
        BigInteger,
        ForeignKey("intake_intakes.id", name="fk_intake_pre_summaries_intake"),
        nullable=False,
    ),
    # Structured clinical fields from LLM (EXT-002): symptoms, duration,
    # severity, history, medications, allergies - JSONB for flexibility
    Column("structured_fields", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    # LLM confidence score (0-1, AMB-006 threshold)
    Column("structuring_confidence", Numeric(5, 4), nullable=True),
    # Low-confidence flag: when below threshold forces doctor review (never a state)
    Column("low_confidence", Boolean, nullable=False, server_default=text("false")),
    # Review lifecycle: draft -> reviewed -> final (three states, never a fourth)
    # (FEAT-007)
    Column("review_state", String(20), nullable=False, server_default=text("'draft'")),
    # Patient's edits to the structured summary (FEAT-007)
    Column("patient_edits", JSONB, nullable=True),
    # Doctor's corrections after review (FEAT-007)
    Column("doctor_corrections", JSONB, nullable=True),
    # Who reviewed: patient | doctor | system
    Column("review_attribution", String(40), nullable=True),
    # The reviewing doctor's identity (MOD-001 gateway principal). No
    # cross-schema FK - identity ids are gateway principals (ADR-0003).
    # Null until an attributed doctor review is recorded; persists the specific
    # doctor behind ``review_attribution`` so reviews are attributable (US-22).
    Column("reviewed_by", BigInteger, nullable=True),
    Column("reviewed_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint(
        "review_state IN ('draft', 'reviewed', 'final')",
        name="ck_intake_pre_summaries_review_state",
    ),
    CheckConstraint(
        "review_attribution IS NULL OR review_attribution IN ('patient', 'doctor', 'system')",
        name="ck_intake_pre_summaries_review_attribution",
    ),
    Index("ix_intake_pre_summaries_intake", "intake_id"),
)


intake_ai_jobs = Table(
    "intake_ai_jobs",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    Column(
        "intake_id",
        BigInteger,
        ForeignKey("intake_intakes.id", name="fk_intake_ai_jobs_intake"),
        nullable=False,
    ),
    # Task type: transcribe | structure | draft | summarize
    Column("task_type", String(30), nullable=False),
    # Provider: openai | google | etc.
    Column("provider", String(30), nullable=False),
    # Model identifier
    Column("model", String(50), nullable=False),
    # Token usage tracking (NFR-001 budget meter)
    Column("input_tokens", Integer, nullable=True),
    Column("output_tokens", Integer, nullable=True),
    # Cost in paise (NFR-001, NFR-COST-001)
    Column("cost_paise", Integer, nullable=True),
    # Job lifecycle: pending -> running -> completed | failed | timeout
    Column("status", String(20), nullable=False, server_default=text("'pending'")),
    # Error details on failure
    Column("error_message", Text, nullable=True),
    # LLM output confidence (0-1)
    Column("confidence", Numeric(5, 4), nullable=True),
    # Duration in milliseconds
    Column("duration_ms", Integer, nullable=True),
    # Retry counter (≤ 3 retries per ADR-0002 / NFR-PERF-003)
    Column("attempts", Integer, nullable=False, server_default=text("0")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint(
        "task_type IN ('transcribe', 'structure', 'draft', 'summarize')",
        name="ck_intake_ai_jobs_task_type",
    ),
    CheckConstraint(
        "status IN ('pending', 'running', 'completed', 'failed', 'timeout')",
        name="ck_intake_ai_jobs_status",
    ),
    Index("ix_intake_ai_jobs_intake", "intake_id", "task_type"),
)


intake_media_refs = Table(
    "intake_media_refs",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    Column(
        "intake_id",
        BigInteger,
        ForeignKey("intake_intakes.id", name="fk_intake_media_refs_intake"),
        nullable=False,
    ),
    # audio or photo
    Column("media_type", String(10), nullable=False),
    # Object storage key under intake/ prefix (security-phii-standards)
    Column("object_key", Text, nullable=False),
    # Audio-specific: duration in milliseconds
    Column("audio_duration_ms", Integer, nullable=True),
    # File size for upload validation / cost metering
    Column("file_size_bytes", BigInteger, nullable=True),
    # Which record attempt this media belongs to (auto-retry tracking)
    Column("record_attempt", Integer, nullable=False, server_default=text("1")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint(
        "media_type IN ('audio', 'photo')",
        name="ck_intake_media_refs_media_type",
    ),
    Index("ix_intake_media_refs_intake", "intake_id"),
)


intake_outbox = outbox_table("intake_outbox", "intake", MODULE_METADATA)
