"""PHASE-7 T01 (#345): intake schema storage surface.

Asserts the SQLAlchemy models expose the table/column surface the Phase 7
intake feature needs, by introspecting the in-memory Table objects (no
database needed): the closed mode/language/status enums, the JSONB structured
fields, and the attempt counters across intakes, pre_summaries, ai_jobs and
media_refs. Mirrors the partner-directory lockstep-test convention.
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Table

from modules.intake.schema.models import (
    MODULE_METADATA,
    intake_ai_jobs,
    intake_intakes,
    intake_media_refs,
    intake_pre_summaries,
)


def _constraint_text(table: Table, name: str) -> str:
    constraints = [
        c for c in table.constraints if isinstance(c, CheckConstraint) and c.name == name
    ]
    assert constraints, f"{table.name} missing CHECK constraint {name}"
    return str(constraints[0].sqltext)


def test_intakes_is_registered_in_intake_schema() -> None:
    table = MODULE_METADATA.tables.get("intake.intake_intakes")
    assert table is not None
    assert table.schema == "intake"
    for column in (
        "patient_id",
        "mode",
        "language",
        "status",
        "record_attempts",
        "text",
        "transcript",
        "transcript_usability",
        "forced_text",
        "created_at",
        "updated_at",
    ):
        assert column in table.c
    assert "id" in table.primary_key.columns


def test_intakes_mode_language_status_checks() -> None:
    assert "'voice'" in _constraint_text(intake_intakes, "ck_intake_intakes_mode")
    assert "'text'" in _constraint_text(intake_intakes, "ck_intake_intakes_mode")
    assert "'hi'" in _constraint_text(intake_intakes, "ck_intake_intakes_language")
    assert "'en'" in _constraint_text(intake_intakes, "ck_intake_intakes_language")
    statuses = _constraint_text(intake_intakes, "ck_intake_intakes_status")
    for value in ("captured", "structuring", "ready_for_review", "re_record", "failed"):
        assert f"'{value}'" in statuses


def test_intakes_record_attempts_counter() -> None:
    assert intake_intakes.c.record_attempts.nullable is False
    assert intake_intakes.c.record_attempts.server_default is not None


def test_pre_summaries_is_registered_with_jsonb_and_attempts() -> None:
    table = MODULE_METADATA.tables.get("intake.intake_pre_summaries")
    assert table is not None
    assert table.schema == "intake"
    assert "structured_fields" in table.c
    assert "structuring_confidence" in table.c
    assert "low_confidence" in table.c
    assert "review_state" in table.c
    assert "patient_edits" in table.c
    assert "doctor_corrections" in table.c
    assert "review_attribution" in table.c
    assert "reviewed_at" in table.c
    assert not intake_pre_summaries.c.structured_fields.nullable


def test_pre_summaries_review_state_check() -> None:
    states = _constraint_text(intake_pre_summaries, "ck_intake_pre_summaries_review_state")
    for value in ("draft", "review_required", "reviewed", "final"):
        assert f"'{value}'" in states


def test_ai_jobs_is_registered_with_cost_fields() -> None:
    table = MODULE_METADATA.tables.get("intake.intake_ai_jobs")
    assert table is not None
    assert table.schema == "intake"
    for column in (
        "intake_id",
        "task_type",
        "provider",
        "model",
        "input_tokens",
        "output_tokens",
        "cost_paise",
        "status",
        "error_message",
        "confidence",
        "duration_ms",
        "attempts",
    ):
        assert column in table.c
    task_types = _constraint_text(intake_ai_jobs, "ck_intake_ai_jobs_task_type")
    for value in ("transcribe", "structure", "draft", "summarize"):
        assert f"'{value}'" in task_types
    assert intake_ai_jobs.c.attempts.nullable is False


def test_media_refs_is_registered() -> None:
    table = MODULE_METADATA.tables.get("intake.intake_media_refs")
    assert table is not None
    assert table.schema == "intake"
    for column in (
        "intake_id",
        "media_type",
        "object_key",
        "audio_duration_ms",
        "file_size_bytes",
        "record_attempt",
    ):
        assert column in table.c
    assert "'audio'" in _constraint_text(intake_media_refs, "ck_intake_media_refs_media_type")
    assert "'photo'" in _constraint_text(intake_media_refs, "ck_intake_media_refs_media_type")


def test_intake_outbox_is_registered() -> None:
    table = MODULE_METADATA.tables.get("intake.intake_outbox")
    assert table is not None
    assert table.schema == "intake"
    for column in ("event_id", "event_type", "payload", "occurred_at", "status", "attempts"):
        assert column in table.c
    assert "id" in table.primary_key.columns
