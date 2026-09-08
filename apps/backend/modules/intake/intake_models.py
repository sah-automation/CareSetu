"""Result models for intake facade (PHASE-7 T07, ticket #351)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel


class MediaFile(BaseModel):
    """A raw recorded clip handed to ``upload_intake_media`` (PHASE-7 T08).

    ``data`` is the unencrypted audio bytes; the facade encrypts them at rest
    (security-phii-standards, audio = PHI) before they touch disk. ``filename``
    is the client's original name (retained for diagnostics only); the object
    key on disk is a server-generated opaque name under the ``intake/`` prefix.
    ``record_attempt`` is the B3-ladder attempt this clip belongs to (1-based);
    the facade echoes it onto the returned :class:`MediaUploadRef`.
    """

    data: bytes
    filename: str = "recording.webm"
    media_type: str = "audio"
    audio_duration_ms: int | None = None
    file_size_bytes: int | None = None
    record_attempt: int = 1


class MediaUploadRef(BaseModel):
    """The opaque clip ticket returned by ``upload_intake_media``.

    Records where the clip lives (``object_key`` under the ``intake/`` prefix),
    its type/duration/size, and which record attempt it belongs to. The clip is
    stored durably at upload time; the ticket is attached to an intake later
    (``submit_intake`` for a first take, ``re_record_intake`` for a retry),
    which persists the ``intake_media_refs`` row against the intake's FK.
    """

    object_key: str
    media_type: str
    audio_duration_ms: int | None
    file_size_bytes: int | None
    record_attempt: int


class ReRecordResult(BaseModel):
    """The outcome of ``re_record_intake``.

    ``accepted`` is True when a fresh recording was attached and the intake
    moved back to structuring (attempt +1, ``intake.retry_requested`` emitted);
    False when the attempt cap was already hit and the intake was routed to the
    forced-text path so the patient is never stuck. When ``accepted`` is True,
    ``status`` is ``structuring`` and ``record_attempts`` reflects the new
    count; when False, ``status`` is ``ready_for_review``, ``forced_text`` is
    True, and no retry event was emitted.
    """

    intake_id: int
    accepted: bool
    status: str
    record_attempts: int
    forced_text: bool
    media_ref_id: int | None = None


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
