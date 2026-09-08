"""Result models for intake facade (PHASE-7 T07, ticket #351)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel


class MediaRefView(BaseModel):
    """A media reference attached to an intake."""

    media_ref_id: int
    media_type: str
    object_key: str
    audio_duration_ms: int | None
    file_size_bytes: int | None
    record_attempt: int


class IntakeSubmitResult(BaseModel):
    """The outcome of submit_intake.

    ``intake_id`` names the freshly captured intake; ``status`` is always
    ``captured`` at this point (the AI pipeline runs asynchronously).
    The intake row and ``intake.captured`` outbox event are committed in
    the same transaction (ADR-0002 S1, spec #344).
    """

    intake_id: int
    status: str


class IntakeDetailView(BaseModel):
    """The read projection returned by get_intake.

    Carries the intake lifecycle fields, transcript, media refs, and
    status from the state machine. Patient-scoped: the facade enforces
    that the caller owns the intake.
    """

    intake_id: int
    patient_id: int
    mode: str
    language: str
    status: str
    record_attempts: int
    text: str | None
    transcript: str | None
    transcript_usability: str | None
    forced_text: bool
    media_refs: list[MediaRefView]
    created_at: datetime
    updated_at: datetime


class PreSummaryView(BaseModel):
    """The read projection returned by get_pre_summary.

    Carries the draft structured fields, structuring confidence, the
    low_confidence honesty flag, review state, patient edits, and the
    review attribution/timestamp. The ``low_confidence`` field is the
    honesty cue: when True the UI shows "AI draft - doctor will verify"
    (AMB-006, spec #344).
    """

    pre_summary_id: int
    intake_id: int
    structured_fields: dict[str, Any]
    structuring_confidence: Decimal | float | None
    low_confidence: bool
    review_state: str
    patient_edits: dict[str, Any] | None
    doctor_corrections: dict[str, Any] | None
    review_attribution: str | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime
