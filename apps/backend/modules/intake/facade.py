"""MOD-005 Intake workflows: typed public sync API (PHASE-7 T07, #351).

The only legal cross-module import target for the ``intake`` module
(coding-standards S2, ADR-0003). Thin coordinator that validates intake
submissions, commits the intake row + outbox event in one transaction
(ADR-0002 S1), and provides read projections for intake and pre-summary
data. ``request_rx_draft`` is the Phase 8 rx-drafting seam (PHASE-8 T05,
#421): it produces a structured rx draft from the doctor input through the
intake AI gateway port and returns it as a typed result. The caller
(``PrescriptionFacade.create_rx_draft``) supplies the consent-gated history
context
via ``history_summary`` (NFR-SEC-006); this facade never performs a raw
history read.

Capture durability is structural: the row + outbox event commit in one
local transaction, so a later AI failure never rolls back the intake
(spec #344, acceptance criterion 5).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from cryptography.exceptions import InvalidTag
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import get_settings
from bus.outbox_writer import write_outbox
from modules.intake.adapters import build_ai_gateway
from modules.intake.adapters.ai_gateway import (
    AiEgressContext,
    AiGateway,
    DraftRxRequest,
    DraftRxResult,
)
from modules.intake.adapters.media_store import IntakeMediaStore
from modules.intake.domain.events import (
    intake_captured_envelope,
    intake_retry_requested_envelope,
    intake_started_envelope,
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
    MAX_AUDIO_DURATION_MS,
    MAX_RECORD_ATTEMPTS,
    MAX_TEXT_LENGTH,
    MIN_AUDIO_DURATION_MS,
    IntakeAction,
    IntakeState,
    IntakeStatus,
    transition,
)
from modules.intake.intake_models import (
    INTAKE_SCHEMA,
    IntakeDetailView,
    IntakeSubmitResult,
    MediaFile,
    MediaRefView,
    MediaUploadRef,
    PatientEditsResult,
    PickDoctorResult,
    PreSummaryReviewResult,
    PreSummaryView,
    ReRecordResult,
    ReviewQueueItem,
    RxDraftItem,
    RxDraftResult,
    StructuredFields,
)
from modules.intake.outbox import INTAKE_OUTBOX_TABLE
from modules.intake.schema.models import (
    intake_intakes,
    intake_media_refs,
    intake_pre_summaries,
)

if TYPE_CHECKING:
    from modules.consent.facade import ConsentFacade

#: Number of attempts (initial + retries) the upload-transfer ladder makes
#: before it gives up on a flaky capture (NFR-PERF-002, spec #344 US-10).
MAX_UPLOAD_ATTEMPTS: int = 3


def _upload_backoff_delay(attempt: int) -> float:
    """Exponential backoff (seconds) before retry ``attempt`` (loop count, 2+).

    Retry ordinal ``r = attempt - 1`` scales ``base * 2**(r-1)``, so the two
    retries after the first failure back off 0.5s then 1.0s.
    """
    return 0.5 * (2.0 ** (attempt - 2))


def _validate_audio_duration(media_ref: MediaUploadRef) -> None:
    """Enforce the voice-audio duration floor and ceiling (T04).

    A bypass client must not submit unusable audio that wastes AI budget:
    clips under ``MIN_AUDIO_DURATION_MS`` (3s) or over ``MAX_AUDIO_DURATION_MS``
    (180s) are rejected with the actual and allowed duration in the message so
    clients get a clear 422. Short clips carry no speech signal, and long clips
    exceed the AI pipeline's context window.
    """
    if media_ref.audio_duration_ms is None:
        return
    if media_ref.audio_duration_ms < MIN_AUDIO_DURATION_MS:
        raise IntakeValidationError(
            f"audio duration {media_ref.audio_duration_ms}ms is below "
            f"minimum {MIN_AUDIO_DURATION_MS}ms"
        )
    if media_ref.audio_duration_ms > MAX_AUDIO_DURATION_MS:
        raise IntakeValidationError(
            f"audio duration {media_ref.audio_duration_ms}ms exceeds "
            f"maximum {MAX_AUDIO_DURATION_MS}ms"
        )


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
        ai_gateway: AiGateway | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        consent_facade: ConsentFacade | None = None,
    ) -> None:
        self._engine = engine
        self._media_store = media_store
        self._ai_gateway = ai_gateway
        self._sleep = sleep
        self._consent_facade = consent_facade

    async def submit_intake(
        self,
        *,
        patient_id: int,
        mode: Literal["voice", "text"],
        language: Literal["hi", "en"],
        text: str | None = None,
        media_ref: MediaUploadRef | None = None,
    ) -> IntakeSubmitResult:
        """Capture a symptom intake and emit ``intake.started`` + ``intake.captured``.

        Validates one-mode-per-intake: text mode requires ``text``, voice mode
        requires ``media_ref``. Text mode ALSO accepts an optional ``media_ref``
        - a doctor-only voice note that rides with the typed symptoms (PHASE-7
        T17 brief): it is persisted as an ``intake_media_refs`` row so the
        doctor hears it on review, and it is NEVER fed to the
        ``transcribe -> structure`` pipeline (the mode gate only transcribes
        ``mode == "voice"``). Enforces the text cap (``MAX_TEXT_LENGTH`` =
        2000 chars). Commits the intake row, the ``intake.started``
        funnel-telemetry event (PHASE-7 T05 #369), the ``intake.captured``
        outbox event, and the ``intake_media_refs`` row (when a media ref is
        present) in the SAME transaction (ADR-0002 S1) so a crash between
        state change and dispatch cannot lose the event(s). The voice-attempt
        cap (3 attempts) is enforced by the domain state machine at the
        re-record seam (``MAX_RECORD_ATTEMPTS``, PHASE-7 T02) - a fresh capture
        always begins at record attempt 1.

        ``media_ref`` is the opaque clip ticket returned by
        ``upload_intake_media``; for a voice intake it is attached here as
        record attempt 1 (the "attach later" contract, PHASE-7 T08).

        Raises :class:`IntakeValidationError` on validation failure.
        """
        if mode == "text":
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
            _validate_audio_duration(media_ref)

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

            if media_ref is not None:
                await connection.execute(
                    intake_media_refs.insert().values(
                        intake_id=intake_id,
                        media_type=media_ref.media_type,
                        object_key=media_ref.object_key,
                        audio_duration_ms=media_ref.audio_duration_ms,
                        file_size_bytes=media_ref.file_size_bytes,
                        record_attempt=state.record_attempts,
                    )
                )

            started_envelope = intake_started_envelope(
                patient_id=patient_id, mode=mode, language=language
            )
            await write_outbox(
                connection,
                INTAKE_SCHEMA,
                INTAKE_OUTBOX_TABLE,
                started_envelope,
            )

            duration_s = None
            if media_ref is not None and media_ref.audio_duration_ms is not None:
                duration_s = media_ref.audio_duration_ms / 1000.0
            envelope = intake_captured_envelope(
                intake_id=intake_id,
                patient_id=patient_id,
                mode=mode,
                duration_s=duration_s,
            )
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
                object_key = await self._media_store.save(
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
        not in a re-recordable state; :class:`IntakeValidationError` when the
        fresh clip duration is outside the accepted range.
        """
        _validate_audio_duration(media_ref)

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
                reason="patient_re_record",
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

    async def get_intake_media(
        self,
        *,
        intake_id: int,
        media_ref_id: int,
        caller_id: int,
        caller_role: Literal["patient", "doctor"],
    ) -> bytes:
        """Decrypt and return the audio bytes for a media ref on an intake.

        Authorization gate (PHASE-7 T13/T17, #373): the clip is only served to
        the owning patient (``caller_role == "patient"`` and ``caller_id``
        matching the intake's patient) or to a doctor partner
        (``caller_role == "doctor"``; the route seam has already verified the
        partner is an active doctor via ``require_partner`` +
        ``partner_type == "doctor"``). PHASE-8.1 (#443) scopes doctor reads to
        the patient's pick: only the doctor recorded in ``assigned_partner_id``
        is served - an unassigned doctor (or one reading before any pick) gets
        the same 404 as a non-owner so the intake's existence is never
        revealed. Audio is PHI, so the returned bytes are never logged.

        The intake must exist and the ``media_ref_id`` must belong to it.
        Raises :class:`IntakeNotFoundError` when either lookup misses or the
        doctor caller is not the assigned doctor;
        :class:`IntakeValidationError` when the store is not configured;
        :class:`MediaTransferError` when the clip cannot be read/decrypted.
        """
        if self._media_store is None:
            raise IntakeValidationError("media store is not configured")

        async with self._engine.begin() as connection:
            if caller_role == "patient":
                intake_row = (
                    await connection.execute(
                        select(intake_intakes).where(
                            intake_intakes.c.id == intake_id,
                            intake_intakes.c.patient_id == caller_id,
                        )
                    )
                ).first()
            else:
                # PHASE-8.1 assigned-partner scoping (#443): after the patient
                # picks a doctor, the intake's health information is served only
                # to that doctor. The scoping predicate is in the WHERE clause
                # (data minimization, security standards §2) - an unassigned
                # doctor partner (or one reading before any pick, or a
                # different doctor) matches no row and gets the same 404 as a
                # non-owner, so the intake's existence is never revealed.
                intake_row = (
                    await connection.execute(
                        select(intake_intakes).where(
                            intake_intakes.c.id == intake_id,
                            intake_intakes.c.assigned_partner_id == caller_id,
                        )
                    )
                ).first()
            if intake_row is None:
                raise IntakeNotFoundError(f"intake {intake_id} not found for caller {caller_id}")

            media_row = (
                await connection.execute(
                    select(intake_media_refs).where(
                        intake_media_refs.c.intake_id == intake_id,
                        intake_media_refs.c.id == media_ref_id,
                    )
                )
            ).first()
            if media_row is None:
                raise IntakeNotFoundError(
                    f"media ref {media_ref_id} not found on intake {intake_id}"
                )
            object_key = str(media_row.object_key)

        try:
            return await self._media_store.read(object_key=object_key)
        except (OSError, InvalidTag) as exc:
            raise MediaTransferError(
                f"failed to read media ref {media_ref_id} for intake {intake_id}"
            ) from exc

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

    async def get_finalized_pre_summary(
        self,
        *,
        pre_summary_id: int,
    ) -> PreSummaryView:
        """Return the pre-summary ONLY when it is in the terminal ``final`` state.

        The MOD-006 consult-handshake gate (CONTEXT.md glossary, ``finalized
        pre-summary``): the sole acceptable input to
        ``mark_consult_complete``. Queries ``intake_pre_summaries`` and
        returns a :class:`PreSummaryView` only when ``review_state == final``
        - a working copy (draft/reviewed) is never served, so a
        prescription-stage case can never arise from an unreviewed summary
        (FEAT-008 edge case).

        Raises :class:`IntakeNotFoundError` when no pre-summary row exists for
        the id; :class:`IntakeValidationError` when the summary exists but is
        not yet ``final``.
        """
        async with self._engine.begin() as connection:
            row = (
                await connection.execute(
                    select(intake_pre_summaries).where(
                        intake_pre_summaries.c.id == pre_summary_id,
                    )
                )
            ).first()
            if row is None:
                raise IntakeNotFoundError(f"pre-summary {pre_summary_id} not found")

            if row.review_state != PreSummaryStatus.FINAL.value:
                raise IntakeValidationError(
                    f"pre-summary {pre_summary_id} is not finalized "
                    f"(review_state={row.review_state}); the consult handshake "
                    "requires a final-state summary"
                )

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

    async def list_review_queue(
        self,
        *,
        doctor_id: int,
    ) -> list[ReviewQueueItem]:
        """List the doctor's assigned pre-summaries still awaiting review (US-11/12).

        The doctor review-queue read (PHASE-8.1 T07, #447): every pre-summary
        on an intake the patient assigned to ``doctor_id`` (pick, #443) that
        is still in the ``draft`` review state - awaiting the doctor's review.
        Ordered low-confidence first (US-12, the AMB-006 honesty priority:
        the summaries that most need the doctor's attention surface before the
        clean ones), then newest-created first within each confidence class so
        a waiting list never reorders under concurrent review activity. Each
        item carries the ``low_confidence`` flag (the AMB-006 cue).

        ``doctor_id`` is the partner identity of the calling doctor (RBAC
        enforced at the route seam). The scoping predicate lives in the JOIN
        WHERE (data minimization, security standards §2): an unassigned doctor
        matches no rows, so an intake assigned to a different doctor is never
        revealed. Open care cases continue to come from the existing
        doctor-scoped case list; this endpoint returns only the review queue
        and the console merges the two lists client-side.
        """
        async with self._engine.begin() as connection:
            rows = (
                await connection.execute(
                    select(
                        intake_pre_summaries.c.id,
                        intake_pre_summaries.c.intake_id,
                        intake_pre_summaries.c.structuring_confidence,
                        intake_pre_summaries.c.low_confidence,
                        intake_pre_summaries.c.review_state,
                        intake_pre_summaries.c.created_at,
                        intake_pre_summaries.c.updated_at,
                    )
                    .select_from(
                        intake_pre_summaries.join(
                            intake_intakes,
                            intake_intakes.c.id == intake_pre_summaries.c.intake_id,
                        )
                    )
                    .where(
                        intake_intakes.c.assigned_partner_id == doctor_id,
                        intake_pre_summaries.c.review_state == PreSummaryStatus.DRAFT.value,
                    )
                    .order_by(
                        case((intake_pre_summaries.c.low_confidence.is_(True), 0), else_=1),
                        intake_pre_summaries.c.created_at.desc(),
                    )
                )
            ).all()

        return [
            ReviewQueueItem(
                pre_summary_id=int(row.id),
                intake_id=int(row.intake_id),
                structuring_confidence=row.structuring_confidence,
                low_confidence=row.low_confidence,
                review_state=row.review_state,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in rows
        ]

    async def get_doctor_pre_summary(
        self,
        *,
        intake_id: int,
        doctor_id: int,
    ) -> PreSummaryView:
        """Read the full pre-summary content for the assigned doctor (US-13, #448, FEAT-008).

        The doctor full pre-summary read (PHASE-8.1 T08): the first
        doctor-scoped read to return the pre-summary's CONTENT - the structured
        summary (``structured_fields``: symptoms, duration, severity, history,
        medications, allergies), the structuring confidence, the
        ``low_confidence`` honesty flag (AMB-006), and the review state - so
        the doctor's review is informed by the patient's own words and the AI
        summary. Today every other pre-summary read is patient-only and the
        care-case view returns only the pre-summary id, so this is a genuinely
        new surface required by any review flow (backend delta 3, #438).

        Assigned-partner scoping (#443), matching ``get_intake_media``: the
        intake's health information is served only to the doctor recorded in
        ``assigned_partner_id``. The scoping predicate lives in the JOIN WHERE
        (data minimization, security standards §2) - an unassigned doctor
        partner (or one reading before any pick, or a different doctor) matches
        no row and gets the same 404 as a non-owner, so the intake's existence
        is never revealed. The read returns any review state (draft/reviewed/
        final) - it carries state, it does not gate on it.

        Raises :class:`IntakeNotFoundError` when no intake assigned to
        ``doctor_id`` has a pre-summary for the given ``intake_id``.
        """
        async with self._engine.begin() as connection:
            row = (
                await connection.execute(
                    select(intake_pre_summaries)
                    .select_from(
                        intake_pre_summaries.join(
                            intake_intakes,
                            intake_intakes.c.id == intake_pre_summaries.c.intake_id,
                        )
                    )
                    .where(
                        intake_pre_summaries.c.intake_id == intake_id,
                        intake_intakes.c.assigned_partner_id == doctor_id,
                    )
                )
            ).first()
            if row is None:
                raise IntakeNotFoundError(
                    f"pre-summary not found for intake {intake_id} assigned to doctor {doctor_id}"
                )

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

        - **low_confidence** (below 0.70 or missing): the one-action finalize
          (PHASE-8.1, #442) - this attributed review action reviews AND
          finalizes the pre-summary (``PreSummaryAction.REVIEW``,
          ``Draft -> Final``), so no low-confidence case is left stuck at
          ``Reviewed``. The machine structurally blocks every other route to
          ``Final`` for a low-confidence pre-summary, keeping the attribution
          gate a real doctor action. A row already at ``reviewed`` (a legacy
          dead-end) is finalized by the same review action through the
          ``Reviewed -> Final`` edge.
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
            # PHASE-8.1 one-action finalize (#442): the attributed review of a
            # low-confidence pre-summary lands Final in this SAME action - via
            # the low-confidence Review edge while DRAFT, or via the always-legal
            # Reviewed -> Finalize edge for a row already stuck at 'reviewed'.
            # High-confidence rows keep the single-action Finalize clean path.
            if low_conf and current.status is PreSummaryStatus.DRAFT:
                action = PreSummaryAction.REVIEW
            else:
                action = PreSummaryAction.FINALIZE
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
            # (ADR-0002 S1). Every attributed review is now a single-action
            # finalize (the high-confidence clean path and the low-confidence
            # one-action finalize, #442), so reaching ``Final`` publishes
            # ``pre_summary.ready`` and MOD-006 attaches the summary to the case
            # while MOD-010 notifies the patient - no low-confidence case is ever
            # left stuck at ``reviewed``. The machine-driven guard below stays.
            if next_state.status is PreSummaryStatus.FINAL:
                patient_id = (
                    await connection.execute(
                        select(intake_intakes.c.patient_id).where(
                            intake_intakes.c.id == intake_id,
                        )
                    )
                ).scalar_one()
                await write_outbox(
                    connection,
                    INTAKE_SCHEMA,
                    INTAKE_OUTBOX_TABLE,
                    pre_summary_ready_envelope(
                        intake_id=intake_id,
                        pre_summary_id=int(row.id),
                        patient_id=int(patient_id),
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

    async def pick_doctor(
        self,
        *,
        intake_id: int,
        patient_id: int,
        partner_id: int,
    ) -> PickDoctorResult:
        """Record the patient's pick-a-doctor and its consent in ONE write (#443).

        Consent-at-pick (MOD-004): the pick IS the consent moment. The chosen
        doctor's partner identity is written to ``intake_intakes``
        (``assigned_partner_id``) and the standing grant for the
        (patient, doctor, consultations) triple is recorded in the SAME
        transaction via ``ConsentFacade.grant_consent_on`` - one atomic write,
        no second gate. From this moment the pre-summary is assigned to that
        doctor: doctor-facing reads (``get_intake_media`` here, the review-queue
        and pre-summary reads #447/#448) are scoped to the assigned partner.

        The write is patient-scoped: the intake must belong to ``patient_id`` or
        :class:`IntakeNotFoundError` is raised (404, mirroring the ownership
        reads). Exactly one doctor is ever picked: an intake already assigned
        (``assigned_partner_id`` set, to any doctor) refuses the pick with
        :class:`IllegalIntakeTransitionError` - a client retry of the same pick
        is safe via the idempotency header at the route seam (api-standards S5),
        never by re-picking.

        The consent cache is invalidated after the commit (the grant only became
        visible when this transaction committed), so a later ``check_consent``
        never answers from a stale decision.

        Raises :class:`IntakeNotFoundError` when the intake is not the caller's;
        :class:`IllegalIntakeTransitionError` when a doctor is already assigned;
        :class:`IntakeValidationError` when ``partner_id`` is missing.
        """
        if not partner_id:
            raise IntakeValidationError("a doctor must be chosen to pick")
        if self._consent_facade is None:
            raise IntakeValidationError("consent facade is not configured")

        counterparty_type: Literal["doctor", "lab", "chemist"] = "doctor"
        counterparty_id = str(partner_id)
        record_scope = "consultations"

        async with self._engine.begin() as connection:
            row = (
                await connection.execute(
                    select(
                        intake_intakes.c.id,
                        intake_intakes.c.patient_id,
                        intake_intakes.c.assigned_partner_id,
                    )
                    .where(intake_intakes.c.id == intake_id)
                    .with_for_update()
                )
            ).first()
            if row is None or row.patient_id != patient_id:
                raise IntakeNotFoundError(f"intake {intake_id} not found for patient {patient_id}")
            if row.assigned_partner_id is not None:
                raise IllegalIntakeTransitionError(
                    f"a doctor is already assigned to intake {intake_id}"
                )

            await connection.execute(
                intake_intakes.update()
                .where(intake_intakes.c.id == intake_id)
                .values(
                    assigned_partner_id=partner_id,
                    updated_at=func.now(),
                )
            )
            consent_view = await self._consent_facade.grant_consent_on(
                connection,
                patient_id,
                counterparty_type,
                counterparty_id,
                record_scope,
            )

        # The grant is only visible once THIS transaction committed; invalidate
        # the gate cache only now (outside the transaction, post-commit).
        await self._consent_facade.invalidate_consent_cache(
            patient_id, counterparty_type, counterparty_id, record_scope
        )

        return PickDoctorResult(
            intake_id=intake_id,
            assigned_partner_id=partner_id,
            consent_id=consent_view.consent_id,
            consent_lineage_ref=consent_view.lineage_ref,
            consent_version=consent_view.version,
        )

    async def request_rx_draft(
        self,
        *,
        doctor_input_ref: int,
        pre_summary_ref: int,
        history_summary: str | None = None,
    ) -> RxDraftResult:
        """Produce a structured rx draft from the doctor input (PHASE-8 T05).

        Delegates to the AI gateway ``draft_rx`` leg (the Phase 7 providers
        - mock/fallback/openai-compatible) and returns a typed result with the
        draft ``rx_items`` and the provider confidence. The caller
        (``PrescriptionFacade.create_rx_draft``) supplies the consent-gated
        history
        context via ``history_summary`` (NFR-SEC-006) - this facade never
        performs a raw history read.

        Resolves the declared language from the intake record associated with
        ``pre_summary_ref`` so the AI gateway's ``AiEgressContext`` carries
        only the intake context (NFR-SEC-006 egress boundary). Raises
        :class:`~modules.intake.domain.exceptions.IntakeNotFoundError` when no
        pre-summary or intake exists for the given references.
        """
        gateway = self._ai_gateway
        if gateway is None:
            gateway = build_ai_gateway(get_settings())

        async with self._engine.begin() as connection:
            ps_row = (
                await connection.execute(
                    select(intake_pre_summaries).where(
                        intake_pre_summaries.c.id == pre_summary_ref,
                    )
                )
            ).first()
            if ps_row is None:
                raise IntakeNotFoundError(f"pre-summary {pre_summary_ref} not found for rx-draft")

            intake_row = (
                await connection.execute(
                    select(intake_intakes).where(
                        intake_intakes.c.id == ps_row.intake_id,
                    )
                )
            ).first()
            language: str = intake_row.language if intake_row is not None else "en"

        draft_result: DraftRxResult = await gateway.draft_rx(
            DraftRxRequest(
                doctor_input_ref=str(doctor_input_ref),
                pre_summary_ref=str(pre_summary_ref),
                patient_history_summary=history_summary or "",
                context=AiEgressContext(language=language),
            )
        )

        return RxDraftResult(
            doctor_input_ref=doctor_input_ref,
            pre_summary_ref=pre_summary_ref,
            rx_items=[
                RxDraftItem(name=item.name, dose=item.dose, duration=item.duration)
                for item in draft_result.rx_items
            ],
            confidence=draft_result.confidence,
        )
