"""T03 (#380): FallbackAiGateway composing primary + secondary providers.

Acceptance contract from the ticket: the fallback gateway tries primary first,
falls back to secondary on genuine outage (retries_exhausted=True) or open
breaker; contract rejection propagates immediately; low confidence never triggers
fallback; effective provider+model exposed after success; both-outaged raises
the outage error with no fabricated result. All tests drive the real adapters
through ``httpx.MockTransport`` with an injectable no-op sleep.
"""

from __future__ import annotations

import json
import logging

import httpx
import pytest

from app.config import DEFAULT_AI_MAX_RETRIES
from modules.intake.adapters.ai_gateway import (
    AiEgressContext,
    AiGateway,
    DraftRxRequest,
    StructureRequest,
    TranscribeRequest,
)
from modules.intake.adapters.ai_provider_ext import (
    CircuitBreakerAiGateway,
    Ext002AiProvider,
    Ext002CallError,
)
from modules.intake.adapters.ai_provider_fallback import (
    AiGatewayMeta,
    FallbackAiGateway,
)
from modules.intake.adapters.ai_provider_openai_compatible import (
    build_openai_compatible_gateway,
)

# A breaker refuses a call by raising before awaiting the adapter coroutine that
# was already created - an inert, safe object that the interpreter warns about.
pytestmark = pytest.mark.filterwarnings("ignore:.*was never awaited.*")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_META_GROQ = AiGatewayMeta(provider="groq", model="llama-3.3-70b-versatile")
_META_GEMINI = AiGatewayMeta(provider="gemini", model="gemini-2.0-flash")

_COMMON_CONTEXT = AiEgressContext(language="hi", age_range="30-40", sex="male")

_TRANSCRIBE_BODY = {
    "transcript": "mujhe bukhar hai",
    "confidence": 0.85,
    "language": "hi",
}
_STRUCTURE_BODY = {
    "chief_complaints": ["fever"],
    "symptoms": ["chills"],
    "duration": "3 days",
    "confidence": 0.92,
}
_DRAFT_RX_BODY = {
    "rx_items": [{"name": "paracetamol", "dose": "500mg", "duration": "5 days"}],
    "confidence": 0.80,
}

_CHAT_SUCCESS_BODY = {
    "choices": [
        {
            "message": {
                "content": json.dumps(_STRUCTURE_BODY),
            }
        }
    ]
}

_STRUCTURE_REQUEST = StructureRequest(
    transcript="mujhe bukhar hai", source="voice", context=_COMMON_CONTEXT
)
_TRANSCRIBE_REQUEST = TranscribeRequest(audio_ref="media/1", mode="voice", context=_COMMON_CONTEXT)
_DRAFT_RX_REQUEST = DraftRxRequest(
    doctor_input_ref="voice_note/1",
    pre_summary_ref="pre_summary/2",
    patient_history_summary="history",
    context=_COMMON_CONTEXT,
)

_GROQ_URL = "https://groq.example"
_GEMINI_URL = "https://gemini.example"
_EXT_URL = "https://ext.example"


class _RecordingTransport:
    """MockTransport handler that records requests and replays canned responses.

    ``responses`` is one ``httpx.Response`` per request; the last entry repeats
    once the list is exhausted (the adapters retry on outage responses).
    """

    def __init__(
        self,
        *responses: httpx.Response,
    ) -> None:
        self._responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        index = min(len(self.requests) - 1, len(self._responses) - 1)
        response = self._responses[index]
        return httpx.Response(response.status_code, json=response.json())


class _SwitchingTransport:
    """MockTransport handler that returns outages until ``available`` is set."""

    def __init__(self) -> None:
        self.available = False
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.available:
            return httpx.Response(200, json=_CHAT_SUCCESS_BODY)
        return httpx.Response(503, json={"error": "provider unavailable"})


async def _noop_sleep(_: float) -> None:
    return None


def _outage_response() -> httpx.Response:
    return httpx.Response(503, json={"error": "provider unavailable"})


def _rejection_response() -> httpx.Response:
    return httpx.Response(400, json={"error": "invalid request"})


def _client(handler: object) -> httpx.AsyncClient:
    """Wrap a handler callable in a MockTransport-backed AsyncClient."""
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _openai_gateway(
    handler: object,
    *,
    base_url: str = _GROQ_URL,
    model: str = "llama-3.3-70b-versatile",
) -> AiGateway:
    return build_openai_compatible_gateway(
        api_key="test-key",
        base_url=base_url,
        model=model,
        client=_client(handler),
        sleep=_noop_sleep,
    )


def _ext_gateway(handler: object) -> AiGateway:
    return Ext002AiProvider(
        api_key="test-key",
        base_url=_EXT_URL,
        client=_client(handler),
        sleep=_noop_sleep,
    )


class _FailingStub:
    """An AiGateway that raises a distinctive error on every operation.

    Used where the chain's failure must be attributable to a specific leg (e.g.
    asserting which provider's error surfaces after a both-outage).
    """

    def __init__(self, error: Ext002CallError) -> None:
        self._error = error

    async def transcribe(self, request: TranscribeRequest) -> object:
        raise self._error

    async def structure(self, request: StructureRequest) -> object:
        raise self._error

    async def draft_rx(self, request: DraftRxRequest) -> object:
        raise self._error


def _breaker(
    adapter: AiGateway,
    *,
    threshold: int = 2,
    clock: object | None = None,
) -> CircuitBreakerAiGateway:
    return CircuitBreakerAiGateway(
        adapter,
        threshold=threshold,
        cooldown_seconds=30.0,
        clock=clock if clock is not None else lambda: 0.0,
    )


def _groq_ok() -> tuple[FallbackAiGateway, _RecordingTransport, _RecordingTransport]:
    primary_transport = _RecordingTransport(httpx.Response(200, json=_CHAT_SUCCESS_BODY))
    secondary_transport = _RecordingTransport(httpx.Response(200, json=_CHAT_SUCCESS_BODY))
    gateway = FallbackAiGateway(
        _openai_gateway(primary_transport),
        _META_GROQ,
        _openai_gateway(
            secondary_transport,
            base_url=_GEMINI_URL,
            model="gemini-2.0-flash",
        ),
        _META_GEMINI,
    )
    return gateway, primary_transport, secondary_transport


def _gemini_fallback() -> tuple[FallbackAiGateway, _RecordingTransport]:
    secondary_transport = _RecordingTransport(httpx.Response(200, json=_CHAT_SUCCESS_BODY))
    gateway = FallbackAiGateway(
        _openai_gateway(_RecordingTransport(_outage_response())),
        _META_GROQ,
        _openai_gateway(
            secondary_transport,
            base_url=_GEMINI_URL,
            model="gemini-2.0-flash",
        ),
        _META_GEMINI,
    )
    return gateway, secondary_transport


# ---------------------------------------------------------------------------
# Primary success (secondary untouched)
# ---------------------------------------------------------------------------


async def test_primary_success_returns_primary_and_never_calls_secondary() -> None:
    gateway, primary_transport, secondary_transport = _groq_ok()

    result = await gateway.structure(_STRUCTURE_REQUEST)

    assert result.model_dump() == _STRUCTURE_BODY
    assert len(primary_transport.requests) >= 1
    assert secondary_transport.requests == []


async def test_primary_success_records_effective_provider_and_model() -> None:
    gateway, _, _ = _groq_ok()

    await gateway.structure(_STRUCTURE_REQUEST)

    assert gateway.last_effective_provider == "groq"
    assert gateway.last_effective_model == "llama-3.3-70b-versatile"


# ---------------------------------------------------------------------------
# Primary outage -> secondary success, secondary effective, no fabrication
# ---------------------------------------------------------------------------


async def test_primary_outage_falls_back_to_secondary_success() -> None:
    primary_transport = _RecordingTransport(_outage_response())
    secondary_transport = _RecordingTransport(httpx.Response(200, json=_CHAT_SUCCESS_BODY))
    gateway = FallbackAiGateway(
        _openai_gateway(primary_transport),
        _META_GROQ,
        _openai_gateway(
            secondary_transport,
            base_url=_GEMINI_URL,
            model="gemini-2.0-flash",
        ),
        _META_GEMINI,
    )

    result = await gateway.structure(_STRUCTURE_REQUEST)

    assert result.model_dump() == _STRUCTURE_BODY
    # Primary exhausted its full retry budget (1 + max_retries HTTP attempts).
    assert len(primary_transport.requests) == DEFAULT_AI_MAX_RETRIES + 1
    assert len(secondary_transport.requests) >= 1


async def test_secondary_recorded_as_effective_after_fallback_success() -> None:
    gateway, _ = _gemini_fallback()

    await gateway.structure(_STRUCTURE_REQUEST)

    assert gateway.last_effective_provider == "gemini"
    assert gateway.last_effective_model == "gemini-2.0-flash"


async def test_fallback_result_is_the_real_secondary_response_not_fabricated() -> None:
    gateway, _ = _gemini_fallback()

    result = await gateway.structure(_STRUCTURE_REQUEST)

    # The returned fields are the secondary's actual provider response - the
    # mock/fabrication path is never a chain terminator in the real-provider chain.
    assert result.chief_complaints == ["fever"]
    assert result.symptoms == ["chills"]
    assert result.confidence == 0.92


async def test_fallback_engagement_logs_degradation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Engaging the secondary is a degradation decision and must be visible to
    operators (third-party-integration-standards S2, ai-engineering-standards A6)."""
    caplog.set_level(logging.WARNING)
    gateway, _ = _gemini_fallback()

    await gateway.structure(_STRUCTURE_REQUEST)

    assert any(
        "engaging secondary fallback" in record.message and record.levelname == "WARNING"
        for record in caplog.records
    )


# ---------------------------------------------------------------------------
# Outage fallback on transcribe / draft_rx legs (full Ext002AiProvider)
# ---------------------------------------------------------------------------


async def test_transcribe_outage_falls_back_to_secondary() -> None:
    primary_transport = _RecordingTransport(_outage_response())
    secondary_transport = _RecordingTransport(httpx.Response(200, json=_TRANSCRIBE_BODY))
    gateway = FallbackAiGateway(
        _ext_gateway(primary_transport),
        _META_GROQ,
        _ext_gateway(secondary_transport),
        _META_GEMINI,
    )

    result = await gateway.transcribe(_TRANSCRIBE_REQUEST)

    assert result.transcript == _TRANSCRIBE_BODY["transcript"]
    assert len(secondary_transport.requests) >= 1
    assert gateway.last_effective_provider == "gemini"


async def test_draft_rx_outage_falls_back_to_secondary() -> None:
    primary_transport = _RecordingTransport(_outage_response())
    secondary_transport = _RecordingTransport(httpx.Response(200, json=_DRAFT_RX_BODY))
    gateway = FallbackAiGateway(
        _ext_gateway(primary_transport),
        _META_GROQ,
        _ext_gateway(secondary_transport),
        _META_GEMINI,
    )

    result = await gateway.draft_rx(_DRAFT_RX_REQUEST)

    assert result.rx_items[0].name == "paracetamol"
    assert len(secondary_transport.requests) >= 1
    assert gateway.last_effective_model == "gemini-2.0-flash"


async def test_transcribe_outage_both_down_raises() -> None:
    gateway = FallbackAiGateway(
        _ext_gateway(_RecordingTransport(_outage_response())),
        _META_GROQ,
        _ext_gateway(_RecordingTransport(_outage_response())),
        _META_GEMINI,
    )

    with pytest.raises(Ext002CallError, match="failed after") as exc_info:
        await gateway.transcribe(_TRANSCRIBE_REQUEST)

    assert exc_info.value.retries_exhausted is True


# ---------------------------------------------------------------------------
# Primary contract rejection -> propagates, secondary NEVER called
# ---------------------------------------------------------------------------


async def test_primary_contract_rejection_propagates_without_fallback() -> None:
    secondary_transport = _RecordingTransport(httpx.Response(200, json=_CHAT_SUCCESS_BODY))
    gateway = FallbackAiGateway(
        _openai_gateway(_RecordingTransport(_rejection_response())),
        _META_GROQ,
        _openai_gateway(
            secondary_transport,
            base_url=_GEMINI_URL,
            model="gemini-2.0-flash",
        ),
        _META_GEMINI,
    )

    with pytest.raises(Ext002CallError, match="400") as exc_info:
        await gateway.structure(_STRUCTURE_REQUEST)

    assert exc_info.value.retries_exhausted is False
    assert secondary_transport.requests == []


async def test_unsupported_leg_rejection_never_falls_back() -> None:
    # A contract rejection on the OpenAI-compatible adapter must not engage the
    # secondary - fallback is reserved for genuine outages. transcribe now posts
    # to the real /audio/transcriptions leg (#387), so its rejection is a 4xx;
    # draft_rx still raises the not-supported rejection (retries_exhausted=False).
    primary = _openai_gateway(_RecordingTransport(_rejection_response()))
    secondary_transport = _RecordingTransport(httpx.Response(200, json=_TRANSCRIBE_BODY))

    gateway = FallbackAiGateway(
        primary,
        _META_GROQ,
        _ext_gateway(secondary_transport),
        _META_GEMINI,
    )

    with pytest.raises(Ext002CallError, match="400"):
        await gateway.transcribe(_TRANSCRIBE_REQUEST)
    with pytest.raises(Ext002CallError, match="not supported"):
        await gateway.draft_rx(_DRAFT_RX_REQUEST)

    assert secondary_transport.requests == []


async def test_effective_is_none_after_contract_rejection() -> None:
    gateway = FallbackAiGateway(
        _openai_gateway(_RecordingTransport(_rejection_response())),
        _META_GROQ,
        _openai_gateway(
            _RecordingTransport(httpx.Response(200, json=_CHAT_SUCCESS_BODY)),
            base_url=_GEMINI_URL,
            model="gemini-2.0-flash",
        ),
        _META_GEMINI,
    )

    with pytest.raises(Ext002CallError):
        await gateway.structure(_STRUCTURE_REQUEST)

    assert gateway.last_effective_provider is None
    assert gateway.last_effective_model is None


# ---------------------------------------------------------------------------
# Open primary breaker -> secondary routed
# ---------------------------------------------------------------------------


async def test_open_primary_breaker_routes_to_secondary() -> None:
    """A real CircuitBreakerAiGateway whose breaker is open short-circuits to
    secondary (the open-breaker error is an outage, retries_exhausted=True)."""
    outage = _RecordingTransport(_outage_response())
    breaker_primary = _breaker(_openai_gateway(outage))
    # Trip the breaker: two consecutive outage failures open it (threshold=2).
    for _ in range(2):
        with pytest.raises(Ext002CallError, match="failed after"):
            await breaker_primary.structure(_STRUCTURE_REQUEST)

    secondary_transport = _RecordingTransport(httpx.Response(200, json=_CHAT_SUCCESS_BODY))
    gateway = FallbackAiGateway(
        breaker_primary,
        _META_GROQ,
        _openai_gateway(
            secondary_transport,
            base_url=_GEMINI_URL,
            model="gemini-2.0-flash",
        ),
        _META_GEMINI,
    )

    result = await gateway.structure(_STRUCTURE_REQUEST)

    assert result.model_dump() == _STRUCTURE_BODY
    # The open breaker refused without touching the primary provider again:
    # 2 tripped calls x (1 + max_retries) attempts.
    assert len(outage.requests) == 2 * (DEFAULT_AI_MAX_RETRIES + 1)
    assert len(secondary_transport.requests) >= 1
    assert gateway.last_effective_provider == "gemini"


# ---------------------------------------------------------------------------
# Both outaged -> outage error, no result
# ---------------------------------------------------------------------------


async def test_both_outaged_raises_outage_without_fabricated_result() -> None:
    # The secondary's failure is distinctive ("secondary down") so we can assert
    # the surfaced error is the PRIMARY's outage error (brief's routing rule),
    # never a partial result or a fabricated mock.
    secondary = _FailingStub(Ext002CallError("secondary down", retries_exhausted=True))
    gateway = FallbackAiGateway(
        _openai_gateway(_RecordingTransport(_outage_response())),
        _META_GROQ,
        secondary,
        _META_GEMINI,
    )

    with pytest.raises(Ext002CallError, match="OpenAI-compatible") as exc_info:
        await gateway.structure(_STRUCTURE_REQUEST)

    assert exc_info.value.retries_exhausted is True
    assert "secondary down" not in str(exc_info.value)
    assert gateway.last_effective_provider is None
    assert gateway.last_effective_model is None


# ---------------------------------------------------------------------------
# Recovery is automatic (breaker cooldown + recovery probe)
# ---------------------------------------------------------------------------


async def test_recovery_probe_after_cooldown_returns_to_primary() -> None:
    """The chain needs no recovery logic: after the primary breaker's cooldown
    elapses, the next call is a recovery probe and success closes the breaker."""
    now: dict[str, float] = {"time": 0.0}

    def clock() -> float:
        return now["time"]

    switching = _SwitchingTransport()
    breaker_primary = _breaker(_openai_gateway(switching), clock=clock)
    for _ in range(2):
        with pytest.raises(Ext002CallError, match="failed after"):
            await breaker_primary.structure(_STRUCTURE_REQUEST)

    # While the breaker is open, calls are refused without the provider.
    secondary_transport = _RecordingTransport(httpx.Response(200, json=_CHAT_SUCCESS_BODY))
    gateway = FallbackAiGateway(
        breaker_primary,
        _META_GROQ,
        _openai_gateway(
            secondary_transport,
            base_url=_GEMINI_URL,
            model="gemini-2.0-flash",
        ),
        _META_GEMINI,
    )
    await gateway.structure(_STRUCTURE_REQUEST)
    assert gateway.last_effective_provider == "gemini"
    requests_after_refusal = len(switching.requests)

    # The primary recovers and its cooldown elapses: the next call becomes a
    # recovery probe through the primary, which closes the breaker.
    switching.available = True
    now["time"] = 30.0

    result = await gateway.structure(_STRUCTURE_REQUEST)

    assert result.chief_complaints == ["fever"]
    assert len(switching.requests) > requests_after_refusal
    assert gateway.last_effective_provider == "groq"
    assert gateway.last_effective_model == "llama-3.3-70b-versatile"


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


async def test_fallback_gateway_implements_all_three_operations() -> None:
    gateway = FallbackAiGateway(
        _openai_gateway(_RecordingTransport(httpx.Response(200, json=_CHAT_SUCCESS_BODY))),
        _META_GROQ,
        _openai_gateway(
            _RecordingTransport(httpx.Response(200, json=_CHAT_SUCCESS_BODY)),
            base_url=_GEMINI_URL,
            model="gemini-2.0-flash",
        ),
        _META_GEMINI,
    )

    assert callable(gateway.transcribe)
    assert callable(gateway.structure)
    assert callable(gateway.draft_rx)


async def test_fallback_gateway_typed_as_port() -> None:
    port: AiGateway = FallbackAiGateway(
        _openai_gateway(_RecordingTransport(httpx.Response(200, json=_CHAT_SUCCESS_BODY))),
        _META_GROQ,
        _openai_gateway(
            _RecordingTransport(httpx.Response(200, json=_CHAT_SUCCESS_BODY)),
            base_url=_GEMINI_URL,
            model="gemini-2.0-flash",
        ),
        _META_GEMINI,
    )

    result = await port.structure(_STRUCTURE_REQUEST)

    assert result.model_dump() == _STRUCTURE_BODY


# ---------------------------------------------------------------------------
# AI-tracing gate (pre-commit check stays green)
# ---------------------------------------------------------------------------


def test_ai_tracing_gate_passes_over_fallback_adapter() -> None:
    from pathlib import Path

    from scripts.check_ai_tracing import check_ai_tracing

    fallback_path = (
        Path(__file__).resolve().parents[2]
        / "apps"
        / "backend"
        / "modules"
        / "intake"
        / "adapters"
        / "ai_provider_fallback.py"
    )
    assert check_ai_tracing([fallback_path]) == ()
