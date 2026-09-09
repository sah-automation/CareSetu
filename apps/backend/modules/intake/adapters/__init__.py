"""MOD-005: event handlers for the ``intake`` module (coding-standards §2).

``register_handlers`` is the composition-root seam (PHASE-1 T4, #30):
the worker entrypoint calls it to register this module's handlers on
the shared ``HandlerRegistry``. PHASE-7 T04 (#349) freezes the module's
event set: it owns the producer payload models for every intake /
pre-summary / AI job event it publishes (the producer owns the model, cf.
notify's ``register_payload_model``) so a claimed ``intake_outbox`` row is
reconstructed with a typed payload before fan-out, and it registers the
module's two self-subscriptions from the §4.2 registry - ``intake.captured``
(self-trigger for the async AI pipeline) and ``intake.retry_requested``
(re-record flow). The re-record body lands in T08; the pipeline happy path
(structuring + pre-summary publish) lands here in T10 (#354).

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

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from bus.envelope import Envelope
from bus.events import (
    EVENT_AI_EGRESS_RECORDED,
    EVENT_AI_JOB_COMPLETED,
    EVENT_AI_JOB_FAILED,
    EVENT_INTAKE_CAPTURED,
    EVENT_INTAKE_RETRY_REQUESTED,
    EVENT_PRE_SUMMARY_LOW_CONFIDENCE,
    EVENT_PRE_SUMMARY_READY,
)
from bus.handler_harness import run_handler
from bus.outbox_writer import write_outbox
from bus.registry import HandlerRegistry
from modules.consent.facade import ConsentFacade
from modules.intake.adapters.ai_gateway import (
    AiEgressContext,
    StructureRequest,
    TranscribeRequest,
)
from modules.intake.adapters.ai_provider_ext import Ext002CallError, build_ai_gateway
from modules.intake.budget_meter import BudgetMeter
from modules.intake.domain.events import (
    AiEgressRecordedPayload,
    AiJobCompletedPayload,
    AiJobFailedPayload,
    IntakeCapturedPayload,
    IntakeRetryRequestedPayload,
    PreSummaryLowConfidencePayload,
    PreSummaryReadyPayload,
    ai_egress_recorded_envelope,
    ai_job_completed_envelope,
    ai_job_failed_envelope,
    pre_summary_low_confidence_envelope,
    pre_summary_ready_envelope,
)
from modules.intake.domain.presummary_machine import is_low_confidence
from modules.intake.domain.state_machine import (
    IntakeAction,
    IntakeState,
    IntakeStatus,
    transition,
)
from modules.intake.facade import INTAKE_SCHEMA
from modules.intake.outbox import INTAKE_OUTBOX_TABLE
from modules.intake.schema.models import (
    intake_ai_jobs,
    intake_intakes,
    intake_media_refs,
    intake_pre_summaries,
)

logger = logging.getLogger(__name__)

#: Mock EXT-002 model identifier recorded on the ai_jobs row (phase0-model
#: convention ``{provider}-model``). The real model is provider-selected in
#: T11/staging; the mock is deterministic with no real model name.
MOCK_AI_MODEL = "mock-model"

#: Egress patient-context placeholders until profile sourcing lands in T11.
#: ``AiEgressContext`` requires age_range/sex, which the intake schema does not
#: yet persist and no module currently sources; the intake row's declared
#: language is real. Isolated here so T11 swaps real patient-profile sourcing
#: without touching the pipeline (NFR-SEC-006).
DEFAULT_EGRESS_AGE_RANGE = "30-40"
DEFAULT_EGRESS_SEX = "other"

#: The consent gate the intake AI egress is authorised under (NFR-SEC-006).
#: The AI drafts a clinical pre-summary for the treating doctor, so the egress
#: rides the patient's live doctor-grant on the ``consultations`` scope
#: (``full_record`` subsumes it). No specific doctor is attached to an intake at
#: capture, so the counterparty id is the stable AI-processing identity the
#: patient's consent log and the egress audit cite.
AI_EGRESS_COUNTERPARTY_TYPE = "doctor"
AI_EGRESS_COUNTERPARTY_ID = "intake-ai"
AI_EGRESS_RECORD_SCOPE = "consultations"


def _egress_context(language: str) -> AiEgressContext:
    """Build the PHI-minimized egress context from the intake row.

    ``language`` is real (declared at capture); ``age_range``/``sex`` are
    placeholder defaults until the patient-profile source lands (T11). The
    context is the only patient-shaped data allowed to cross to EXT-002
    (NFR-SEC-006) - never name/phone/full record.
    """
    return AiEgressContext(
        language=language,
        age_range=DEFAULT_EGRESS_AGE_RANGE,
        sex=DEFAULT_EGRESS_SEX,
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


def register_handlers(registry: HandlerRegistry) -> None:
    """Register the intake module's event payload models + self-subscriptions.

    MOD-005 owns the producer payload models for its own published events; the
    dispatcher reconstructs a claimed ``intake_outbox`` row with each before
    fan-out. The two §4.2 self-subscriptions (MOD-005 -> MOD-005 self) are
    ``intake.captured`` (the async AI pipeline happy path, T10 #354) and
    ``intake.retry_requested`` (the re-record body, T08).
    """
    for event_type, payload_model in (
        (EVENT_INTAKE_CAPTURED, IntakeCapturedPayload),
        (EVENT_INTAKE_RETRY_REQUESTED, IntakeRetryRequestedPayload),
        (EVENT_PRE_SUMMARY_READY, PreSummaryReadyPayload),
        (EVENT_PRE_SUMMARY_LOW_CONFIDENCE, PreSummaryLowConfidencePayload),
        (EVENT_AI_JOB_COMPLETED, AiJobCompletedPayload),
        (EVENT_AI_JOB_FAILED, AiJobFailedPayload),
        (EVENT_AI_EGRESS_RECORDED, AiEgressRecordedPayload),
    ):
        registry.register_payload_model(event_type, payload_model)

    registry.register(EVENT_INTAKE_CAPTURED, _on_intake_captured)
    registry.register(EVENT_INTAKE_RETRY_REQUESTED, _on_intake_retry_requested)


async def _on_intake_captured(envelope: Envelope[BaseModel]) -> None:
    """Consume ``intake.captured``: run the async AI structuring pipeline.

    Ledger first (``run_handler``), pipeline second, one transaction boundary.
    A redelivered ``event_id`` finds its ledger row and skips (at-least-once -
    exactly one pre-summary per captured event). The pipeline never raises a
    user-visible error: a missing or non-structurable intake degrades to a
    logged skip.
    """

    async def _impl(connection: AsyncConnection, payload: IntakeCapturedPayload) -> None:
        await _run_structuring_pipeline(connection, payload.intake_id)

    await run_handler(
        envelope,
        IntakeCapturedPayload,
        _impl,
        "intake_structuring_pipeline",
        INTAKE_SCHEMA,
    )


async def _on_intake_retry_requested(envelope: Envelope[BaseModel]) -> None:
    """Re-record flow seam (T08 #352). Registered here for the composition root."""

    async def _impl(connection: AsyncConnection, payload: IntakeRetryRequestedPayload) -> None:
        del connection, payload

    await run_handler(
        envelope,
        IntakeRetryRequestedPayload,
        _impl,
        "intake_retry_requested",
        INTAKE_SCHEMA,
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
    gate_engine, consent_facade, budget_meter = _build_egress_gate()
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
            counterparty_type=AI_EGRESS_COUNTERPARTY_TYPE,  # type: ignore[arg-type]
            counterparty_id=AI_EGRESS_COUNTERPARTY_ID,
            record_scope=AI_EGRESS_RECORD_SCOPE,
        )
        if not decision.allowed:
            await _degrade_to_raw_review(
                connection,
                intake_id,
                state=structing,
                reason="consent for AI processing is missing or revoked (fail-closed)",
            )
            return

        gateway = build_ai_gateway(get_settings())

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

        ai_job_id = await _insert_ai_job(connection, intake_id)
        try:
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
                await connection.execute(
                    intake_intakes.update()
                    .where(intake_intakes.c.id == intake_id)
                    .values(
                        transcript=transcript,
                        transcript_usability="usable",
                        updated_at=datetime.now(UTC),
                    )
                )

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

            structured_fields: dict[str, object] = {
                "chief_complaints": structure_result.chief_complaints,
                "symptoms": structure_result.symptoms,
                "duration": structure_result.duration,
            }
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
            counterparty_type=AI_EGRESS_COUNTERPARTY_TYPE,
            counterparty_id=AI_EGRESS_COUNTERPARTY_ID,
            record_scope=AI_EGRESS_RECORD_SCOPE,
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
            model=MOCK_AI_MODEL,
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
    structured_fields: dict[str, object],
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
            structured_fields=structured_fields,
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
