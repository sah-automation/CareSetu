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

EXT-002 is served by an in-test HTTP stub: the real ``Ext002AiProvider`` HTTP
adapter round-trips against a local ``httpx.MockTransport`` server for the
``/v1/transcribe``, ``/v1/structure`` and ``/v1/draft-rx`` contract, so the
EXT-002 wire boundary is answerable without any external network. The closed
loop itself uses the mock provider throughout (deterministic clean confidence).

The consent gate and budget meter are the REAL facades wired by the pipeline's
``_build_egress_gate``: a patient grant is seeded via ``ConsentFacade.grant_consent``
so ``check_consent`` allows (fail-open here deliberately), and the mock AI job
costs 0 paise against the NFR-001 default budget so the hard stop never trips.
The pipeline therefore runs the genuine closed loop, and its egress is recorded
in ``consent_egress_log`` (NFR-SEC-006).
"""

from __future__ import annotations

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
    StructureRequest,
    TranscribeRequest,
)
from modules.intake.adapters.ai_provider_ext import Ext002AiProvider
from modules.intake.adapters.ai_provider_mock import MOCK_CONFIDENCE_CLEAN
from modules.intake.domain.state_machine import IntakeStatus
from modules.intake.facade import IntakeFacade
from modules.intake.outbox import INTAKE_OUTBOX_TABLE
from worker.main import build_registry

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

INTAKE_SCHEMA = "intake"
INTAKE_GATE_COUNTERPARTY_TYPE = "doctor"
INTAKE_GATE_COUNTERPARTY_ID = "intake-ai"
INTAKE_GATE_RECORD_SCOPE = "consultations"

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
            "SELECT task_type, provider, model, status FROM intake.intake_ai_jobs",
        )
        assert len(ai_jobs) == 1
        assert ai_jobs[0]["task_type"] == "structure"
        assert ai_jobs[0]["provider"] == "mock"
        assert ai_jobs[0]["status"] == "completed"

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
async def test_ext002_http_stub_serves_the_provider_contract(database_url: str) -> None:
    """EXT-002 is served by an HTTP stub: the wire boundary round-trips locally."""
    del database_url

    def _stub(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/transcribe":
            return httpx.Response(
                200,
                json={"transcript": "mujhe bukhar hai", "confidence": 0.8, "language": "hi"},
            )
        if request.url.path == "/v1/structure":
            return httpx.Response(
                200,
                json={
                    "chief_complaints": ["bukhar"],
                    "symptoms": ["sirdard"],
                    "duration": "1 week",
                    "confidence": 0.8,
                },
            )
        if request.url.path == "/v1/draft-rx":
            return httpx.Response(
                200,
                json={
                    "rx_items": [{"name": "dolo", "dose": "650mg", "duration": "3 days"}],
                    "confidence": 0.8,
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(_stub)
    client = httpx.AsyncClient(transport=transport)
    provider = Ext002AiProvider(
        api_key="test-key",
        base_url="https://ext002.local",
        client=client,
        max_retries=1,
    )
    context = AiEgressContext(language="hi")
    try:
        transcribed = await provider.transcribe(
            TranscribeRequest(audio_ref="intake/abc", mode="voice", context=context)
        )
        structured = await provider.structure(
            StructureRequest(transcript="sir dard hai", source="text", context=context)
        )
        drafted = await provider.draft_rx(
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
    assert transcribed.confidence == MOCK_CONFIDENCE_CLEAN
    assert structured.chief_complaints == ["bukhar"]
    assert structured.duration == "1 week"
    assert len(drafted.rx_items) == 1
    assert drafted.rx_items[0].name == "dolo"
