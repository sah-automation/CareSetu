"""PHASE-7 T08: intake media upload + re-record facade (ticket #352, spec #344).

Drives ``upload_intake_media`` and ``re_record_intake`` at the facade-with-fakes
seam - the real IntakeFacade with a fake engine, a fake media store, and an
injected fake backoff sleep. Pins the durable, self-correcting capture contract:

- ``upload_intake_media`` retries the object-store transfer up to 3 times with
  backoff on failure, then raises the typed :class:`MediaTransferError` - a
  partial capture is never lost silently; on success it returns a
  ``MediaUploadRef`` recording duration/size/attempt under the ``intake/``
  object prefix.
- ``re_record_intake`` attaches a fresh recording attempt, increments the
  server-side attempt count and hard-stops at 3 (never trusting the client),
  emits ``intake.retry_requested`` between attempts, and routes to forced text
  when attempts are exhausted so the patient is never stuck.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.sql.dml import Insert

from modules.intake.domain.events import (
    EVENT_INTAKE_RETRY_REQUESTED,
    IntakeRetryRequestedPayload,
)
from modules.intake.domain.exceptions import (
    IntakeNotFoundError,
    IntakeValidationError,
    MediaTransferError,
)
from modules.intake.facade import MAX_UPLOAD_ATTEMPTS, IntakeFacade
from modules.intake.intake_models import MediaFile, MediaUploadRef
from modules.intake.schema.models import intake_media_refs

NOW = datetime.now(UTC)


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

    def first(self) -> object:
        return self._row

    def all(self) -> list:
        return self._rows


class _FakeMediaStore:
    """A controllable media store: fails the first ``n_failures`` writes, then succeeds."""

    def __init__(self, *, n_failures: int = 0) -> None:
        self.n_failures = n_failures
        self.save_calls: int = 0
        self.captured_patient_ids: list[int] = []
        self.captured_data: list[bytes] = []

    def save(self, *, data: bytes, patient_id: int) -> str:
        self.save_calls += 1
        self.captured_patient_ids.append(patient_id)
        self.captured_data.append(data)
        if self.save_calls <= self.n_failures:
            raise OSError("disk full")
        return f"intake/{patient_id}/clip-{self.save_calls}.enc"


class _FakeSleep:
    """Records backoff waits instead of actually sleeping."""

    def __init__(self) -> None:
        self.waits: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


def _connection(execute_results: list[object]) -> AsyncMock:
    connection = AsyncMock()
    connection.execute = AsyncMock(side_effect=execute_results)
    return connection


def _engine(connection: AsyncMock) -> AsyncMock:
    engine = AsyncMock(spec=AsyncEngine)
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=connection)
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    return engine


def _facade(
    connection: AsyncMock,
    *,
    store: object | None = None,
    sleep: _FakeSleep | None = None,
) -> IntakeFacade:
    return IntakeFacade(
        engine=_engine(connection),
        media_store=store,
        sleep=sleep or _FakeSleep(),
    )


def _file(
    *,
    duration_ms: int = 90_000,
    size: int = 1_024_000,
    record_attempt: int = 1,
) -> MediaFile:
    return MediaFile(
        data=b"\x00" * 512,
        filename="recording.webm",
        media_type="audio",
        audio_duration_ms=duration_ms,
        file_size_bytes=size,
        record_attempt=record_attempt,
    )


def _media_ref(*, object_key: str = "intake/7/clip-1.enc") -> MediaUploadRef:
    return MediaUploadRef(
        object_key=object_key,
        media_type="audio",
        audio_duration_ms=90_000,
        file_size_bytes=1_024_000,
        record_attempt=1,
    )


def _intake_row(
    *,
    intake_id: int = 1,
    patient_id: int = 7,
    status: str = "re_record",
    record_attempts: int = 1,
    forced_text: bool = False,
) -> object:
    return SimpleNamespace(
        id=intake_id,
        patient_id=patient_id,
        mode="voice",
        language="en",
        status=status,
        record_attempts=record_attempts,
        text=None,
        transcript=None,
        transcript_usability=None,
        forced_text=forced_text,
        created_at=NOW,
        updated_at=NOW,
    )


def _inserts(connection: AsyncMock) -> list[Insert]:
    return [
        call.args[0]
        for call in connection.execute.await_args_list
        if isinstance(call.args[0], Insert)
    ]


def _insert_by_table(connection: AsyncMock, table_name: str) -> Insert:
    return next(s for s in _inserts(connection) if s.table.name == table_name)


# ---------------------------------------------------------------------------
# upload_intake_media
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_retries_the_transfer_up_to_three_times_then_raises_typed_error() -> None:
    """A persistently failing transfer is retried 3x with backoff, never lost silently."""
    store = _FakeMediaStore(n_failures=999)
    sleep = _FakeSleep()
    facade = _facade(_connection([]), store=store, sleep=sleep)

    with pytest.raises(MediaTransferError, match="failed after 3 attempts"):
        await facade.upload_intake_media(patient_id=7, file=_file())

    assert store.save_calls == 3
    assert len(sleep.waits) == 2  # two backoff sleeps between the three attempts
    assert sleep.waits == [0.5, 1.0]  # exponential backoff


@pytest.mark.asyncio
async def test_upload_retries_and_succeeds_on_a_later_attempt() -> None:
    """A flaky transfer that heals within the ladder is captured, not dropped."""
    store = _FakeMediaStore(n_failures=1)
    sleep = _FakeSleep()
    facade = _facade(_connection([]), store=store, sleep=sleep)

    ref = await facade.upload_intake_media(patient_id=7, file=_file())

    assert store.save_calls == 2
    assert len(sleep.waits) == 1
    assert ref.object_key == "intake/7/clip-2.enc"


@pytest.mark.asyncio
async def test_upload_returns_a_media_ref_recording_metadata_under_intake_prefix() -> None:
    """The returned reference records type/duration/size/attempt under intake/."""
    store = _FakeMediaStore()
    facade = _facade(_connection([]), store=store)

    ref = await facade.upload_intake_media(
        patient_id=7,
        file=_file(duration_ms=90_000, size=1_024_000),
    )

    assert isinstance(ref, MediaUploadRef)
    assert ref.object_key.startswith("intake/7/")
    assert ref.media_type == "audio"
    assert ref.audio_duration_ms == 90_000
    assert ref.file_size_bytes == 1_024_000
    assert ref.record_attempt == 1
    assert store.captured_patient_ids == [7]
    assert store.captured_data == [b"\x00" * 512]


@pytest.mark.asyncio
async def test_upload_echoes_the_clip_record_attempt_truthfully() -> None:
    """A later-take clip carries its true B3 attempt, not a hardcoded 1."""
    store = _FakeMediaStore()
    facade = _facade(_connection([]), store=store)

    ref = await facade.upload_intake_media(
        patient_id=7,
        file=_file(record_attempt=3),
    )

    assert ref.record_attempt == 3


@pytest.mark.asyncio
async def test_upload_requires_a_configured_media_store() -> None:
    facade = _facade(_connection([]))

    with pytest.raises(IntakeValidationError, match="media store is not configured"):
        await facade.upload_intake_media(patient_id=7, file=_file())


# ---------------------------------------------------------------------------
# re_record_intake - accepting a fresh attempt
# ---------------------------------------------------------------------------


def _accepting_results(media_ref_id: int = 55) -> list[object]:
    # select(intake) -> media-ref insert -> intake update -> outbox insert
    return [
        _FakeResult(row=_intake_row(status="re_record", record_attempts=1)),
        _FakeResult(scalar=media_ref_id),
        _FakeResult(scalar=None),
        _FakeResult(scalar=None),
    ]


@pytest.mark.asyncio
async def test_re_record_increments_attempt_and_emits_retry_requested() -> None:
    """A fresh recording accepted from re_record -> structuring, attempt +1, event emitted."""
    connection = _connection(_accepting_results())
    facade = _facade(connection, store=_FakeMediaStore())

    result = await facade.re_record_intake(
        intake_id=1,
        patient_id=7,
        media_ref=_media_ref(),
    )

    assert result.accepted is True
    assert result.status == "structuring"
    assert result.record_attempts == 2
    assert result.forced_text is False
    assert result.media_ref_id == 55

    # A real intake.retry_requested envelope was written to the outbox.
    outbox_write = _insert_by_table(connection, "intake_outbox")
    values = outbox_write.compile().params
    assert values["event_type"] == EVENT_INTAKE_RETRY_REQUESTED
    payload = IntakeRetryRequestedPayload.model_validate(values["payload"])
    assert payload.intake_id == 1
    assert payload.record_attempt == 2


@pytest.mark.asyncio
async def test_re_record_attaches_the_new_media_with_the_next_attempt_number() -> None:
    connection = _connection(_accepting_results())
    facade = _facade(connection)

    await facade.re_record_intake(intake_id=1, patient_id=7, media_ref=_media_ref())

    media_insert = _insert_by_table(connection, intake_media_refs.name)
    params = dict(media_insert.compile().params)
    assert params["intake_id"] == 1
    assert params["object_key"] == "intake/7/clip-1.enc"
    assert params["record_attempt"] == 2


@pytest.mark.asyncio
async def test_re_record_increments_attempt_a_second_time_towards_the_cap() -> None:
    """Accepting an attempt 2 -> attempt 3: still increments and emits the event."""
    connection = _connection(
        [
            _FakeResult(row=_intake_row(status="re_record", record_attempts=2)),
            _FakeResult(scalar=56),
            _FakeResult(scalar=None),
            _FakeResult(scalar=None),
        ]
    )
    facade = _facade(connection)

    result = await facade.re_record_intake(
        intake_id=1,
        patient_id=7,
        media_ref=_media_ref(),
    )

    assert result.accepted is True
    assert result.record_attempts == 3

    outbox_write = _insert_by_table(connection, "intake_outbox")
    payload = IntakeRetryRequestedPayload.model_validate(outbox_write.compile().params["payload"])
    assert payload.record_attempt == 3


# ---------------------------------------------------------------------------
# re_record_intake - hard stop at 3 (server-side) -> forced text
# ---------------------------------------------------------------------------


def _at_cap_results() -> list[object]:
    # select(intake) -> intake update (forced text)
    return [
        _FakeResult(row=_intake_row(status="re_record", record_attempts=3)),
        _FakeResult(scalar=None),
    ]


@pytest.mark.asyncio
async def test_re_record_hard_stops_at_three_and_routes_to_forced_text() -> None:
    """At the server-side cap (3), a further re-record request is refused -> forced text."""
    connection = _connection(_at_cap_results())
    facade = _facade(connection)

    result = await facade.re_record_intake(
        intake_id=1,
        patient_id=7,
        media_ref=_media_ref(),
    )

    assert result.accepted is False
    assert result.status == "ready_for_review"
    assert result.forced_text is True
    assert result.record_attempts == 3
    assert result.media_ref_id is None

    # No new media attached and no retry event emitted on the hard stop.
    assert _inserts(connection) == []


@pytest.mark.asyncio
async def test_re_record_hard_stop_never_trusts_a_client_claiming_more_attempts() -> None:
    """Even when the client claims otherwise, the server's own count is authoritative.

    The intake is at 3 according to the server; the client passes a media ref as
    if it were a valid 4th attempt, but the server refuses and forces text.
    """
    connection = _connection(_at_cap_results())
    facade = _facade(connection)

    result = await facade.re_record_intake(
        intake_id=1,
        patient_id=7,
        media_ref=_media_ref(object_key="intake/7/client-4th.enc"),
    )

    assert result.accepted is False
    assert result.forced_text is True
    media_inserts = [s for s in _inserts(connection) if s.table.name == intake_media_refs.name]
    assert media_inserts == []


# ---------------------------------------------------------------------------
# re_record_intake - patient scoping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_re_record_refuses_an_intake_the_patient_does_not_own() -> None:
    facade = _facade(_connection([_FakeResult(row=None)]))

    with pytest.raises(IntakeNotFoundError, match="not found for patient"):
        await facade.re_record_intake(intake_id=1, patient_id=99, media_ref=_media_ref())


@pytest.mark.asyncio
async def test_upload_attempt_constant_matches_spec() -> None:
    assert MAX_UPLOAD_ATTEMPTS == 3
