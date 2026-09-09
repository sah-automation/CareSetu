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

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Literal, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from bus.outbox_writer import write_outbox
from modules.intake.adapters.media_store import IntakeMediaStore
from modules.intake.domain.events import (
    intake_captured_envelope,
    intake_retry_requested_envelope,
    pre_summary_ready_envelope,
)
from modules.intake.domain.exceptions import (
    IllegalIntakeTransitionError,
    IntakeNotFoundError,
    IntakeValidationError,
    MediaTransferError,
)
from modules.intake.domain.presummary_machine import (
    PreSummaryAction,
    PreSummaryState,
    PreSummaryStatus,
    is_low_confidence,
)
from modules.intake.domain.presummary_machine import (
    transition as pre_summary_transition,
)
from modules.intake.domain.state_machine import (
    CAPTURED,
    MAX_RECORD_ATTEMPTS,
    MAX_TEXT_LENGTH,
    IntakeAction,
    IntakeState,
    IntakeStatus,
    transition,
)
from modules.intake.intake_models import (
    IntakeDetailView,
    IntakeSubmitResult,
    MediaFile,
    MediaRefView,
    MediaUploadRef,
    PatientEditsResult,
    PreSummaryReviewResult,
    PreSummaryView,
    ReRecordResult,
    StructuredFields,
)
from modules.intake.outbox import INTAKE_OUTBOX_TABLE
from modules.intake.schema.models import (
    intake_intakes,
    intake_media_refs,
    intake_pre_summaries,
)

#: Number of attempts (initial + retries) the upload-transfer ladder makes
#: before it gives up on a flaky capture (NFR-PERF-002, spec #344 US-10).
MAX_UPLOAD_ATTEMPTS: int = 3


def _upload_backoff_delay(attempt: int) -> float:
    """Exponential backoff (seconds) before retry ``attempt`` (loop count, 2+).

    Retry ordinal ``r = attempt - 1`` scales ``base * 2**(r-1)``, so the two
    retries after the first failure back off 0.5s then 1.0s.
    """
    return 0.5 * (2.0 ** (attempt - 2))


INTAKE_SCHEMA = "intake"


class IntakeFacade:
    """Typed public facade for intake capture and read projections.

    Takes the engine in its constructor, mirroring the partner facade
    convention. Enforces one-mode-per-intake and the text cap (2000 chars)
    server-side with typed errors.
    """

    def __init__(
        self,
        engine: AsyncEngine,
        *,
        media_store: IntakeMediaStore | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._engine = engine
        self._media_store = media_store
        self._sleep = sleep

    async def submit_intake(
        self,
        *,
        patient_id: int,
        mode: Literal["voice", "text"],
        language: Literal["hi", "en"],
        text: str | None = None,
        media_ref: MediaUploadRef | None = None,
    ) -> IntakeSubmitResult:
        """Capture a symptom intake and emit ``intake.captured`` atomically.

        Validates one-mode-per-intake: exactly one of ``text`` or
        ``media_ref`` must be provided, matching the declared ``mode``.
        Enforces the text cap (``MAX_TEXT_LENGTH`` = 2000 chars). Commits
        the intake row, the ``intake.captured`` outbox event, and (for a
        voice intake) the ``intake_media_refs`` row in the SAME
        transaction (ADR-0002 S1) so a crash between state change and
        dispatch cannot lose the event. The voice-attempt cap (3 attempts)
        is enforced by the domain state machine at the re-record seam
        (``MAX_RECORD_ATTEMPTS``, PHASE-7 T02) - a fresh capture always
        begins at record attempt 1.

        ``media_ref`` is the opaque clip ticket returned by
        ``upload_intake_media``; for a voice intake it is attached here as
        record attempt 1 (the "attach later" contract, PHASE-7 T08).

        Raises :class:`IntakeValidationError` on validation failure.
        """
        if mode == "text":
            if media_ref is not None:
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
            if media_ref is None:
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

            if mode == "voice":
                media_ref_attached = cast(MediaUploadRef, media_ref)
                await connection.execute(
                    intake_media_refs.insert().values(
                        intake_id=intake_id,
                        media_type=media_ref_attached.media_type,
                        object_key=media_ref_attached.object_key,
                        audio_duration_ms=media_ref_attached.audio_duration_ms,
                        file_size_bytes=media_ref_attached.file_size_bytes,
                        record_attempt=state.record_attempts,
                    )
                )

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

    async def upload_intake_media(
        self,
        *,
        patient_id: int,
        file: MediaFile,
    ) -> MediaUploadRef:
        """Capture an audio clip to the object store with upload resilience.

        Runs the media-store write through an upload-resilience ladder
        (NFR-PERF-002, spec #344 US-10): on a transient write failure it backs
        off and retries up to ``MAX_UPLOAD_ATTEMPTS`` (3) attempts, then raises
        the typed :class:`MediaTransferError` - a partial capture is never
        silently lost. The clip is encrypted at rest under the ``intake/``
        prefix before it touches disk (security-phii-standards, audio = PHI).

        Answers an opaque :class:`MediaUploadRef` clip ticket recording the
        object key, type, duration, size, and record attempt. No database row
        is written here - the ticket is attached to an intake later, by
        ``submit_intake`` (first take) or ``re_record_intake`` (retry), which
        persists the ``intake_media_refs`` row against the intake.

        Raises :class:`MediaTransferError` when every upload attempt fails.
        """
        if self._media_store is None:
            raise IntakeValidationError("media store is not configured")

        object_key: str | None = None
        last_error: OSError | None = None
        for attempt in range(1, MAX_UPLOAD_ATTEMPTS + 1):
            if attempt > 1:
                await self._sleep(_upload_backoff_delay(attempt))
            try:
                object_key = self._media_store.save(
                    data=file.data,
                    patient_id=patient_id,
                )
                break
            except OSError as exc:
                last_error = exc

        if object_key is None:
            raise MediaTransferError(
                f"media upload failed after {MAX_UPLOAD_ATTEMPTS} attempts for patient {patient_id}"
            ) from last_error

        return MediaUploadRef(
            object_key=object_key,
            media_type=file.media_type,
            audio_duration_ms=file.audio_duration_ms,
            file_size_bytes=file.file_size_bytes,
            record_attempt=file.record_attempt,
        )

    async def re_record_intake(
        self,
        *,
        intake_id: int,
        patient_id: int,
        media_ref: MediaUploadRef,
    ) -> ReRecordResult:
        """Attach a fresh recording attempt to a re-record intake.

        Patient-scoped: the intake must belong to ``patient_id``. The intake
        must be in the ``re_record`` state (the patient was asked for a new
        take, B3 ladder).

        If the intake's server-side attempt count is already at
        ``MAX_RECORD_ATTEMPTS`` (3) the request hard-stops - the machine routes
        the intake to forced text (``FORCE_TEXT``, Ready for Review with
        ``forced_text=True``) so the patient is never stuck, and no
        ``intake.retry_requested`` is emitted. The cap is enforced here on the
        server's own count, never trusted from the client.

        Otherwise the fresh clip is attached as a new ``intake_media_refs`` row
        (record attempt = the incremented count), the intake returns to
        structuring (``RETRY_ACCEPTED``, attempt +1), and ``intake.retry_requested``
        is emitted - all in one transaction (ADR-0002 A1).

        Raises :class:`IntakeNotFoundError` when the intake does not belong to
        the patient; :class:`IllegalIntakeTransitionError` when the intake is
        not in a re-recordable state.
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

            current = IntakeState(
                status=IntakeStatus(row.status),
                record_attempts=int(row.record_attempts),
                forced_text=bool(row.forced_text),
            )

            if current.status is not IntakeStatus.RE_RECORD:
                raise IllegalIntakeTransitionError(
                    f"intake {intake_id} is in status {current.status.value}, "
                    "not re_record; re-record is only allowed on re-record intakes"
                )

            if current.record_attempts >= MAX_RECORD_ATTEMPTS:
                next_state = transition(current, IntakeAction.FORCE_TEXT)
                await connection.execute(
                    intake_intakes.update()
                    .where(intake_intakes.c.id == intake_id)
                    .values(
                        status=next_state.status.value,
                        record_attempts=next_state.record_attempts,
                        forced_text=next_state.forced_text,
                    )
                )
                return ReRecordResult(
                    intake_id=intake_id,
                    accepted=False,
                    status=next_state.status.value,
                    record_attempts=next_state.record_attempts,
                    forced_text=next_state.forced_text,
                )

            next_state = transition(current, IntakeAction.RETRY_ACCEPTED)

            media_result = await connection.execute(
                intake_media_refs.insert()
                .values(
                    intake_id=intake_id,
                    media_type=media_ref.media_type,
                    object_key=media_ref.object_key,
                    audio_duration_ms=media_ref.audio_duration_ms,
                    file_size_bytes=media_ref.file_size_bytes,
                    record_attempt=next_state.record_attempts,
                )
                .returning(intake_media_refs.c.id)
            )
            media_ref_id = int(media_result.scalar_one())

            await connection.execute(
                intake_intakes.update()
                .where(intake_intakes.c.id == intake_id)
                .values(
                    status=next_state.status.value,
                    record_attempts=next_state.record_attempts,
                    forced_text=next_state.forced_text,
                )
            )

            envelope = intake_retry_requested_envelope(
                intake_id=intake_id,
                record_attempt=next_state.record_attempts,
            )
            await write_outbox(
                connection,
                INTAKE_SCHEMA,
                INTAKE_OUTBOX_TABLE,
                envelope,
            )

        return ReRecordResult(
            intake_id=intake_id,
            accepted=True,
            status=next_state.status.value,
            record_attempts=next_state.record_attempts,
            forced_text=next_state.forced_text,
            media_ref_id=media_ref_id,
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
            structured_fields=StructuredFields.model_validate(row.structured_fields or {}),
            structuring_confidence=row.structuring_confidence,
            low_confidence=row.low_confidence,
            review_state=row.review_state,
            patient_edits=dict(row.patient_edits) if row.patient_edits else None,
            doctor_corrections=dict(row.doctor_corrections) if row.doctor_corrections else None,
            review_attribution=row.review_attribution,
            reviewed_by=int(row.reviewed_by) if row.reviewed_by is not None else None,
            reviewed_at=row.reviewed_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def save_patient_pre_summary_edits(
        self,
        *,
        intake_id: int,
        patient_id: int,
        fields: dict[str, object],
    ) -> PatientEditsResult:
        """Record patient-spotted mistakes as informational corrections (US-14).

        Persists ``fields`` onto ``intake_pre_summaries.patient_edits`` as
        informational corrections AVAILABLE TO THE DOCTOR - they never mutate
        the AI ``structured_fields`` and never trigger a review transition
        (patient edits are advice, not authority; only the doctor review has
        edit-wins semantics). Corrections ACCUMULATE across saves (a later
        save merges over the earlier ones), so a patient adding more mistakes
        never loses the ones already marked. Patient-scoped: the caller must
        own the intake.

        Raises :class:`IntakeNotFoundError` when no pre-summary exists for the
        patient's intake.
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

            merged_edits = {**(row.patient_edits or {}), **fields}

            await connection.execute(
                intake_pre_summaries.update()
                .where(intake_pre_summaries.c.id == row.id)
                .values(
                    patient_edits=merged_edits,
                    updated_at=func.now(),
                )
            )

        return PatientEditsResult(
            intake_id=intake_id,
            pre_summary_id=int(row.id),
            patient_edits=merged_edits,
        )

    async def mark_pre_summary_reviewed(
        self,
        *,
        intake_id: int,
        doctor_id: int,
        corrections: dict[str, object] | None = None,
    ) -> PreSummaryReviewResult:
        """Perform the attributed doctor review-and-edit (US-21 through US-24).

        The single, individually-attributed review action. ``doctor_id`` is the
        reviewing doctor (RBAC enforced at the route seam, PHASE-7 T13) and is
        required for attribution. ``corrections`` maps the fields the doctor
        edited to their corrected values; the doctor's edits WIN over the AI
        extraction, so the resulting ``reviewed_copy`` is the original
        ``structured_fields`` with every correction overlaid.

        The transition the machine applies depends on confidence (the
        AMB-006 0.70 threshold, structurally enforced here):

        - **low_confidence** (below 0.70 or missing): the hard gate - the
          pre-summary can ONLY reach ``Reviewed`` through this attributed
          review action (``PreSummaryAction.REVIEW``). It never reaches
          ``Final`` unreviewed.
        - **high_confidence**: the clean path - a single attributed review
          action reviews AND finalizes it (``PreSummaryAction.FINALIZE``,
          ``Draft -> Final``), user story 23.

        The confirming change-list (the correction keys whose value actually
        changed), the reviewing doctor's identity (``reviewed_by`` =
        ``doctor_id``), and the review timestamp are persisted in the same
        transaction as the state change (ADR-0002 §1), making the reviewed
        copy trustworthy and attributable to a specific doctor (US-22).

        Raises :class:`IntakeNotFoundError` when no pre-summary exists for the
        intake; :class:`IntakeValidationError` when ``doctor_id`` is missing;
        :class:`~modules.intake.domain.exceptions.IllegalPreSummaryTransitionError`
        when the review action is illegal in the current state (e.g. an already-
        reviewed or finalized pre-summary).
        """
        if not doctor_id:
            raise IntakeValidationError("a doctor identity is required for review attribution")
        resolved = dict(corrections or {})

        async with self._engine.begin() as connection:
            row = (
                await connection.execute(
                    select(intake_pre_summaries).where(
                        intake_pre_summaries.c.intake_id == intake_id,
                    )
                )
            ).first()
            if row is None:
                raise IntakeNotFoundError(f"pre-summary not found for intake {intake_id}")

            current = PreSummaryState(
                status=PreSummaryStatus(row.review_state),
                structuring_confidence=row.structuring_confidence,
            )
            low_conf = is_low_confidence(row.structuring_confidence)
            action = PreSummaryAction.REVIEW if low_conf else PreSummaryAction.FINALIZE
            next_state = pre_summary_transition(current, action)

            original = dict(row.structured_fields or {})
            reviewed_copy = {**original, **resolved}
            changed_fields = [key for key in resolved if resolved.get(key) != original.get(key)]
            reviewed_at = datetime.now(UTC)

            await connection.execute(
                intake_pre_summaries.update()
                .where(intake_pre_summaries.c.id == row.id)
                .values(
                    structured_fields=reviewed_copy,
                    doctor_corrections=resolved,
                    review_state=next_state.status.value,
                    review_attribution="doctor",
                    reviewed_by=doctor_id,
                    reviewed_at=reviewed_at,
                    updated_at=func.now(),
                )
            )

            # Every state change writes its outbox event in the SAME transaction
            # (ADR-0002 S1). A review that REACHES ``Final`` (high-confidence
            # single action) publishes ``pre_summary.ready`` so MOD-006 attaches
            # the summary to the case and MOD-010 notifies the patient. The
            # low-confidence gate to ``Reviewed`` publishes nothing: there is no
            # "reviewed" event in the registry, the pre-summary is not yet ready
            # for downstream use, and ``pre_summary.low_confidence`` (needs
            # review) would be factually wrong once reviewed.
            if next_state.status is PreSummaryStatus.FINAL:
                await write_outbox(
                    connection,
                    INTAKE_SCHEMA,
                    INTAKE_OUTBOX_TABLE,
                    pre_summary_ready_envelope(
                        intake_id=intake_id,
                        pre_summary_id=int(row.id),
                    ),
                )

        return PreSummaryReviewResult(
            intake_id=intake_id,
            pre_summary_id=int(row.id),
            review_state=next_state.status.value,
            reviewed_copy=reviewed_copy,
            changed_fields=changed_fields,
            review_attribution="doctor",
            reviewed_by=doctor_id,
            reviewed_at=reviewed_at,
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
