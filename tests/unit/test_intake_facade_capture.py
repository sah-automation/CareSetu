"""PHASE-7 T07: IntakeFacade capture seam (ticket #351, spec #344).

Drives the intake capture facade through a mocked engine, mirroring the
partner registration sub-facade direct-seam suite
(``test_partner_facade_register.py``). Pins the capture contract at the
facade-with-fakes seam:

- ``submit_intake`` commits the intake row and the ``intake.started`` +
  ``intake.captured`` outbox rows in the SAME transaction - the outbox writes go
  through ``write_outbox`` on the same connection as the intake insert
  (ADR-0002 S1), so a crash between state change and dispatch cannot lose the
  events (accepted criterion 1). ``intake.started`` is the PHASE-7 T05 #369
  funnel-telemetry ride-along (patient id + mode + language) written ahead of
  ``intake.captured`` to preserve funnel ordering.
- One-mode-per-intake and the text cap (2000 chars) are enforced
  server-side with typed errors (accepted criterion 2). Text mode also accepts
  an optional doctor-only ``media_ref`` voice note (T17 brief, #373) that is
  persisted to ``intake_media_refs`` and never fed to transcription.
- ``get_intake`` / ``get_pre_summary`` return the agreed DTO shapes:
  status from the state machine, honesty (``low_confidence``) fields
  present (accepted criterion 3).
- ``request_rx_draft`` is the live Phase 8 drafting seam (PHASE-8 T05,
  #421): it resolves the intake language, delegates to the AI gateway
  ``draft_rx`` leg, and returns the typed ``RxDraftResult`` (accepted
  criterion 4). Since B4 (#722) the seam also METERS that call: a ``draft``
  ``ai_jobs`` row is booked before the provider call and finalized with the
  serving provider/model, tokens, paise cost and duration, publishing
  ``ai_job.completed`` - or, on a provider failure, ``ai_job.failed`` - on the
  same transaction, so the drafting leg's spend is countable like the
  transcription and structuring legs (PS-03). A draft whose intake cannot be
  read fails closed rather than spending tokens off the meter. Capture
  durability is structural - the row + outbox event
  commit in one local transaction, so a later AI failure never rolls
  back the intake (accepted criterion 5).
- ``record_composer_opened`` is the funnel's real ENTRY step (B4e #721): it
  writes one ``intake.composer_opened`` outbox row in its own transaction and
  nothing else - no intake row, no media ref, no clinical content - so a patient
  who opens the composer and abandons is still countable. ``intake.started`` is
  untouched and still fires at capture time.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.sql.dml import Insert, Update
from sqlalchemy.sql.selectable import Select

from modules.intake.adapters.ai_gateway import (
    DraftRxRequest,
    DraftRxResult,
    Ext002CallError,
    RxItem,
)
from modules.intake.adapters.ai_provider_mock import MockAiProvider
from modules.intake.domain.events import (
    EVENT_AI_JOB_COMPLETED,
    EVENT_AI_JOB_FAILED,
    EVENT_AI_JOB_QUEUED,
    EVENT_INTAKE_CAPTURED,
    EVENT_INTAKE_COMPOSER_OPENED,
    EVENT_INTAKE_STARTED,
    IntakeCapturedPayload,
    IntakeComposerOpenedPayload,
    IntakeStartedPayload,
)
from modules.intake.domain.exceptions import (
    IntakeNotFoundError,
    IntakeValidationError,
)
from modules.intake.facade import IntakeFacade
from modules.intake.intake_models import (
    IntakeDetailView,
    MediaUploadRef,
    PreSummaryView,
    RxDraftItem,
    StructuredFields,
)
from modules.intake.pricing import compute_cost_paise, resolve_pricing_table
from modules.intake.schema.models import (
    intake_intakes,
    intake_media_refs,
)

NOW = datetime.now(UTC)


def _media_ref(*, object_key: str = "intake/abc-123", duration_ms: int = 90_000) -> MediaUploadRef:
    return MediaUploadRef(
        object_key=object_key,
        media_type="audio",
        audio_duration_ms=duration_ms,
        file_size_bytes=1_024_000,
        record_attempt=1,
    )


class _FakeResult:
    """Mimics ``Insert``/``Select`` result shapes: ``scalar_one``, ``first``, ``all``."""

    def __init__(
        self,
        scalar: object | None = None,
        row: object | None = None,
        rows: list[object] | None = None,
    ) -> None:
        self._scalar = scalar
        self._row = row
        self._rows = rows or []

    def scalar_one(self) -> object:
        return self._scalar

    def scalar_one_or_none(self) -> object:
        return self._scalar

    def first(self) -> object:
        return self._row

    def all(self) -> list:
        return self._rows


def _connection(execute_results: list[object]) -> AsyncMock:
    connection = AsyncMock()
    connection.execute = AsyncMock(side_effect=execute_results)
    return connection


def _engine(connection: AsyncMock) -> AsyncMock:
    engine = AsyncMock(spec=AsyncEngine)
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=connection)
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    return engine


def _commit_probing_engine(connection: AsyncMock) -> AsyncMock:
    """Like :func:`_engine`, but records how the transaction block exited.

    A clean exit commits, an exception rolls back - without this a test cannot
    tell a durably written job row from one the escaping error undid, which is
    exactly the distinction a failed-but-metered draft turns on.
    """

    async def _exit(exc_type: object, exc: object, tb: object) -> bool:
        connection.rolled_back = exc_type is not None
        return False

    engine = AsyncMock(spec=AsyncEngine)
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=connection)
    engine.begin.return_value.__aexit__ = AsyncMock(side_effect=_exit)
    return engine


def _facade(connection: AsyncMock) -> IntakeFacade:
    return IntakeFacade(engine=_engine(connection))


def _inserts(connection: AsyncMock) -> list[Insert]:
    return [
        call.args[0]
        for call in connection.execute.await_args_list
        if isinstance(call.args[0], Insert)
    ]


def _insert_params(inserts: list[Insert], table_name: str) -> dict[str, object] | None:
    for stmt in inserts:
        if stmt.table.name == table_name:
            return dict(stmt.compile().params)
    return None


def _intake_row(*, intake_id: int = 1, patient_id: int = 7, status: str = "captured") -> object:
    return SimpleNamespace(
        id=intake_id,
        patient_id=patient_id,
        mode="text",
        language="en",
        status=status,
        record_attempts=1,
        text="headache for two days",
        transcript=None,
        transcript_usability=None,
        forced_text=False,
        created_at=NOW,
        updated_at=NOW,
    )


def _media_row(*, media_ref_id: int = 11, intake_id: int = 1) -> object:
    return SimpleNamespace(
        id=media_ref_id,
        intake_id=intake_id,
        media_type="audio",
        object_key="intake/abc-123",
        audio_duration_ms=90_000,
        file_size_bytes=1_024_000,
        record_attempt=1,
    )


def _pre_summary_row(*, pre_summary_id: int = 5, intake_id: int = 1) -> object:
    return SimpleNamespace(
        id=pre_summary_id,
        intake_id=intake_id,
        structured_fields={"symptoms": ["headache"], "severity": "mild"},
        structuring_confidence=0.82,
        low_confidence=False,
        review_state="draft",
        patient_edits=None,
        doctor_corrections=None,
        review_attribution=None,
        reviewed_by=None,
        reviewed_at=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _intake_id_result(intake_id: int = 42) -> _FakeResult:
    return _FakeResult(scalar=intake_id)


def _outbox_result() -> _FakeResult:
    return _FakeResult(scalar=None)


def _outbox_inserts(connection: AsyncMock) -> list[Insert]:
    return [
        call.args[0]
        for call in connection.execute.await_args_list
        if isinstance(call.args[0], Insert) and call.args[0].table.name == "intake_outbox"
    ]


def _outbox_array(connection: AsyncMock, event_type: str) -> Insert | None:
    for stmt in _outbox_inserts(connection):
        if stmt.compile().params["event_type"] == event_type:
            return stmt
    return None


# ---------------------------------------------------------------------------
# Draft metering harness (B4 #722)
# ---------------------------------------------------------------------------


class _Recorded:
    """One executed statement with its compiled params, for read-back assertions."""

    def __init__(self, kind: str, statement: object) -> None:
        self.kind = kind
        self.statement = statement
        self.params = dict(statement.compile().params)


class _DraftMeteringConnection:
    """Records the drafting seam's writes so a test can read the meter back.

    ``_connection`` above scripts results by call order, which cannot say what the
    seam WROTE. This recorder answers the two selects the seam reads, hands back a
    fresh job id for the ``ai_jobs`` insert, and classifies every statement the
    seam executes - booking, finalization and outbox event - so the assertions run
    against the real SQLAlchemy statements rather than a parallel fiction.
    """

    def __init__(self, *, ai_job_id: int = 42) -> None:
        self._ai_job_id = ai_job_id
        self.executed: list[_Recorded] = []
        self.rolled_back = False

    async def execute(self, statement: object) -> _FakeResult:
        if isinstance(statement, Insert):
            table = statement.table.name
            if table == "intake_ai_jobs":
                self.executed.append(_Recorded("insert_ai_job", statement))
                job_id = self._ai_job_id
                self._ai_job_id += 1
                return _FakeResult(scalar=job_id)
            if table == "intake_outbox":
                self.executed.append(_Recorded("outbox", statement))
                return _FakeResult()
            self.executed.append(_Recorded("insert_other", statement))
            return _FakeResult()
        if isinstance(statement, Update):
            self.executed.append(
                _Recorded(
                    "update_ai_job" if statement.table.name == "intake_ai_jobs" else "update_other",
                    statement,
                )
            )
            return _FakeResult()
        if isinstance(statement, Select):
            froms = statement.get_final_froms()
            table = getattr(froms[0], "name", None) if froms else None
            self.executed.append(_Recorded(f"select_{table}", statement))
            if table == "intake_pre_summaries":
                return _FakeResult(row=_pre_summary_row(pre_summary_id=5, intake_id=1))
            if table == "intake_intakes":
                return _FakeResult(row=_intake_row(intake_id=1, patient_id=7))
            return _FakeResult(row=None)
        self.executed.append(_Recorded("other", statement))
        return _FakeResult()

    def _statements(self, kind: str) -> list[dict[str, object]]:
        return [r.params for r in self.executed if r.kind == kind]

    def ai_job_booking(self) -> dict[str, object]:
        return self._statements("insert_ai_job")[0]

    def ai_job_update(self) -> dict[str, object]:
        return self._statements("update_ai_job")[0]

    def outbox_types(self) -> list[str]:
        return [r.params["event_type"] for r in self.executed if r.kind == "outbox"]

    def outbox_payload(self, event_type: str) -> dict[str, object]:
        for record in self.executed:
            if record.kind == "outbox" and record.params["event_type"] == event_type:
                payload: dict[str, object] = record.params["payload"]
                return payload
        raise AssertionError(f"no {event_type} event was published")


class _UsageReportingGateway:
    """A ``draft_rx`` stub that reports real usage, or raises, like a provider.

    ``MockAiProvider`` reports zero tokens (it is the free, deterministic default),
    so the pricing assertion needs a gateway that behaves like a paid one.
    """

    def __init__(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        error: BaseException | None = None,
    ) -> None:
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens
        self._error = error

    @property
    def effective_provider(self) -> str:
        return "paid-provider"

    @property
    def effective_model(self) -> str:
        return "mock-model"

    async def draft_rx(self, request: DraftRxRequest) -> DraftRxResult:
        if self._error is not None:
            raise self._error
        return DraftRxResult(
            rx_items=[RxItem(name="paid medication", dose="1 tablet", duration="5 days")],
            confidence=0.91,
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
        )


@pytest.mark.asyncio
async def test_record_composer_opened_writes_only_the_entry_event_in_its_own_transaction() -> None:
    """The funnel entry is an arrival fact: one outbox row, no clinical write.

    There is no intake row, no media ref and nothing else on this path - the
    patient has opened a screen and typed nothing, so the seam must not invent a
    capture. One ``engine.begin()`` proves the event rides its own transaction
    rather than joining a capture that may never happen (ADR-0002 S1).
    """
    connection = _connection([_outbox_result()])
    facade = _facade(connection)

    await facade.record_composer_opened(patient_id=7, trace_id="a" * 32)

    facade._engine.begin.assert_called_once()
    outboxes = _outbox_inserts(connection)
    assert [stmt.compile().params["event_type"] for stmt in outboxes] == [
        EVENT_INTAKE_COMPOSER_OPENED
    ]
    # Nothing beyond the outbox row: an opened composer must not create an
    # intake, a media ref, a pre-summary or an AI job.
    assert _inserts(connection) == outboxes


@pytest.mark.asyncio
async def test_record_composer_opened_keys_the_event_on_the_patient_and_the_trace_scope() -> None:
    """The payload is the patient plus the platform's trace-context session scope.

    ``session_key`` and ``trace_id`` coincide today because the platform's only
    session scope is the request - the full derivation and its limits are set out
    on ``IntakeComposerOpenedPayload``; both are carried so the product ledger's
    two columns keep their own meanings.
    """
    connection = _connection([_outbox_result()])
    facade = _facade(connection)

    await facade.record_composer_opened(patient_id=7, trace_id="a" * 32)

    stmt = _outbox_array(connection, EVENT_INTAKE_COMPOSER_OPENED)
    assert stmt is not None
    payload = IntakeComposerOpenedPayload.model_validate(stmt.compile().params["payload"])
    assert payload.patient_id == 7
    assert payload.session_key == "a" * 32
    assert payload.trace_id == "a" * 32


@pytest.mark.asyncio
async def test_submit_intake_still_writes_intake_started_at_capture_time() -> None:
    """``intake.started`` is retained unchanged and is NOT the funnel's entry.

    #721 keeps this event exactly where it was - on the capture transaction,
    with its existing payload - and only stops calling it the funnel's entry
    step. A composer-opened publish and a capture publish therefore write two
    different event types, and capture alone still writes ``intake.started``.
    """
    connection = _connection(
        [
            _outbox_result(),
            _intake_id_result(intake_id=9),
            _outbox_result(),
            _outbox_result(),
        ]
    )
    facade = _facade(connection)

    await facade.record_composer_opened(patient_id=7, trace_id="a" * 32)
    await facade.submit_intake(patient_id=7, mode="text", language="hi", text="sir dard hai")

    published = [stmt.compile().params["event_type"] for stmt in _outbox_inserts(connection)]
    assert published == [
        EVENT_INTAKE_COMPOSER_OPENED,
        EVENT_INTAKE_STARTED,
        EVENT_INTAKE_CAPTURED,
    ]
    # The retained event keeps its existing payload shape - no session key, no
    # trace id bolted on - so nothing downstream of #369 has to change.
    started = IntakeStartedPayload.model_validate(
        _outbox_array(connection, EVENT_INTAKE_STARTED).compile().params["payload"]  # type: ignore[union-attr]
    )
    assert set(started.model_dump(mode="json")) == {"patient_id", "mode", "language"}


@pytest.mark.asyncio
async def test_submit_intake_commits_row_and_captured_outbox_in_one_transaction() -> None:
    """The intake insert and both outbox writes (started + captured) share a connection."""
    connection = _connection([_intake_id_result(intake_id=42), _outbox_result(), _outbox_result()])
    facade = _facade(connection)

    result = await facade.submit_intake(
        patient_id=7,
        mode="text",
        language="hi",
        text="sir dard hai",
    )

    assert result.intake_id == 42
    assert result.status == "captured"
    # Exactly one engine transaction was opened for the whole submit.
    engine = facade._engine
    engine.begin.assert_called_once()
    # The intake row was inserted with the captured lifecycle state.
    intake_params = _insert_params(_inserts(connection), intake_intakes.name)
    assert intake_params is not None
    assert intake_params["mode"] == "text"
    assert intake_params["language"] == "hi"
    assert intake_params["status"] == "captured"
    assert intake_params["record_attempts"] == 1
    assert intake_params["forced_text"] is False


@pytest.mark.asyncio
async def test_submit_intake_writes_started_then_captured_envelope_in_one_transaction() -> None:
    """``intake.started`` (funnel) and ``intake.captured`` ride the same outbox write."""
    connection = _connection(
        [
            _intake_id_result(intake_id=9),
            _FakeResult(scalar=None),
            _outbox_result(),
            _outbox_result(),
        ]
    )
    facade = _facade(connection)

    await facade.submit_intake(
        patient_id=7,
        mode="voice",
        language="en",
        media_ref=_media_ref(),
    )

    # The zero-cost assertion: both outbox writes passed the same connection,
    # the intake schema, the outbox table name, and typed envelopes - started
    # first (funnel order), captured second, exactly like the PRD trail.
    outboxes = _outbox_inserts(connection)
    assert [stmt.compile().params["event_type"] for stmt in outboxes] == [
        EVENT_INTAKE_STARTED,
        EVENT_INTAKE_CAPTURED,
    ]
    started = IntakeStartedPayload.model_validate(outboxes[0].compile().params["payload"])
    assert started.patient_id == 7
    assert started.mode == "voice"
    assert started.language == "en"
    captured = IntakeCapturedPayload.model_validate(outboxes[1].compile().params["payload"])
    assert captured.intake_id == 9


@pytest.mark.asyncio
async def test_submit_intake_writes_the_captured_envelope_through_write_outbox() -> None:
    """The outbox write is a real ``intake.captured`` envelope, not a raw row."""
    connection = _connection(
        [
            _intake_id_result(intake_id=9),
            _FakeResult(scalar=None),
            _outbox_result(),
            _outbox_result(),
        ]
    )
    facade = _facade(connection)

    await facade.submit_intake(
        patient_id=7,
        mode="voice",
        language="en",
        media_ref=_media_ref(),
    )

    # The zero-cost assertion: the write_outbox contract passed the same
    # connection, the intake schema, the outbox table name, and an envelope
    # carrying the captured event type + intake id (accepted criterion 1).
    calls = [
        call for call in connection.execute.await_args_list if isinstance(call.args[0], Insert)
    ]
    # Four inserts: intake row, media-ref row (voice attach), and the two
    # outbox rows (started + captured).
    assert len(calls) == 4
    captured_write = _outbox_array(connection, EVENT_INTAKE_CAPTURED)
    assert captured_write is not None
    values = captured_write.compile().params
    assert values["event_type"] == EVENT_INTAKE_CAPTURED
    assert values["status"] == "pending"
    payload = IntakeCapturedPayload.model_validate(values["payload"])
    assert payload.intake_id == 9


@pytest.mark.asyncio
async def test_submit_intake_text_mode_accepts_optional_doctor_only_media_ref() -> None:
    """A text-mode intake may carry a doctor-only voice note (T17 brief, #373).

    The note rides with the typed symptoms: the ``media_ref`` is persisted as
    an ``intake_media_refs`` row alongside the intake (exactly like the voice
    attach), so the doctor hears it on review. It is never transcribed - the
    pipeline's mode gate only reads ``mode == "voice"`` clips.
    """
    connection = _connection(
        [
            _intake_id_result(intake_id=42),
            _FakeResult(scalar=None),
            _outbox_result(),
            _outbox_result(),
        ]
    )
    facade = _facade(connection)

    result = await facade.submit_intake(
        patient_id=7,
        mode="text",
        language="en",
        text="sir dard hai, aage bol raha hoon",
        media_ref=_media_ref(),
    )

    assert result.intake_id == 42
    assert result.status == "captured"
    # The media ref is persisted into intake_media_refs with the intake's id.
    ref_params = _insert_params(_inserts(connection), intake_media_refs.name)
    assert ref_params is not None
    assert ref_params["intake_id"] == 42
    assert ref_params["media_type"] == "audio"
    assert ref_params["object_key"] == "intake/abc-123"
    assert ref_params["record_attempt"] == 1

    with pytest.raises(IntakeValidationError, match="requires text content"):
        await facade.submit_intake(patient_id=7, mode="text", language="en")


@pytest.mark.asyncio
async def test_submit_intake_voice_mode_demands_media_ref_rejects_text() -> None:
    facade = _facade(_connection([]))

    with pytest.raises(
        IntakeValidationError,
        match="voice mode intake must not include text content",
    ):
        await facade.submit_intake(
            patient_id=7,
            mode="voice",
            language="en",
            text="pehle record karo",
        )

    with pytest.raises(IntakeValidationError, match="requires a media reference"):
        await facade.submit_intake(patient_id=7, mode="voice", language="en")


@pytest.mark.asyncio
async def test_submit_intake_voice_duration_below_floor_is_rejected() -> None:
    """A clip under the 3s floor is unusable and must not waste AI budget."""
    facade = _facade(_connection([]))

    with pytest.raises(
        IntakeValidationError,
        match="audio duration 2999ms is below minimum 3000ms",
    ):
        await facade.submit_intake(
            patient_id=7,
            mode="voice",
            language="en",
            media_ref=_media_ref(duration_ms=2999),
        )


@pytest.mark.asyncio
async def test_submit_intake_voice_duration_at_floor_is_accepted() -> None:
    """The floor is inclusive: exactly 3s (3000ms) is a valid submission."""
    connection = _connection(
        [
            _intake_id_result(intake_id=8),
            _FakeResult(scalar=None),
            _outbox_result(),
            _outbox_result(),
        ]
    )
    facade = _facade(connection)

    result = await facade.submit_intake(
        patient_id=7,
        mode="voice",
        language="en",
        media_ref=_media_ref(duration_ms=3000),
    )

    assert result.intake_id == 8


@pytest.mark.asyncio
async def test_submit_intake_voice_duration_at_ceiling_is_accepted() -> None:
    """The ceiling is inclusive: exactly 180s (180000ms) is a valid submission."""
    connection = _connection(
        [
            _intake_id_result(intake_id=8),
            _FakeResult(scalar=None),
            _outbox_result(),
            _outbox_result(),
        ]
    )
    facade = _facade(connection)

    result = await facade.submit_intake(
        patient_id=7,
        mode="voice",
        language="en",
        media_ref=_media_ref(duration_ms=180_000),
    )

    assert result.intake_id == 8


@pytest.mark.asyncio
async def test_submit_intake_voice_duration_above_ceiling_is_rejected() -> None:
    """A clip over the 180s ceiling exceeds the AI pipeline context window."""
    facade = _facade(_connection([]))

    with pytest.raises(
        IntakeValidationError,
        match="audio duration 180001ms exceeds maximum 180000ms",
    ):
        await facade.submit_intake(
            patient_id=7,
            mode="voice",
            language="en",
            media_ref=_media_ref(duration_ms=180_001),
        )


@pytest.mark.asyncio
async def test_submit_intake_text_exceeding_2000_chars_is_rejected() -> None:
    """The text cap is enforced server-side with a typed error (criterion 2)."""
    facade = _facade(_connection([]))

    with pytest.raises(IntakeValidationError, match="exceeds 2000 character cap"):
        await facade.submit_intake(
            patient_id=7,
            mode="text",
            language="en",
            text="a" * 2001,
        )


@pytest.mark.asyncio
async def test_submit_intake_text_of_exactly_2000_chars_is_accepted() -> None:
    """The cap is inclusive: exactly 2000 chars is a valid submission."""
    connection = _connection([_intake_id_result(intake_id=8), _outbox_result(), _outbox_result()])
    facade = _facade(connection)

    result = await facade.submit_intake(
        patient_id=7,
        mode="text",
        language="en",
        text="b" * 2000,
    )

    assert result.intake_id == 8


@pytest.mark.asyncio
async def test_submit_intake_capture_commits_before_any_ai_runs() -> None:
    """A capture commits durably and never touches an AI seam (AC5, durable here).

    The ticket's durability half is structural: the intake row and its outbox
    events are the ONLY writes in the submit transaction - no AI gateway call
    is attempted on this facade at all. The AI pipeline runs asynchronously
    from the captured event; its failure handling (``ai_job.failed``,
    raw-review degrade) is tested at the worker/pipeline seam in the later
    pipeline tickets.
    """
    connection = _connection([_intake_id_result(intake_id=42), _outbox_result(), _outbox_result()])
    facade = _facade(connection)

    result = await facade.submit_intake(
        patient_id=7,
        mode="text",
        language="en",
        text="draft durable now",
    )

    assert result.status == "captured"
    # Exactly three inserts (row + the started/captured outbox events) and
    # nothing else touched the connection - no AI gateway seam exists here.
    inserts = _inserts(connection)
    assert [s.table.name for s in inserts] == [
        "intake_intakes",
        "intake_outbox",
        "intake_outbox",
    ]


@pytest.mark.asyncio
async def test_get_intake_returns_agreed_dto_with_status_and_media_refs() -> None:
    connection = _connection(
        [_FakeResult(row=_intake_row(intake_id=1, patient_id=7)), _FakeResult(rows=[_media_row()])]
    )
    facade = _facade(connection)

    view = await facade.get_intake(intake_id=1, patient_id=7)

    assert isinstance(view, IntakeDetailView)
    assert view.intake_id == 1
    assert view.patient_id == 7
    assert view.status == "captured"
    assert view.record_attempts == 1
    assert view.text == "headache for two days"
    assert len(view.media_refs) == 1
    assert view.media_refs[0].object_key == "intake/abc-123"


@pytest.mark.asyncio
async def test_get_intake_refuses_an_intake_the_patient_does_not_own() -> None:
    facade = _facade(_connection([_FakeResult(row=None)]))

    with pytest.raises(IntakeNotFoundError, match="not found for patient"):
        await facade.get_intake(intake_id=1, patient_id=99)


@pytest.mark.asyncio
async def test_get_pre_summary_returns_draft_confidence_honesty_and_edits() -> None:
    row = _pre_summary_row(pre_summary_id=5, intake_id=1)
    connection = _connection(
        [_FakeResult(row=_intake_row(intake_id=1, patient_id=7)), _FakeResult(row=row)]
    )
    facade = _facade(connection)

    view = await facade.get_pre_summary(intake_id=1, patient_id=7)

    assert isinstance(view, PreSummaryView)
    assert view.pre_summary_id == 5
    assert view.intake_id == 1
    assert view.structured_fields == StructuredFields(symptoms=["headache"], severity="mild")
    assert view.structuring_confidence == 0.82
    assert view.low_confidence is False
    assert view.review_state == "draft"
    assert view.patient_edits is None
    assert view.review_attribution is None


@pytest.mark.asyncio
async def test_get_pre_summary_honesty_flag_true_on_low_confidence() -> None:
    row = _pre_summary_row(pre_summary_id=6, intake_id=2)
    row.low_confidence = True
    row.structuring_confidence = 0.55
    connection = _connection(
        [_FakeResult(row=_intake_row(intake_id=2, patient_id=7)), _FakeResult(row=row)]
    )
    facade = _facade(connection)

    view = await facade.get_pre_summary(intake_id=2, patient_id=7)

    assert view.low_confidence is True
    assert view.structuring_confidence == 0.55
    assert view.review_state == "draft"


@pytest.mark.asyncio
async def test_get_pre_summary_refuses_an_intake_the_patient_does_not_own() -> None:
    facade = _facade(_connection([_FakeResult(row=None)]))

    with pytest.raises(IntakeNotFoundError, match="not found for patient"):
        await facade.get_pre_summary(intake_id=1, patient_id=99)


@pytest.mark.asyncio
async def test_get_pre_summary_none_when_no_pre_summary_refs_exist() -> None:
    connection = _connection(
        [_FakeResult(row=_intake_row(intake_id=1, patient_id=7)), _FakeResult(row=None)]
    )
    facade = _facade(connection)

    with pytest.raises(IntakeNotFoundError, match="pre-summary not found"):
        await facade.get_pre_summary(intake_id=1, patient_id=7)


@pytest.mark.asyncio
async def test_request_rx_draft_delegates_to_ai_gateway() -> None:
    connection = _DraftMeteringConnection()
    gateway = MockAiProvider(confidence_level="clean")
    facade = IntakeFacade(engine=_engine(connection), ai_gateway=gateway)

    result = await facade.request_rx_draft(
        doctor_input_ref=101,
        pre_summary_ref=5,
        history_summary="case notes for context",
    )

    assert result.doctor_input_ref == 101
    assert result.pre_summary_ref == 5
    assert result.rx_items == [
        RxDraftItem(
            name="mock medication",
            dose="1 tablet",
            duration="5 days",
            frequency="once daily",
        )
    ]
    assert result.confidence >= 0.0
    assert len(gateway.calls) == 1
    request = gateway.calls[0]
    assert isinstance(request, DraftRxRequest)
    assert request.doctor_input_ref == "101"
    assert request.pre_summary_ref == "5"
    assert request.patient_history_summary == "case notes for context"
    assert request.context.language == "en"


@pytest.mark.asyncio
async def test_request_rx_draft_raises_when_pre_summary_missing() -> None:
    connection = _connection([_FakeResult(row=None)])
    facade = _facade(connection)

    with pytest.raises(IntakeNotFoundError, match="pre-summary 5 not found"):
        await facade.request_rx_draft(doctor_input_ref=101, pre_summary_ref=5)


@pytest.mark.asyncio
async def test_request_rx_draft_raises_when_its_intake_is_missing() -> None:
    """A draft needs its intake for the metered job row, so it fails closed.

    The ``intake_ai_jobs`` FK points at the intake, so a pre-summary whose intake
    cannot be read is a dead reference: drafting against it would consume provider
    tokens with no row to record them on (PS-03, #722). The seam refuses instead.
    """
    connection = _connection(
        [_FakeResult(row=_pre_summary_row(pre_summary_id=5, intake_id=1)), _FakeResult(row=None)]
    )
    gateway = MockAiProvider(confidence_level="clean")
    facade = IntakeFacade(engine=_engine(connection), ai_gateway=gateway)

    with pytest.raises(IntakeNotFoundError, match="intake 1 not found"):
        await facade.request_rx_draft(doctor_input_ref=101, pre_summary_ref=5)

    assert gateway.calls == []


@pytest.mark.asyncio
async def test_request_rx_draft_writes_a_metered_draft_job_and_publishes_completed() -> None:
    """A draft is a metered egress like any other leg (PS-03, B4 #722).

    The seam books a ``draft`` ``ai_jobs`` row before the provider call, then
    finalizes it with the effective serving provider/model, the provider's
    reported tokens priced into ``cost_paise``, the call duration and the
    confidence - and publishes ``ai_job.completed`` on the same connection, in the
    same transaction, so MOD-013 accumulates the drafting leg's spend like the
    transcription and structuring legs.
    """
    connection = _DraftMeteringConnection()
    gateway = MockAiProvider(confidence_level="clean")
    facade = IntakeFacade(engine=_engine(connection), ai_gateway=gateway)

    await facade.request_rx_draft(
        doctor_input_ref=101,
        pre_summary_ref=5,
        history_summary="case notes for context",
    )

    booking = connection.ai_job_booking()
    assert booking["intake_id"] == 1
    assert booking["task_type"] == "draft"
    assert booking["status"] == "running"

    completion = connection.ai_job_update()
    assert completion["status"] == "completed"
    assert completion["provider"] == "mock"
    assert completion["model"] == "mock-model"
    # The mock provider reports no usage (the real-usage price assertion lives in
    # ``test_request_rx_draft_prices_the_completed_job_from_reported_tokens``).
    assert completion["input_tokens"] == 0
    assert completion["output_tokens"] == 0
    assert completion["cost_paise"] == 0
    assert completion["duration_ms"] >= 0

    event = connection.outbox_payload(EVENT_AI_JOB_COMPLETED)
    assert event["task_type"] == "draft"
    assert event["ai_job_id"] == 42
    assert event["intake_id"] == 1
    assert event["patient_id"] == 7
    # No doctor is resolved on this leg: the drafting doctor lives in the care
    # schema, and per-actor attribution rides the ``intake.doctor_assigned``
    # edge (#720) rather than a cross-schema read (ADR-0003).
    assert event["doctor_id"] is None
    # The booking announced the enqueue before the completion closed it (#729), so
    # the leg's queue row has both ends.
    assert connection.outbox_types() == [EVENT_AI_JOB_QUEUED, EVENT_AI_JOB_COMPLETED]
    queued = connection.outbox_payload(EVENT_AI_JOB_QUEUED)
    assert queued["ai_job_id"] == 42
    assert queued["intake_id"] == 1
    assert queued["task_type"] == "draft"
    assert queued["patient_id"] == 7


@pytest.mark.asyncio
async def test_request_rx_draft_prices_the_completed_job_from_reported_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cost is the provider's reported usage priced per model, never a constant.

    The mock provider reports nothing, so this drives a gateway that reports real
    usage against a deployment-priced model and asserts the paise figure comes out
    of the pricing helper.
    """
    monkeypatch.setenv("AI_PRICING_TABLE", "mock-model:0.02:0.06")
    connection = _DraftMeteringConnection()
    gateway = _UsageReportingGateway(input_tokens=800, output_tokens=200)
    facade = IntakeFacade(engine=_engine(connection), ai_gateway=gateway)

    await facade.request_rx_draft(doctor_input_ref=101, pre_summary_ref=5)

    completion = connection.ai_job_update()
    assert completion["input_tokens"] == 800
    assert completion["output_tokens"] == 200
    assert completion["cost_paise"] == 28
    assert completion["cost_paise"] == compute_cost_paise(
        "mock-model",
        input_tokens=800,
        output_tokens=200,
        table=resolve_pricing_table(),
    )
    event = connection.outbox_payload(EVENT_AI_JOB_COMPLETED)
    assert event["input_tokens"] == 800
    assert event["output_tokens"] == 200
    assert event["cost_paise"] == completion["cost_paise"]


@pytest.mark.asyncio
async def test_request_rx_draft_failure_records_the_job_failed_and_still_raises() -> None:
    """A failed draft is metered as failed, then the caller still sees the error.

    The booking is finalized ``failed`` and ``ai_job.failed`` is published, so the
    aggregate counts the attempt; the transaction COMMITS before the provider error
    escapes, so the failure is durably recorded rather than rolled back with it.
    No token count is invented: the gateway's failure carries no usage, so none is
    written.
    """
    connection = _DraftMeteringConnection()
    gateway = _UsageReportingGateway(
        input_tokens=0,
        output_tokens=0,
        error=Ext002CallError("provider timed out after 3 attempts", retries_exhausted=True),
    )
    facade = IntakeFacade(engine=_commit_probing_engine(connection), ai_gateway=gateway)

    with pytest.raises(Ext002CallError, match="provider timed out"):
        await facade.request_rx_draft(doctor_input_ref=101, pre_summary_ref=5)

    failure = connection.ai_job_update()
    assert failure["status"] == "failed"
    assert failure["error_message"] == "Ext002CallError"
    assert "input_tokens" not in failure
    assert "cost_paise" not in failure

    event = connection.outbox_payload(EVENT_AI_JOB_FAILED)
    assert event["task_type"] == "draft"
    assert event["reason"] == "Ext002CallError"
    assert event["patient_id"] == 7
    assert event["doctor_id"] is None
    # The enqueue came FIRST (#729): queue depth is ``enqueued - completed -
    # failed``, so a job that only published its failure would never have been
    # counted as queued and the depth arithmetic would have no enqueue term.
    assert connection.outbox_types() == [EVENT_AI_JOB_QUEUED, EVENT_AI_JOB_FAILED]
    queued = connection.outbox_payload(EVENT_AI_JOB_QUEUED)
    # The enqueue names the SAME job the close names - that identity is what makes
    # the pair a queue in and a queue out rather than two unrelated events.
    assert queued["ai_job_id"] == event["ai_job_id"]
    assert queued["task_type"] == "draft"
    assert queued["patient_id"] == 7
    # NO doctor reference on the enqueue: at enqueue time the drafting doctor lives
    # in the care schema (ADR-0003), so carrying one would be a null nobody reads.
    assert "doctor_id" not in queued
    # The transaction committed on the way out of the facade, so the recorded
    # failure is not rolled back with the exception.
    assert connection.rolled_back is False


@pytest.mark.asyncio
async def test_request_rx_draft_books_exactly_one_job_per_call() -> None:
    """One draft is one metered row - booked before the call, never twice.

    The insert lands first so the attempt has a row to be finalized onto, and a
    second booking would double-count the call in the aggregate. Note what this
    does NOT claim: the booking shares the call's transaction (the same shape the
    transcribe and structure legs use), so what durability it buys is the
    ``ai_job.failed`` record committing with the escaping error, which the test
    above pins.
    """
    connection = _DraftMeteringConnection()
    gateway = _UsageReportingGateway(
        input_tokens=0,
        output_tokens=0,
        error=Ext002CallError("provider rejected the request", retries_exhausted=False),
    )
    facade = IntakeFacade(engine=_engine(connection), ai_gateway=gateway)

    with pytest.raises(Ext002CallError):
        await facade.request_rx_draft(doctor_input_ref=101, pre_summary_ref=5)

    kinds = [r.kind for r in connection.executed]
    assert kinds.count("insert_ai_job") == 1
    assert kinds.index("insert_ai_job") < kinds.index("update_ai_job")
