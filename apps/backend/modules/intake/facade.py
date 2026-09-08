"""MOD-005 Intake workflows: typed public sync API (PHASE-7 T07, #351).

The only legal cross-module import target for the ``intake`` module
(coding-standards S2, ADR-0003). Thin coordinator that validates intake
submissions, commits the intake row + outbox event in one transaction
(ADR-0002 S1), and provides read projections for intake and pre-summary
data. ``request_rx_draft`` is declared as a contract stub only (verified
in Phase 8).

Capture durability is structural: the row + outbox event commit in one
local transaction, so a later AI failure never rolls back the intake
(spec #344, acceptance criterion 5).
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from bus.outbox_writer import write_outbox
from modules.intake.domain.events import intake_captured_envelope
from modules.intake.domain.exceptions import (
    IntakeNotFoundError,
    IntakeValidationError,
)
from modules.intake.domain.state_machine import (
    CAPTURED,
    MAX_TEXT_LENGTH,
)
from modules.intake.intake_models import (
    IntakeDetailView,
    IntakeSubmitResult,
    MediaRefView,
    PreSummaryView,
)
from modules.intake.outbox import INTAKE_OUTBOX_TABLE
from modules.intake.schema.models import (
    intake_intakes,
    intake_media_refs,
    intake_pre_summaries,
)

INTAKE_SCHEMA = "intake"


class IntakeFacade:
    """Typed public facade for intake capture and read projections.

    Takes the engine in its constructor, mirroring the partner facade
    convention. Enforces one-mode-per-intake and the text cap (2000 chars)
    server-side with typed errors.
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def submit_intake(
        self,
        *,
        patient_id: int,
        mode: Literal["voice", "text"],
        language: Literal["hi", "en"],
        text: str | None = None,
        media_ref_id: int | None = None,
    ) -> IntakeSubmitResult:
        """Capture a symptom intake and emit ``intake.captured`` atomically.

        Validates one-mode-per-intake: exactly one of ``text`` or
        ``media_ref_id`` must be provided, matching the declared ``mode``.
        Enforces the text cap (``MAX_TEXT_LENGTH`` = 2000 chars). Commits
        the intake row and the ``intake.captured`` outbox event in the SAME
        transaction (ADR-0002 S1) so a crash between state change and
        dispatch cannot lose the event. The voice-attempt cap (3 attempts)
        is enforced by the domain state machine at the re-record seam
        (``MAX_RECORD_ATTEMPTS``, PHASE-7 T02) - a fresh capture always
        begins at record attempt 1.

        Raises :class:`IntakeValidationError` on validation failure.
        """
        if mode == "text":
            if media_ref_id is not None:
                raise IntakeValidationError("text mode intake must not include a media reference")
            if text is None:
                raise IntakeValidationError("text mode intake requires text content")
            if len(text) > MAX_TEXT_LENGTH:
                raise IntakeValidationError(
                    f"text exceeds {MAX_TEXT_LENGTH} character cap ({len(text)} chars)"
                )
        elif mode == "voice":
            if text is not None:
                raise IntakeValidationError("voice mode intake must not include text content")
            if media_ref_id is None:
                raise IntakeValidationError("voice mode intake requires a media reference")

        async with self._engine.begin() as connection:
            state = CAPTURED
            result = await connection.execute(
                intake_intakes.insert()
                .values(
                    patient_id=patient_id,
                    mode=mode,
                    language=language,
                    status=state.status.value,
                    record_attempts=state.record_attempts,
                    text=text,
                    forced_text=state.forced_text,
                )
                .returning(intake_intakes.c.id)
            )
            intake_id = int(result.scalar_one())

            envelope = intake_captured_envelope(intake_id=intake_id)
            await write_outbox(
                connection,
                INTAKE_SCHEMA,
                INTAKE_OUTBOX_TABLE,
                envelope,
            )

        return IntakeSubmitResult(
            intake_id=intake_id,
            status=state.status.value,
        )

    async def get_intake(
        self,
        *,
        intake_id: int,
        patient_id: int,
    ) -> IntakeDetailView:
        """Read an intake with transcript, media refs, and status.

        Patient-scoped: the facade enforces that the caller owns the
        intake. Raises :class:`IntakeNotFoundError` when no row matches
        the given intake_id + patient_id pair.
        """
        async with self._engine.begin() as connection:
            row = (
                await connection.execute(
                    select(intake_intakes).where(
                        intake_intakes.c.id == intake_id,
                        intake_intakes.c.patient_id == patient_id,
                    )
                )
            ).first()
            if row is None:
                raise IntakeNotFoundError(f"intake {intake_id} not found for patient {patient_id}")

            media_rows = (
                await connection.execute(
                    select(intake_media_refs).where(
                        intake_media_refs.c.intake_id == intake_id,
                    )
                )
            ).all()

        media_refs = [
            MediaRefView(
                media_ref_id=int(m.id),
                media_type=m.media_type,
                object_key=m.object_key,
                audio_duration_ms=m.audio_duration_ms,
                file_size_bytes=m.file_size_bytes,
                record_attempt=m.record_attempt,
            )
            for m in media_rows
        ]

        return IntakeDetailView(
            intake_id=int(row.id),
            patient_id=int(row.patient_id),
            mode=row.mode,
            language=row.language,
            status=row.status,
            record_attempts=row.record_attempts,
            text=row.text,
            transcript=row.transcript,
            transcript_usability=row.transcript_usability,
            forced_text=row.forced_text,
            media_refs=media_refs,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def get_pre_summary(
        self,
        *,
        intake_id: int,
        patient_id: int,
    ) -> PreSummaryView:
        """Read the pre-summary with draft, confidence, honesty fields, and edits.

        The ``low_confidence`` field is the honesty cue: when True the UI
        shows "AI draft - doctor will verify" (AMB-006, spec #344).
        Patient-scoped: the facade verifies the intake belongs to the
        caller before returning the pre-summary.

        Raises :class:`IntakeNotFoundError` when no intake or pre-summary
        exists for the given pair.
        """
        async with self._engine.begin() as connection:
            intake_row = (
                await connection.execute(
                    select(intake_intakes.c.id).where(
                        intake_intakes.c.id == intake_id,
                        intake_intakes.c.patient_id == patient_id,
                    )
                )
            ).first()
            if intake_row is None:
                raise IntakeNotFoundError(f"intake {intake_id} not found for patient {patient_id}")

            row = (
                await connection.execute(
                    select(intake_pre_summaries).where(
                        intake_pre_summaries.c.intake_id == intake_id,
                    )
                )
            ).first()
            if row is None:
                raise IntakeNotFoundError(f"pre-summary not found for intake {intake_id}")

        return PreSummaryView(
            pre_summary_id=int(row.id),
            intake_id=int(row.intake_id),
            structured_fields=dict(row.structured_fields or {}),
            structuring_confidence=row.structuring_confidence,
            low_confidence=row.low_confidence,
            review_state=row.review_state,
            patient_edits=dict(row.patient_edits) if row.patient_edits else None,
            doctor_corrections=dict(row.doctor_corrections) if row.doctor_corrections else None,
            review_attribution=row.review_attribution,
            reviewed_at=row.reviewed_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def request_rx_draft(
        self,
        *,
        doctor_input_ref: int,
        pre_summary_ref: int,
        history_summary: str | None = None,
    ) -> None:
        """Contract stub for rx-draft generation (Phase 8 makes it live).

        Declared here so the facade surface matches the spec API
        (spec #344). The actual implementation lands in Phase 8 when the
        AI pipeline and doctor-approval flow are wired.
        """
        raise NotImplementedError(
            "request_rx_draft is a contract stub; implementation lands in Phase 8"
        )
