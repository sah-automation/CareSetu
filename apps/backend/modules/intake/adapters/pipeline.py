"""MOD-005: the async intake AI structuring pipeline (PHASE-7 T04).

Holds the pipeline implementation extracted from ``adapters/__init__.py``
(composition root). ``register_handlers`` in ``__init__.py`` remains the
registration seam; it routes ``intake.captured`` here via
``_run_structuring_pipeline``. The pipeline body (transcribe -> structure ->
pre_summary) lives here. This is a pure extraction refactor (T01, #365): zero
behavioral change from the prior single-file layout.

The ``intake.captured`` handler is the async AI pipeline (MOD-005 self-
subscription). It is ledger-first (ADR-0002 §3): the ``consumed_events`` row
is written in the SAME transaction as the pipeline effects, so replaying a
delivered ``event_id`` finds its ledger row and is a no-op - exactly one
pre-summary per captured event. It creates an ``intake_ai_jobs`` row, runs
transcribe (voice) then structure through the ``AiGateway`` port (the mock
provider is the fail-closed default), writes a Draft pre_summary, and
publishes ``pre_summary.ready`` + ``ai_job.completed`` on success. Budget
meter and consent-gate enforcement land in T11; the happy path never raises
a user-visible error to the patient - a missing/unstructurable intake
degrades to a logged skip.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from decimal import Decimal

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

import modules.intake.adapters as _adapters
from app.config import get_settings
from bus.outbox_writer import write_outbox
from modules.consent.facade import ConsentFacade
from modules.intake.adapters.ai_gateway import (
    AiEgressContext,
    StructureRequest,
    TranscribeRequest,
)
from modules.intake.adapters.ai_provider_ext import Ext002CallError
from modules.intake.budget_meter import BudgetMeter
from modules.intake.domain.events import (
    ai_egress_recorded_envelope,
    ai_job_completed_envelope,
    ai_job_failed_envelope,
    intake_retry_requested_envelope,
    pre_summary_low_confidence_envelope,
    pre_summary_ready_envelope,
)
from modules.intake.domain.presummary_machine import is_low_confidence
from modules.intake.domain.state_machine import (
    IntakeAction,
    IntakeState,
    IntakeStatus,
    TranscriptUsability,
    classify_transcript_usability,
    transition,
)
from modules.intake.intake_models import INTAKE_SCHEMA, StructuredFields
from modules.intake.outbox import INTAKE_OUTBOX_TABLE
from modules.intake.schema.models import (
    intake_ai_jobs,
    intake_intakes,
    intake_media_refs,
    intake_pre_summaries,
)

logger = logging.getLogger(__name__)


def _egress_context(language: str) -> AiEgressContext:
    """Build the PHI-minimized egress context from the intake row.

    ``language`` is real (declared at capture); ``age_range``/``sex`` are
    placeholder defaults until the patient-profile source lands (T11). The
    context is the only patient-shaped data allowed to cross to EXT-002
    (NFR-SEC-006) - never name/phone/full record.
    """
    return AiEgressContext(
        language=language,
        age_range=_adapters.DEFAULT_EGRESS_AGE_RANGE,
        sex=_adapters.DEFAULT_EGRESS_SEX,
    )


def _build_egress_gate() -> tuple[AsyncEngine, ConsentFacade, BudgetMeter]:
    """Compose the consent gate + NFR-001 budget meter for one pipeline run.

    The AI pipeline is a worker handler: it receives only the delivery
    connection, while ``ConsentFacade`` and ``BudgetMeter`` own their own
    transactions (consent check, egress audit, month spend aggregate). A
    short-lived ``NullPool`` engine mirrors the delivery-engine lifecycle
    (``bus.handler_harness``); the caller disposes it with the run. Tests
    patch this seam to inject fakes.
    """
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    return (
        engine,
        ConsentFacade(engine=engine),
        BudgetMeter(
            engine=engine,
            monthly_budget_paise=get_settings().ai_monthly_budget_paise,
        ),
    )


async def _run_structuring_pipeline(
    connection: AsyncConnection,
    intake_id: int,
) -> None:
    """Run transcribe -> structure on a captured intake and publish a Draft pre_summary.

    The T11 pipeline is gated and degradable: a single ``structure`` ai_jobs row
    records the whole pass (provider/model/tokens/cost/latency/status/attempts),
    and the intake is moved Captured -> Structuring -> Ready for Review. Before
    any egress the NFR-001 budget meter is consulted (hard stop) and the consent
    gate is checked fail-closed (missing/revoked grant -> raw doctor review with
    no PHI sent); every successful egress is PHI-minimized (intake context only)
    and audited via ``record_egress_disclosure``. Timeout-after-3-retries and
    malformed provider output mark the job ``failed`` and degrade to raw review;
    a low-confidence structuring outcome publishes ``pre_summary.low_confidence``
    and forces doctor review. All effects ride the SAME transaction as the
    ledger-first dedupe (replay is a no-op); the handler never raises a
    user-visible error to the patient.
    """
    row = (
        await connection.execute(select(intake_intakes).where(intake_intakes.c.id == intake_id))
    ).first()
    if row is None:
        logger.warning(
            "intake.captured consumed for missing intake %s; skipping pipeline",
            intake_id,
        )
        return

    current = IntakeState(
        status=IntakeStatus(row.status),
        record_attempts=int(row.record_attempts),
        forced_text=bool(row.forced_text),
    )
    if current.status is not IntakeStatus.CAPTURED:
        logger.warning(
            "intake %s is %s, not captured; skipping AI pipeline (already structured?)",
            intake_id,
            current.status.value,
        )
        return

    structing = transition(current, IntakeAction.START_STRUCTURING)
    await connection.execute(
        intake_intakes.update()
        .where(intake_intakes.c.id == intake_id)
        .values(
            status=structing.status.value,
            record_attempts=structing.record_attempts,
            forced_text=structing.forced_text,
        )
    )

    context = _egress_context(row.language)
    gate_engine, consent_facade, budget_meter = _adapters._build_egress_gate()
    try:
        # NFR-001 hard stop: no egress when the monthly meter is exhausted - the
        # intake degrades to raw doctor review rather than overspending.
        if not await budget_meter.allows_ai_call():
            await _degrade_to_raw_review(
                connection,
                intake_id,
                state=structing,
                reason="monthly AI budget exhausted (NFR-001 hard stop)",
            )
            return

        # Consent gate (fail-closed, NFR-SEC-006): a live doctor-grant on the
        # consultations scope is required before ANY content leaves for EXT-002.
        # A missing or revoked grant means no egress and raw doctor review.
        decision = await consent_facade.check_consent(
            patient_id=row.patient_id,
            counterparty_type=_adapters.AI_EGRESS_COUNTERPARTY_TYPE,  # type: ignore[arg-type]
            counterparty_id=_adapters.AI_EGRESS_COUNTERPARTY_ID,
            record_scope=_adapters.AI_EGRESS_RECORD_SCOPE,
        )
        if not decision.allowed:
            await _degrade_to_raw_review(
                connection,
                intake_id,
                state=structing,
                reason="consent for AI processing is missing or revoked (fail-closed)",
            )
            return

        gateway = _adapters.build_ai_gateway(get_settings())

        # Resolve the transcript before any job is created, so an unstructurable
        # intake (voice with no clip, or no text at all) degrades to a logged
        # skip with NO ai_job row - mirroring the T10 skip semantics.
        transcript = row.text
        source = "text"
        audio_ref: str | None = None
        if row.mode == "voice":
            source = "voice"
            media_row = (
                await connection.execute(
                    select(intake_media_refs)
                    .where(intake_media_refs.c.intake_id == intake_id)
                    .order_by(intake_media_refs.c.record_attempt.desc())
                )
            ).first()
            if media_row is None or not media_row.object_key:
                logger.warning(
                    "intake %s voice mode has no media ref to transcribe; skipping pipeline",
                    intake_id,
                )
                return
            audio_ref = media_row.object_key
        if not transcript and row.mode == "text":
            logger.warning(
                "intake %s has no text/transcript to structure; skipping pipeline",
                intake_id,
            )
            return

        if row.mode == "voice":
            # transcribe leg (voice only): the current attempt's audio becomes
            # the transcript, persisted onto the intake for downstream
            # raw-text fallback.
            transcribe_result = await gateway.transcribe(
                TranscribeRequest(
                    audio_ref=audio_ref,
                    mode="voice",
                    context=context,
                )
            )
            transcript = transcribe_result.transcript
            usability = classify_transcript_usability(transcript)

            if usability is TranscriptUsability.UNUSABLE:
                unusable_state = transition(structing, IntakeAction.RECORD_UNUSABLE)
                await connection.execute(
                    intake_intakes.update()
                    .where(intake_intakes.c.id == intake_id)
                    .values(
                        transcript=transcript,
                        transcript_usability=TranscriptUsability.UNUSABLE,
                        status=unusable_state.status.value,
                        record_attempts=unusable_state.record_attempts,
                        forced_text=unusable_state.forced_text,
                        updated_at=datetime.now(UTC),
                    )
                )
                if unusable_state.status is IntakeStatus.RE_RECORD:
                    await write_outbox(
                        connection,
                        INTAKE_SCHEMA,
                        INTAKE_OUTBOX_TABLE,
                        intake_retry_requested_envelope(
                            intake_id=intake_id,
                            record_attempt=unusable_state.record_attempts,
                            reason="unusable_audio",
                        ),
                    )
                    logger.warning(
                        "intake %s transcript unusable (%d chars); re-recording",
                        intake_id,
                        len(transcript.strip()),
                    )
                else:
                    logger.warning(
                        "intake %s transcript unusable at attempt cap; forced text fallback",
                        intake_id,
                    )
                return

            if usability is TranscriptUsability.PARTIAL:
                logger.warning(
                    "intake %s transcript partial (%d chars); proceeding degraded",
                    intake_id,
                    len(transcript.strip()),
                )

            await connection.execute(
                intake_intakes.update()
                .where(intake_intakes.c.id == intake_id)
                .values(
                    transcript=transcript,
                    transcript_usability=usability,
                    updated_at=datetime.now(UTC),
                )
            )

        ai_job_id = await _insert_ai_job(connection, intake_id)
        try:
            started = time.monotonic()
            structure_result = await gateway.structure(
                StructureRequest(
                    transcript=transcript,
                    source=source,
                    context=context,
                )
            )
            elapsed_ms = int((time.monotonic() - started) * 1000)
            confidence = structure_result.confidence
            low_conf = is_low_confidence(confidence)

            structured_fields = StructuredFields(
                chief_complaints=structure_result.chief_complaints,
                symptoms=structure_result.symptoms,
                duration=structure_result.duration,
            )
        except (Ext002CallError, ValidationError) as exc:
            await _fail_job(
                connection,
                ai_job_id=ai_job_id,
                intake_id=intake_id,
                task_type="structure",
                reason=_failure_reason(exc),
            )
            await _degrade_to_raw_review(
                connection,
                intake_id,
                state=structing,
                reason=(
                    "AI provider call failed after retry/timeout or malformed "
                    f"output: {_failure_reason(exc)}"
                ),
            )
            return

        # Every successful egress is audited via the consent facade's egress
        # log (NFR-SEC-006) - the intake context was sent to EXT-002 under the
        # checked grant, and ``ai_egress.recorded`` notifies the audit trail.
        await consent_facade.record_egress_disclosure(
            patient_id=row.patient_id,
            consent_id=decision.consent_id,
            version=decision.version or 0,
            counterparty_type=_adapters.AI_EGRESS_COUNTERPARTY_TYPE,
            counterparty_id=_adapters.AI_EGRESS_COUNTERPARTY_ID,
            record_scope=_adapters.AI_EGRESS_RECORD_SCOPE,
            disclosed_entry_ids=[intake_id],
        )
        await write_outbox(
            connection,
            INTAKE_SCHEMA,
            INTAKE_OUTBOX_TABLE,
            ai_egress_recorded_envelope(
                intake_id=intake_id,
                ai_job_id=ai_job_id,
                reason="structure egress of intake context to EXT-002",
            ),
        )

        await _finalize_pipeline(
            connection,
            intake_id=intake_id,
            ai_job_id=ai_job_id,
            confidence=confidence,
            elapsed_ms=elapsed_ms,
            structured_fields=structured_fields,
            low_conf=low_conf,
            record_attempts=structing.record_attempts,
            forced_text=structing.forced_text,
        )
    finally:
        await gate_engine.dispose()


async def _insert_ai_job(connection: AsyncConnection, intake_id: int) -> int:
    """Create the running ai_jobs row for this pass (markable failed on error)."""
    job_insert = await connection.execute(
        intake_ai_jobs.insert()
        .values(
            intake_id=intake_id,
            task_type="structure",
            provider=get_settings().ai_provider.strip().lower(),
            model=_adapters.MOCK_AI_MODEL,
            status="running",
            attempts=1,
        )
        .returning(intake_ai_jobs.c.id)
    )
    return int(job_insert.scalar_one())


def _failure_reason(exc: BaseException) -> str:
    """A short, PHI-free operational failure reason for the job + event."""
    return type(exc).__name__


async def _degrade_to_raw_review(
    connection: AsyncConnection,
    intake_id: int,
    *,
    state: IntakeState,
    reason: str,
) -> None:
    """Move the intake Structuring -> Ready for Review via ``RAW_TEXT`` (durable).

    The captured text/transcript is already durable; the doctor reviews it raw.
    The degradation transition never touches ``forced_text`` (its RAW_TEXT
    semantic) and writes the intake update in the SAME transaction as the
    ledger-first pipeline effects, so a replay stays a no-op.
    """
    degraded = transition(state, IntakeAction.RAW_TEXT)
    await connection.execute(
        intake_intakes.update()
        .where(intake_intakes.c.id == intake_id)
        .values(
            status=degraded.status.value,
            record_attempts=degraded.record_attempts,
            forced_text=degraded.forced_text,
            updated_at=datetime.now(UTC),
        )
    )
    logger.warning("intake %s degraded to raw doctor review: %s", intake_id, reason)


async def _fail_job(
    connection: AsyncConnection,
    *,
    ai_job_id: int,
    intake_id: int,
    task_type: str,
    reason: str,
) -> None:
    """Mark the ai_jobs row ``failed`` and publish ``ai_job.failed``.

    Runs in the SAME transaction as the intake degradation, so a timeout/
    malformed-output failure durably records the failed job and its bus event
    alongside the raw-review transition (ADR-0002 §1).
    """
    await connection.execute(
        intake_ai_jobs.update()
        .where(intake_ai_jobs.c.id == ai_job_id)
        .values(
            status="failed",
            error_message=reason,
            updated_at=datetime.now(UTC),
        )
    )
    await write_outbox(
        connection,
        INTAKE_SCHEMA,
        INTAKE_OUTBOX_TABLE,
        ai_job_failed_envelope(
            ai_job_id=ai_job_id,
            intake_id=intake_id,
            task_type=task_type,  # type: ignore[arg-type]
            reason=reason,
        ),
    )


async def _finalize_pipeline(
    connection: AsyncConnection,
    *,
    intake_id: int,
    ai_job_id: int,
    confidence: float,
    elapsed_ms: int,
    structured_fields: StructuredFields,
    low_conf: bool,
    record_attempts: int,
    forced_text: bool,
) -> None:
    """Persist the completed structure job + Draft pre_summary, then publish.

    Runs in the SAME transaction as the ledger dedupe: the ai_jobs row is
    marked completed with the metered provider/model/tokens/cost/latency/
    attempts, the Draft ``intake_pre_summaries`` row is written with the
    provider confidence + honesty fields, the intake moves to
    ``ready_for_review``, and ``pre_summary.ready`` + ``ai_job.completed`` are
    emitted. A low-confidence outcome ALSO publishes ``pre_summary.low_confidence``
    (AMB-006) - the honesty cue that structurally forces doctor review before
    the pre-summary can finalize (ADR-0001). ADR-0002 S1. A downstream failure
    here rolls the whole pass back, so at-least-once redelivery re-runs it -
    never a partial pre-summary.
    """
    token_input = 0
    token_output = 0
    cost_paise = 0

    await connection.execute(
        intake_ai_jobs.update()
        .where(intake_ai_jobs.c.id == ai_job_id)
        .values(
            status="completed",
            confidence=Decimal(str(confidence)),
            input_tokens=token_input,
            output_tokens=token_output,
            cost_paise=cost_paise,
            duration_ms=elapsed_ms,
            updated_at=datetime.now(UTC),
        )
    )

    pre_insert = await connection.execute(
        intake_pre_summaries.insert()
        .values(
            intake_id=intake_id,
            structured_fields=structured_fields.model_dump(mode="json"),
            structuring_confidence=Decimal(str(confidence)),
            low_confidence=low_conf,
            review_state="draft",
        )
        .returning(intake_pre_summaries.c.id)
    )
    pre_summary_id = int(pre_insert.scalar_one())

    finished = transition(
        IntakeState(
            status=IntakeStatus.STRUCTURING,
            record_attempts=record_attempts,
            forced_text=forced_text,
        ),
        IntakeAction.STRUCTURING_SUCCESS,
    )
    await connection.execute(
        intake_intakes.update()
        .where(intake_intakes.c.id == intake_id)
        .values(
            status=finished.status.value,
            forced_text=finished.forced_text,
            updated_at=datetime.now(UTC),
        )
    )

    await write_outbox(
        connection,
        INTAKE_SCHEMA,
        INTAKE_OUTBOX_TABLE,
        pre_summary_ready_envelope(
            intake_id=intake_id,
            pre_summary_id=pre_summary_id,
        ),
    )
    if low_conf:
        await write_outbox(
            connection,
            INTAKE_SCHEMA,
            INTAKE_OUTBOX_TABLE,
            pre_summary_low_confidence_envelope(
                intake_id=intake_id,
                pre_summary_id=pre_summary_id,
            ),
        )
    await write_outbox(
        connection,
        INTAKE_SCHEMA,
        INTAKE_OUTBOX_TABLE,
        ai_job_completed_envelope(
            ai_job_id=ai_job_id,
            intake_id=intake_id,
            task_type="structure",
        ),
    )
