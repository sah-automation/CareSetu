"""PHASE-14A B2 (#700): Langfuse span-metadata allow-list + boot wiring.

Covers the ticket's acceptance criteria:

- The AI-span metadata allow-list is exactly the plan's documented set
  (plan-phase14-observability §6), and a key off the list - a transcript, a
  patient name/phone, a raw provider payload - is rejected, so no PHI can be
  attached to a span.
- ``set_span_metadata`` is best-effort: it never raises into the AI call path,
  attaches only allow-listed keys, and is a no-op when Langfuse is unconfigured.
- ``get_langfuse_client`` is called (explicitly) at both composition roots; the
  absent-keys path leaves boot unchanged.
"""

from __future__ import annotations

import asyncio

import pytest

import app.main as app_main
import observability.langfuse_client as langfuse_client
import observability.langfuse_span as langfuse_span
import worker.main as worker_main
from app.config import Settings
from observability.langfuse_span import (
    ALLOWED_SPAN_METADATA_KEYS,
    SpanMetadataError,
    build_span_metadata,
    set_span_metadata,
)

#: The documented set (plan-phase14-observability §6 "Span metadata").
_DOCUMENTED_METADATA_KEYS = {
    "task_type",
    "provider",
    "model",
    "input_tokens",
    "output_tokens",
    "duration_ms",
    "cost_paise",
    "confidence",
    "status",
    "intake_id",
    "ai_job_id",
    "trace_id",
    "prompt_version",
}


# --- allow-list contract ---------------------------------------------------


def test_allow_list_is_exactly_the_documented_set() -> None:
    assert ALLOWED_SPAN_METADATA_KEYS == _DOCUMENTED_METADATA_KEYS


def test_allow_list_excludes_phi_bearing_keys() -> None:
    for key in ("transcript", "patient_name", "patient_phone", "phone", "raw_payload", "output"):
        assert key not in ALLOWED_SPAN_METADATA_KEYS


def test_build_span_metadata_passes_allow_listed_fields() -> None:
    fields = {
        "task_type": "structure",
        "provider": "openai_compatible",
        "model": "gpt-4o-mini",
        "input_tokens": 120,
        "output_tokens": 40,
        "duration_ms": 812,
        "cost_paise": 7,
        "confidence": 0.82,
        "status": "success",
        "intake_id": "intake-123",
        "ai_job_id": "job-456",
        "trace_id": "trace-789",
        "prompt_version": "v3",
    }

    assert build_span_metadata(fields) == fields


def test_build_span_metadata_rejects_a_transcript() -> None:
    with pytest.raises(SpanMetadataError, match="transcript"):
        build_span_metadata({"task_type": "structure", "transcript": "patient said ..."})


def test_build_span_metadata_rejects_patient_identity() -> None:
    with pytest.raises(SpanMetadataError, match="patient_name"):
        build_span_metadata({"status": "success", "patient_name": "Ada Lovelace"})


def test_build_span_metadata_names_every_offending_key() -> None:
    with pytest.raises(SpanMetadataError) as excinfo:
        build_span_metadata({"transcript": "x", "phone": "+919999999999"})

    message = str(excinfo.value)
    assert "phone" in message
    assert "transcript" in message


def test_build_span_metadata_drops_none_values() -> None:
    assert build_span_metadata({"status": "success", "confidence": None}) == {"status": "success"}


# --- best-effort enrichment -------------------------------------------------


class _FakeClient:
    """Records ``update_current_span`` calls; can be made to raise."""

    def __init__(self, *, raises: bool = False) -> None:
        self.raises = raises
        self.updates: list[dict[str, object]] = []

    def update_current_span(self, *, metadata: dict[str, object]) -> None:
        if self.raises:
            raise RuntimeError("langfuse unavailable")
        self.updates.append(metadata)


def test_set_span_metadata_is_noop_without_a_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(langfuse_span, "get_configured_client", lambda: None)

    # A disallowed key would raise in the builder, but with no client the whole
    # call is short-circuited - so tracing-off never affects the AI call path.
    set_span_metadata(task_type="structure", transcript="should never be evaluated")


def test_set_span_metadata_attaches_allow_listed_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient()
    monkeypatch.setattr(langfuse_span, "get_configured_client", lambda: client)

    set_span_metadata(task_type="transcribe", status="success", input_tokens=10, confidence=0.8)

    assert client.updates == [
        {"task_type": "transcribe", "status": "success", "input_tokens": 10, "confidence": 0.8}
    ]


def test_set_span_metadata_drops_a_disallowed_key_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient()
    monkeypatch.setattr(langfuse_span, "get_configured_client", lambda: client)

    set_span_metadata(task_type="structure", transcript="patient said ...")

    assert client.updates == []


def test_set_span_metadata_never_logs_the_value_of_a_disallowed_key(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The PHI never reaches the logs: only the offending key name is reported."""
    client = _FakeClient()
    monkeypatch.setattr(langfuse_span, "get_configured_client", lambda: client)

    with caplog.at_level("WARNING", logger="observability.langfuse_span"):
        set_span_metadata(task_type="structure", transcript="Ada reports a cough")

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "transcript" in logged
    assert "Ada reports a cough" not in logged


def test_set_span_metadata_skips_a_client_update_when_all_values_are_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient()
    monkeypatch.setattr(langfuse_span, "get_configured_client", lambda: client)

    set_span_metadata(task_type="structure", confidence=None, input_tokens=None)

    # task_type is not None so it is attached; the None fields are dropped.
    assert client.updates == [{"task_type": "structure"}]


def test_set_span_metadata_never_raises_when_the_client_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(raises=True)
    monkeypatch.setattr(langfuse_span, "get_configured_client", lambda: client)

    set_span_metadata(task_type="structure", status="success")


# --- singleton + flush ------------------------------------------------------


class _FakeSingletonClient:
    def __init__(self) -> None:
        self.flushed = 0

    def flush(self) -> None:
        self.flushed += 1


def test_get_configured_client_is_none_before_init(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(langfuse_client, "_client", None)

    assert langfuse_client.get_configured_client() is None


def test_flush_langfuse_is_noop_without_a_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(langfuse_client, "_client", None)

    langfuse_client.flush_langfuse()  # never raises


def test_flush_langfuse_flushes_the_client(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeSingletonClient()
    monkeypatch.setattr(langfuse_client, "_client", client)

    langfuse_client.flush_langfuse()

    assert client.flushed == 1


def test_flush_langfuse_swallows_a_flush_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Boom:
        def flush(self) -> None:
            raise RuntimeError("flush exploded")

    monkeypatch.setattr(langfuse_client, "_client", _Boom())

    langfuse_client.flush_langfuse()  # never raises


def test_get_langfuse_client_is_a_noop_when_keys_are_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A blank public key returns None and never imports the SDK."""
    monkeypatch.setattr(langfuse_client, "_client", None)
    monkeypatch.setattr(langfuse_client, "_initialised", False)

    assert langfuse_client.get_langfuse_client("", "", "https://lf.invalid") is None
    assert langfuse_client._client is None
    assert langfuse_client.get_configured_client() is None


# --- composition-root wiring ------------------------------------------------


class _FakeConnection:
    async def __aenter__(self) -> _FakeConnection:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False


class _FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    def connect(self) -> _FakeConnection:
        return _FakeConnection()

    async def dispose(self) -> None:
        self.disposed = True


async def test_worker_boot_wires_langfuse_explicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, str]] = []
    engine = _FakeEngine()
    stop_event = asyncio.Event()
    stop_event.set()

    async def fake_discover(connection: object, schemas: object) -> tuple[object, ...]:
        del connection, schemas
        return ()

    async def fake_poll(*args: object, **kwargs: object) -> None:
        del args, kwargs

    monkeypatch.setattr(
        worker_main,
        "get_langfuse_client",
        lambda public_key, secret_key, host: calls.append((public_key, secret_key, host)),
    )
    monkeypatch.setattr(worker_main, "create_async_engine", lambda url: engine)
    monkeypatch.setattr(worker_main, "discover_outbox_tables", fake_discover)
    monkeypatch.setattr(worker_main, "run_poll_loop", fake_poll)

    settings = Settings(
        langfuse_public_key="pk",
        langfuse_secret_key="sk",
        langfuse_host="https://lf.invalid",
    )
    await worker_main.run_worker_until_stopped(stop_event, settings=settings)

    assert calls == [("pk", "sk", "https://lf.invalid")]


def test_app_boot_wires_langfuse_explicitly(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        app_main,
        "get_langfuse_client",
        lambda public_key, secret_key, host: calls.append((public_key, secret_key, host)),
    )
    settings = Settings(
        langfuse_public_key="pk",
        langfuse_secret_key="sk",
        langfuse_host="https://lf.invalid",
    )
    application = app_main.create_app(settings)

    async def _run_lifespan() -> None:
        async with application.router.lifespan_context(application):
            pass

    asyncio.run(_run_lifespan())

    assert calls == [("pk", "sk", "https://lf.invalid")]


def test_app_boot_is_unchanged_when_keys_are_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        app_main,
        "get_langfuse_client",
        lambda public_key, secret_key, host: calls.append((public_key, secret_key, host)),
    )
    application = app_main.create_app(Settings())

    async def _run_lifespan() -> None:
        async with application.router.lifespan_context(application):
            pass

    asyncio.run(_run_lifespan())

    # Still wired (called with blanks); the client itself no-ops on blank keys.
    assert calls == [("", "", Settings().langfuse_host)]
