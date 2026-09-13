"""PHASE-7 T14: closed-loop intake capture -> AI pipeline -> doctor review (ticket #358).

Proves the Phase-7 slice end-to-end against a real local PostgreSQL (skipping
cleanly when it is unreachable): submit captures an intake with its
``intake.captured`` outbox event in one transaction (facade seam), the async
structuring pipeline drains the intake outbox through the REAL composition-root
registry + dispatcher poll loop and structures it via the deterministic mock
provider (clean-lown knob), and the doctor review-and-edit finalizes the
pre-summary - proving that the routes-facing facade, outbox writer, dispatcher,
consumer, budget meter and consent gate seams actually connect, not just pass in
isolation (spec #344 testing decisions, "closed loop capture -> pipeline ->
review").

EXT-002 is served by an in-test HTTP stub: the shipping ``OpenAiCompatibleAdapter``
round-trips against a local ``httpx.MockTransport`` server for the
``/audio/transcriptions`` and ``/chat/completions`` contract (``draft_rx``
raises the typed not-supported rejection), so the EXT-002 wire boundary is
answerable without any external network. The closed loop itself uses the mock
provider throughout (deterministic clean confidence).

The consent gate and budget meter are the REAL facades wired by the pipeline's
``_build_egress_gate``: a patient grant is seeded via ``ConsentFacade.grant_consent``
so ``check_consent`` allows (fail-open here deliberately), and the mock AI job
costs 0 paise against the NFR-001 default budget so the meter stays well under
budget (observe-and-warn, PS-10 - exhaustion never blocks anyway).
The pipeline therefore runs the genuine closed loop, and its egress is recorded
in ``consent_egress_log`` (NFR-SEC-006).
"""

from __future__ import annotations

import base64
import json
import logging
import secrets
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from bus.dispatcher import DispatcherConfig, OutboxTable, process_outbox_table
from bus.events import EVENT_PRE_SUMMARY_READY
from modules.consent.facade import ConsentFacade
from modules.intake.adapters.ai_gateway import (
    AiEgressContext,
    DraftRxRequest,
    Ext002CallError,
    StructureRequest,
    TranscribeRequest,
)
from modules.intake.adapters.ai_provider_mock import MOCK_CONFIDENCE_CLEAN
from modules.intake.adapters.ai_provider_openai_compatible import OpenAiCompatibleAdapter
from modules.intake.adapters.media_store import LocalFilesystemIntakeMediaStore
from modules.intake.domain.state_machine import IntakeStatus
from modules.intake.facade import IntakeFacade
from modules.intake.intake_models import MediaUploadRef
from modules.intake.outbox import INTAKE_OUTBOX_TABLE
from worker.main import build_registry

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

INTAKE_SCHEMA = "intake"
INTAKE_GATE_COUNTERPARTY_TYPE = "doctor"
INTAKE_GATE_COUNTERPARTY_ID = "intake-ai"
INTAKE_GATE_RECORD_SCOPE = "consultations"

#: AES-256 key shared by the test media store and the pipeline's per-run store
#: (set via ``INTAKE_MEDIA_KEY``) so a voice clip seeded once decrypts
#: consistently on read. Derived once per session so no key literal is ever
#: committed - the pipeline reads the same env var at runtime.
_MEDIA_KEY_BYTES = secrets.token_bytes(32)
_MEDIA_KEY_B64 = base64.b64encode(_MEDIA_KEY_BYTES).decode()

_INTAKE_TABLES = (
    "intake.intake_outbox",
    "intake.intake_ai_jobs",
    "intake.intake_pre_summaries",
    "intake.intake_media_refs",
    "intake.intake_intakes",
    "intake.consumed_events",
)

_CONSENT_TABLES = (
    "consent.consent_outbox",
    "consent.consent_egress_log",
    "consent.consent_events",
    "consent.consent_consents",
)


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture(scope="module")
def migrated_schema(database_url: str) -> Iterator[None]:
    """Migrate to head (intake + consent + shared deltas) for the module."""
    config = _alembic_config(database_url)
    try:
        command.upgrade(config, "head")
    except Exception as exc:
        pytest.skip(f"PostgreSQL unreachable at {database_url} - {exc}")
    yield
    command.downgrade(config, "base")


@pytest_asyncio.fixture
async def clean_intake_tables(
    database_url: str, migrated_schema: None, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[None]:
    """Empty the intake + consent tables under test and point the worker at the test DB.

    The pipeline's short-lived delivery/gate engines read ``get_settings().database_url``
    (the ``DATABASE_URL`` env), so the closed loop must run against the same database
    the fixture resolved - otherwise capture and structuring would hit different DBs.
    """
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("TRUNCATE TABLE " + ", ".join(_INTAKE_TABLES + _CONSENT_TABLES) + " CASCADE")
            )
    finally:
        await engine.dispose()
    monkeypatch.setenv("DATABASE_URL", database_url)
    yield


async def _query(database_url: str, sql: str) -> list[dict[str, Any]]:
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text(sql))
            return [dict(row) for row in result.mappings().all()]
    finally:
        await engine.dispose()


def _intake_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, poolclass=NullPool)


@pytest.mark.asyncio
async def test_closed_loop_capture_pipeline_review_finalizes_with_mock_provider(
    database_url: str, clean_intake_tables: None
) -> None:
    """The full closed loop: capture -> intake.captured -> pipeline -> review -> final."""
    patient_id = uuid.uuid4().int % (2**53)
    doctor_id = uuid.uuid4().int % (2**53)
    intake_engine = _intake_engine(database_url)
    try:
        intake_facade = IntakeFacade(engine=intake_engine)
        consent_facade = ConsentFacade(engine=intake_engine)

        # Seed the fail-closed consent gate's grant (doctor/intake-ai/consultations).
        grant = await consent_facade.grant_consent(
            patient_id,
            INTAKE_GATE_COUNTERPARTY_TYPE,  # type: ignore[arg-type]
            INTAKE_GATE_COUNTERPARTY_ID,
            INTAKE_GATE_RECORD_SCOPE,
        )
        assert grant.status == "granted"

        # 1. Capture: intake row + intake.captured outbox event commit together.
        submitted = await intake_facade.submit_intake(
            patient_id=patient_id,
            mode="text",
            language="hi",
            text="sir dard hai aur bukhar bhi",
        )
        intake_id = submitted.intake_id
        assert submitted.status == IntakeStatus.CAPTURED.value

        intake_rows = await _query(
            database_url,
            f"SELECT id, status, mode, language FROM intake.intake_intakes WHERE id = {intake_id}",
        )
        assert len(intake_rows) == 1
        box_rows = await _query(
            database_url,
            "SELECT event_id, event_type, status FROM intake.intake_outbox "
            "WHERE status = 'pending'",
        )
        assert any(row["event_type"] == "intake.captured" for row in box_rows)

        # 2. Pipeline: drain the intake outbox through the real composition-root
        #    registry + dispatcher. The mock provider structures at clean confidence.
        registry = build_registry()
        poll_engine = _intake_engine(database_url)
        try:
            result = await process_outbox_table(
                poll_engine,
                OutboxTable(INTAKE_SCHEMA, INTAKE_OUTBOX_TABLE),
                registry,
                DispatcherConfig(),
            )
        finally:
            await poll_engine.dispose()

        assert result.claimed >= 1
        assert result.fanned_out >= 1
        assert result.deleted >= 1

        intake_now = await _query(
            database_url,
            f"SELECT id, status, transcript FROM intake.intake_intakes WHERE id = {intake_id}",
        )
        assert intake_now[0]["status"] == IntakeStatus.READY_FOR_REVIEW.value

        pre_summaries = await _query(
            database_url,
            "SELECT intake_id, review_state, low_confidence, structuring_confidence, "
            "structured_fields FROM intake.intake_pre_summaries",
        )
        assert len(pre_summaries) == 1
        summary = pre_summaries[0]
        assert summary["review_state"] == "draft"
        assert summary["low_confidence"] is False
        assert float(summary["structuring_confidence"]) == pytest.approx(MOCK_CONFIDENCE_CLEAN)
        assert summary["structured_fields"]["chief_complaints"] == ["mock chief complaint"]
        assert summary["structured_fields"]["symptoms"] == ["mock symptom"]
        assert summary["structured_fields"]["duration"] == "1 week"

        ai_jobs = await _query(
            database_url,
            "SELECT task_type, provider, model, status, input_tokens, output_tokens, "
            "cost_paise FROM intake.intake_ai_jobs",
        )
        assert len(ai_jobs) == 1
        assert ai_jobs[0]["task_type"] == "structure"
        assert ai_jobs[0]["provider"] == "mock"
        assert ai_jobs[0]["status"] == "completed"
        assert ai_jobs[0]["model"] == "mock-model"
        assert ai_jobs[0]["input_tokens"] == 0
        assert ai_jobs[0]["output_tokens"] == 0
        assert ai_jobs[0]["cost_paise"] == 0

        egress_rows = await _query(
            database_url,
            f"SELECT patient_id, counterparty_id, record_scope FROM consent.consent_egress_log "
            f"WHERE patient_id = {patient_id}",
        )
        assert len(egress_rows) == 1
        assert egress_rows[0]["counterparty_id"] == INTAKE_GATE_COUNTERPARTY_ID

        # 3. Review: high-confidence clean path - a single attributed review finalizes.
        view = await intake_facade.get_pre_summary(intake_id=intake_id, patient_id=patient_id)
        assert view.review_state == "draft"

        reviewed = await intake_facade.mark_pre_summary_reviewed(
            intake_id=intake_id,
            doctor_id=doctor_id,
            corrections={"duration": "2 weeks"},
        )
        assert reviewed.review_state == "final"
        assert reviewed.review_attribution == "doctor"
        assert reviewed.reviewed_by == doctor_id
        assert reviewed.reviewed_copy["duration"] == "2 weeks"
        assert reviewed.changed_fields == ["duration"]

        reviewed_row = await _query(
            database_url,
            f"SELECT review_state, review_attribution, reviewed_by "
            f"FROM intake.intake_pre_summaries WHERE intake_id = {intake_id}",
        )
        assert reviewed_row[0]["review_state"] == "final"
        assert reviewed_row[0]["review_attribution"] == "doctor"

        ready_events = await _query(
            database_url,
            "SELECT event_type FROM intake.intake_outbox WHERE event_type = 'pre_summary.ready'",
        )
        assert any(row["event_type"] == EVENT_PRE_SUMMARY_READY for row in ready_events)
    finally:
        await intake_engine.dispose()


@pytest.mark.asyncio
async def test_closed_loop_voice_intake_books_transcribe_and_structure_jobs(
    database_url: str,
    clean_intake_tables: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A voice intake runs BOTH legs in the real closed loop, metered + audited
    (T12 #409 over MOD-005).

    The clip is seeded through a real ``LocalFilesystemIntakeMediaStore`` under
    the same root/key the pipeline's per-run store reads (``INTAKE_MEDIA_*``
    env), so the transcribe leg decrypts it like production. Assertions: one
    ``transcribe`` + one ``structure`` job row, both completed with the mock's
    real provider/model and (zero) token/cost metering, and an egress audit row
    for each of the two legs (PS-03, NFR-SEC-006).
    """
    patient_id = uuid.uuid4().int % (2**53)
    intake_engine = _intake_engine(database_url)
    try:
        monkeypatch.setenv("INTAKE_MEDIA_BACKEND", "local")
        monkeypatch.setenv("INTAKE_MEDIA_ROOT", str(tmp_path))
        monkeypatch.setenv("INTAKE_MEDIA_KEY", _MEDIA_KEY_B64)

        store = LocalFilesystemIntakeMediaStore(root=tmp_path, key_bytes=_MEDIA_KEY_BYTES)
        audio_key = await store.save(
            data=b"fake-pcm-audio-bytes-for-closed-loop",
            patient_id=patient_id,
        )
        await store.close()

        intake_facade = IntakeFacade(engine=intake_engine)
        consent_facade = ConsentFacade(engine=intake_engine)

        grant = await consent_facade.grant_consent(
            patient_id,
            INTAKE_GATE_COUNTERPARTY_TYPE,  # type: ignore[arg-type]
            INTAKE_GATE_COUNTERPARTY_ID,
            INTAKE_GATE_RECORD_SCOPE,
        )
        assert grant.status == "granted"

        submitted = await intake_facade.submit_intake(
            patient_id=patient_id,
            mode="voice",
            language="hi",
            media_ref=MediaUploadRef(
                object_key=audio_key,
                media_type="audio",
                audio_duration_ms=5000,
                file_size_bytes=len(b"fake-pcm-audio-bytes-for-closed-loop"),
                record_attempt=1,
            ),
        )
        intake_id = submitted.intake_id
        assert submitted.status == IntakeStatus.CAPTURED.value

        registry = build_registry()
        poll_engine = _intake_engine(database_url)
        try:
            result = await process_outbox_table(
                poll_engine,
                OutboxTable(INTAKE_SCHEMA, INTAKE_OUTBOX_TABLE),
                registry,
                DispatcherConfig(),
            )
        finally:
            await poll_engine.dispose()

        assert result.claimed >= 1
        assert result.fanned_out >= 1
        assert result.deleted >= 1

        intake_now = await _query(
            database_url,
            f"SELECT id, status, transcript FROM intake.intake_intakes WHERE id = {intake_id}",
        )
        assert intake_now[0]["status"] == IntakeStatus.READY_FOR_REVIEW.value
        assert intake_now[0]["transcript"] == "mock transcript"

        ai_jobs = await _query(
            database_url,
            "SELECT task_type, provider, model, status, input_tokens, output_tokens, "
            "cost_paise FROM intake.intake_ai_jobs",
        )
        assert len(ai_jobs) == 2
        jobs_by_task = {row["task_type"]: row for row in ai_jobs}
        assert set(jobs_by_task) == {"transcribe", "structure"}
        for row in ai_jobs:
            assert row["status"] == "completed"
            assert row["provider"] == "mock"
            assert row["model"] == "mock-model"
            assert row["input_tokens"] == 0
            assert row["output_tokens"] == 0
            assert row["cost_paise"] == 0

        egress_rows = await _query(
            database_url,
            f"SELECT patient_id, counterparty_id, record_scope, disclosed_entry_ids "
            f"FROM consent.consent_egress_log WHERE patient_id = {patient_id}",
        )
        assert len(egress_rows) == 2
        assert all(row["counterparty_id"] == INTAKE_GATE_COUNTERPARTY_ID for row in egress_rows)
        assert all(row["record_scope"] == INTAKE_GATE_RECORD_SCOPE for row in egress_rows)
        assert all(row["disclosed_entry_ids"] == [intake_id] for row in egress_rows)

        pre_summaries = await _query(
            database_url,
            "SELECT intake_id, review_state, low_confidence FROM intake.intake_pre_summaries",
        )
        assert len(pre_summaries) == 1
        assert pre_summaries[0]["review_state"] == "draft"
        assert pre_summaries[0]["low_confidence"] is False
    finally:
        await intake_engine.dispose()


@pytest.mark.asyncio
async def test_closed_loop_exhausted_budget_still_completes(
    database_url: str,
    clean_intake_tables: None,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An exhausted NFR-001 meter is observe-and-warn: it never blocks the pipeline
    (T12 #409, post-T11 #408).

    The budget knob is set to a 1-paise cap and a seeded completed job prices
    the month's spend over it, so ``BudgetMeter.allows_ai_call()`` answers
    ``False`` (PS-10, #408). The pipeline must still run the structure leg and
    land the intake at ``ready_for_review`` with a metered job - the advisory
    banner, not a hard stop (spec #344's hard-stop wording was dropped).
    """
    patient_id = uuid.uuid4().int % (2**53)
    intake_engine = _intake_engine(database_url)
    caplog.set_level(logging.WARNING, logger="modules.intake.adapters.pipeline")
    try:
        monkeypatch.setenv("AI_MONTHLY_BUDGET_PAISE", "1")

        intake_facade = IntakeFacade(engine=intake_engine)
        consent_facade = ConsentFacade(engine=intake_engine)

        grant = await consent_facade.grant_consent(
            patient_id,
            INTAKE_GATE_COUNTERPARTY_TYPE,  # type: ignore[arg-type]
            INTAKE_GATE_COUNTERPARTY_ID,
            INTAKE_GATE_RECORD_SCOPE,
        )
        assert grant.status == "granted"

        submitted = await intake_facade.submit_intake(
            patient_id=patient_id,
            mode="text",
            language="hi",
            text="sir dard hai aur bukhar bhi",
        )
        intake_id = submitted.intake_id

        # Price the month over the 1-paise cap with a completed job so the
        # meter reports exhausted before the pipeline runs.
        seeder = create_async_engine(database_url, poolclass=NullPool)
        try:
            async with seeder.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO intake.intake_ai_jobs "
                        "(intake_id, task_type, provider, model, status, cost_paise) "
                        "VALUES (:intake_id, 'structure', 'mock', 'mock-model', "
                        "'completed', :cost_paise)"
                    ),
                    {"intake_id": intake_id, "cost_paise": 10},
                )
        finally:
            await seeder.dispose()

        registry = build_registry()
        poll_engine = _intake_engine(database_url)
        try:
            result = await process_outbox_table(
                poll_engine,
                OutboxTable(INTAKE_SCHEMA, INTAKE_OUTBOX_TABLE),
                registry,
                DispatcherConfig(),
            )
        finally:
            await poll_engine.dispose()

        assert result.claimed >= 1
        assert result.fanned_out >= 1
        assert result.deleted >= 1

        intake_now = await _query(
            database_url,
            f"SELECT id, status FROM intake.intake_intakes WHERE id = {intake_id}",
        )
        assert intake_now[0]["status"] == IntakeStatus.READY_FOR_REVIEW.value

        ai_jobs = await _query(
            database_url,
            "SELECT task_type, provider, status, input_tokens, output_tokens, cost_paise "
            "FROM intake.intake_ai_jobs ORDER BY cost_paise",
        )
        assert len(ai_jobs) == 2
        assert [row["cost_paise"] for row in ai_jobs] == [0, 10]
        assert all(row["status"] == "completed" for row in ai_jobs)

        assert any(
            "monthly AI budget exhausted" in record.message
            for record in caplog.records
            if record.name == "modules.intake.adapters.pipeline"
        )
    finally:
        await intake_engine.dispose()


@pytest.mark.asyncio
async def test_openai_compatible_http_stub_serves_the_provider_contract(database_url: str) -> None:
    """EXT-002 is served by an HTTP stub: the wire boundary round-trips locally (T12 #409).

    The stub answers the OpenAI-compatible endpoint shapes the shipping
    adapter posts to - ``/audio/transcriptions`` (multipart, with a
    ``x_groq.usage`` block) and ``/chat/completions`` (top-level ``usage``) - so
    the metered token counts real providers report flow off the wire onto the
    ``TranscribeResult``/``StructureResult`` (PS-01, #398).
    """
    del database_url

    def _stub(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/audio/transcriptions":
            return httpx.Response(
                200,
                json={
                    "text": "mujhe bukhar hai",
                    "language": "hi",
                    # Vendor-specific usage block (Groq-style): the transcription
                    # usage extraction path reads ``x_groq.usage`` when there is
                    # no top-level ``usage``.
                    "x_groq": {"usage": {"prompt_tokens": 42, "completion_tokens": 7}},
                },
            )
        if request.url.path == "/chat/completions":
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "chief_complaints": ["bukhar"],
                                        "symptoms": ["sirdard"],
                                        "duration": "1 week",
                                        "confidence": 0.8,
                                    }
                                )
                            }
                        }
                    ],
                    "usage": {"prompt_tokens": 120, "completion_tokens": 30},
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(_stub)
    client = httpx.AsyncClient(transport=transport)
    provider = OpenAiCompatibleAdapter(
        api_key="test-key",
        base_url="https://ext002.local",
        model="test-model",
        client=client,
        max_retries=1,
    )
    context = AiEgressContext(language="hi")
    try:
        transcribed = await provider.transcribe(
            TranscribeRequest(
                audio_ref="intake/abc",
                audio_bytes=b"fake-pcm-audio-bytes",
                mode="voice",
                context=context,
            )
        )
        structured = await provider.structure(
            StructureRequest(transcript="sir dard hai", source="text", context=context)
        )
        with pytest.raises(Ext002CallError, match="not supported"):
            await provider.draft_rx(
                DraftRxRequest(
                    doctor_input_ref="voice_note/1",
                    pre_summary_ref="pre_summary/2",
                    patient_history_summary="mock history",
                    context=context,
                )
            )
    finally:
        await client.aclose()

    assert transcribed.transcript == "mujhe bukhar hai"
    assert transcribed.language == "hi"
    assert transcribed.confidence == MOCK_CONFIDENCE_CLEAN
    assert transcribed.input_tokens == 42
    assert transcribed.output_tokens == 7
    assert structured.chief_complaints == ["bukhar"]
    assert structured.duration == "1 week"
    assert structured.input_tokens == 120
    assert structured.output_tokens == 30
