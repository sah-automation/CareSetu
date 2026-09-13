"""PHASE-7 T05 (#348): EXT-002 AI gateway port + mock provider + AI config.

Acceptance contract from the ticket: the gateway port declares transcribe/
structure/draft_rx and both mock and provider adapters implement them; settings
select the provider fail-closed (real provider key refused in dev/test unless
demo mode forces the mock); egress payloads carry only intake context (no
name/phone/full record); the pre-commit AI-tracing gate stays green; unit tests
switch clean vs low confidence via the mock knob.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError
from scripts.check_ai_tracing import check_ai_tracing

from app.config import Settings
from modules.intake.adapters.ai_gateway import (
    AiEgressContext,
    DraftRxRequest,
    StructureRequest,
    TranscribeRequest,
    TranscribeResult,
)
from modules.intake.adapters.ai_provider_ext import (
    CircuitBreakerAiGateway,
    Ext002AiProvider,
    Ext002CallError,
    build_ai_gateway,
)
from modules.intake.adapters.ai_provider_fallback import FallbackAiGateway
from modules.intake.adapters.ai_provider_mock import (
    MOCK_AI_MODEL,
    MOCK_AI_PROVIDER,
    MOCK_CONFIDENCE_CLEAN,
    MOCK_CONFIDENCE_LOW,
    MockAiProvider,
    build_mock_ai_gateway,
)
from modules.intake.adapters.ai_provider_openai_compatible import OpenAiCompatibleAdapter

REPO_ROOT = Path(__file__).resolve().parents[2]


def _intake_adapter_files() -> list[Path]:
    adapters = REPO_ROOT / "apps" / "backend" / "modules" / "intake" / "adapters"
    return sorted(adapters.glob("ai_*.py"))


def _context() -> AiEgressContext:
    return AiEgressContext(language="hi", age_range="30-40", sex="male")


async def test_mock_transcribe_clean_confidence() -> None:
    provider = build_mock_ai_gateway()
    result = await provider.transcribe(
        TranscribeRequest(audio_ref="media/abc", mode="voice", context=_context())
    )

    assert isinstance(provider, MockAiProvider)
    assert result.transcript
    assert result.confidence == MOCK_CONFIDENCE_CLEAN
    assert result.language == "hi"
    assert result.input_tokens == 0
    assert result.output_tokens == 0


async def test_mock_structure_clean_confidence() -> None:
    provider = MockAiProvider()
    result = await provider.structure(
        StructureRequest(transcript="mujhe bukhar hai", source="voice", context=_context())
    )

    assert result.chief_complaints == ["mock chief complaint"]
    assert result.symptoms == ["mock symptom"]
    assert result.duration == "1 week"
    assert result.confidence == MOCK_CONFIDENCE_CLEAN
    assert result.input_tokens == 0
    assert result.output_tokens == 0


async def test_mock_draft_rx_clean_confidence_declared_contract() -> None:
    provider = MockAiProvider()
    result = await provider.draft_rx(
        DraftRxRequest(
            doctor_input_ref="voice_note/1",
            pre_summary_ref="pre_summary/2",
            patient_history_summary="mock history",
            context=_context(),
        )
    )

    assert len(result.rx_items) == 1
    assert result.rx_items[0].name == "mock medication"
    assert result.confidence == MOCK_CONFIDENCE_CLEAN
    assert result.input_tokens == 0
    assert result.output_tokens == 0


@pytest.mark.parametrize(
    "operator",
    [
        pytest.param(
            lambda p: p.transcribe(
                TranscribeRequest(audio_ref="media/abc", mode="voice", context=_context())
            ),
            id="transcribe",
        ),
        pytest.param(
            lambda p: p.structure(
                StructureRequest(transcript="mujhe bukhar hai", source="voice", context=_context())
            ),
            id="structure",
        ),
        pytest.param(
            lambda p: p.draft_rx(
                DraftRxRequest(
                    doctor_input_ref="voice_note/1",
                    pre_summary_ref="pre_summary/2",
                    patient_history_summary="mock history",
                    context=_context(),
                )
            ),
            id="draft_rx",
        ),
    ],
)
async def test_mock_low_confidence_knob(
    operator: Callable[[MockAiProvider], Awaitable[Any]],
) -> None:
    provider = MockAiProvider(confidence_level="low")

    result = await operator(provider)

    assert result.confidence == MOCK_CONFIDENCE_LOW
    assert result.confidence < 0.70


async def test_mock_records_only_what_was_sent() -> None:
    provider = MockAiProvider()
    request = StructureRequest(transcript="mujhe bukhar hai", source="voice", context=_context())

    await provider.structure(request)

    assert provider.calls == [request]


def test_mock_rejects_unknown_confidence_level() -> None:
    from modules.intake.adapters.ai_provider_mock import ConfidenceLevel

    with pytest.raises(ValueError, match="confidence_level"):
        MockAiProvider(confidence_level=cast(ConfidenceLevel, "medium"))


def test_mock_exposes_effective_provider_and_model() -> None:
    provider = MockAiProvider()

    assert provider.effective_provider == MOCK_AI_PROVIDER
    assert provider.effective_model == MOCK_AI_MODEL


async def test_provider_adapter_implements_all_three_operations() -> None:
    provider = Ext002AiProvider(api_key="k", base_url="https://ext.example")

    assert callable(provider.transcribe)
    assert callable(provider.structure)
    assert callable(provider.draft_rx)


async def test_breaker_adapter_implements_all_three_operations() -> None:
    gateway = CircuitBreakerAiGateway(
        Ext002AiProvider(api_key="k", base_url="https://ext.example"),
        threshold=2,
        cooldown_seconds=1.0,
    )

    assert callable(gateway.transcribe)
    assert callable(gateway.structure)
    assert callable(gateway.draft_rx)


def test_ai_tracing_gate_passes_over_intake_adapters() -> None:
    assert check_ai_tracing(_intake_adapter_files()) == ()


def test_build_ai_gateway_default_is_mock() -> None:
    gateway = build_ai_gateway(Settings())

    assert isinstance(gateway, MockAiProvider)


def test_build_ai_gateway_mock_knob() -> None:
    gateway = build_ai_gateway(Settings(ai_provider="mock"))

    assert isinstance(gateway, MockAiProvider)


def _staging_openai_settings() -> Settings:
    return Settings(
        app_environment="staging",
        ai_provider="openai_compatible",
        ai_api_key="secret-key",
        ai_base_url="https://ext.example",
        ai_model="grok-3",
    )


def test_build_ai_gateway_provider_path_wraps_openai_compatible() -> None:
    gateway = build_ai_gateway(_staging_openai_settings())

    assert isinstance(gateway, CircuitBreakerAiGateway)
    assert isinstance(gateway._adapter, OpenAiCompatibleAdapter)
    assert gateway.effective_provider == "openai_compatible"
    assert gateway.effective_model == "grok-3"


def test_build_ai_gateway_wires_asr_model_from_settings() -> None:
    settings = Settings(
        app_environment="staging",
        ai_provider="openai_compatible",
        ai_api_key="secret-key",
        ai_base_url="https://ext.example",
        ai_model="grok-3",
        ai_asr_model="whisper-large-v3",
    )

    gateway = build_ai_gateway(settings)

    assert isinstance(gateway, CircuitBreakerAiGateway)
    assert gateway._adapter._asr_model == "whisper-large-v3"


def test_build_ai_gateway_asr_model_defaults_to_freemium_tier() -> None:
    gateway = build_ai_gateway(_staging_openai_settings())

    assert isinstance(gateway, CircuitBreakerAiGateway)
    assert gateway._adapter._asr_model == "whisper-large-v3-turbo"


def _staging_openai_fallback_settings() -> Settings:
    return Settings(
        app_environment="staging",
        ai_provider="openai_compatible",
        ai_api_key="secret-key",
        ai_base_url="https://api.groq.example/openai/v1",
        ai_model="llama-3.3-70b-versatile",
        ai_fallback_provider="openai_compatible",
        ai_fallback_api_key="fallback-key",
        ai_fallback_base_url="https://gemini.example/v1",
        ai_fallback_model="gemini-2.0-flash",
    )


def test_build_ai_gateway_openai_compatible_without_fallback_is_breaker_wrapped() -> None:
    gateway = build_ai_gateway(_staging_openai_settings())

    assert isinstance(gateway, CircuitBreakerAiGateway)
    assert not isinstance(gateway, FallbackAiGateway)


def test_build_ai_gateway_openai_compatible_with_fallback_composes_chain() -> None:
    gateway = build_ai_gateway(_staging_openai_fallback_settings())

    assert isinstance(gateway, FallbackAiGateway)
    # Each chain leg is itself a breaker-wrapped OpenAI-compatible adapter.
    assert isinstance(gateway._primary, CircuitBreakerAiGateway)
    assert isinstance(gateway._primary._adapter, OpenAiCompatibleAdapter)
    assert isinstance(gateway._secondary, CircuitBreakerAiGateway)
    assert isinstance(gateway._secondary._adapter, OpenAiCompatibleAdapter)
    # The effective surface is None until the first successful call - the
    # pipeline reads it only after a success.
    assert gateway.effective_provider is None
    assert gateway.effective_model is None


def test_build_ai_gateway_dev_override_wires_openai_compatible() -> None:
    settings = Settings(
        app_environment="dev",
        ai_provider="openai_compatible",
        ai_api_key="secret-key",
        ai_base_url="https://ext.example",
        ai_model="grok-3",
        ai_allow_dev_provider=True,
    )

    gateway = build_ai_gateway(settings)

    assert isinstance(gateway, CircuitBreakerAiGateway)
    assert gateway.effective_model == "grok-3"


@pytest.mark.parametrize(
    "environment",
    [
        pytest.param("dev", id="dev"),
        pytest.param("test", id="test"),
        pytest.param("DEV", id="dev-uppercase"),
    ],
)
def test_ai_provider_key_refused_in_dev_test_without_demo(environment: str) -> None:
    with pytest.raises(ValueError, match="gated to staging/production"):
        Settings(
            app_environment=environment,
            ai_provider="openai_compatible",
            ai_api_key="secret-key",
            ai_base_url="https://ext.example",
            ai_model="grok-3",
        )


def test_ai_provider_dev_override_permits_dev_use() -> None:
    Settings(
        app_environment="dev",
        ai_provider="openai_compatible",
        ai_api_key="secret-key",
        ai_base_url="https://ext.example",
        ai_model="grok-3",
        ai_allow_dev_provider=True,
    )


def test_ai_provider_openai_compatible_accepted_in_staging() -> None:
    settings = _staging_openai_settings()

    assert settings.ai_provider == "openai_compatible"
    assert settings.ai_model == "grok-3"


def test_ai_provider_production_requires_key() -> None:
    with pytest.raises(ValueError, match="AI_API_KEY"):
        Settings(
            app_environment="production",
            ai_provider="openai_compatible",
            ai_api_key="",
            ai_base_url="https://ext.example",
            ai_model="grok-3",
        )


def test_ai_provider_production_requires_base_url() -> None:
    with pytest.raises(ValueError, match="AI_BASE_URL"):
        Settings(
            app_environment="production",
            ai_provider="openai_compatible",
            ai_api_key="secret-key",
            ai_base_url="",
            ai_model="grok-3",
        )


def test_ai_provider_production_requires_model() -> None:
    with pytest.raises(ValueError, match="AI_MODEL"):
        Settings(
            app_environment="production",
            ai_provider="openai_compatible",
            ai_api_key="secret-key",
            ai_base_url="https://ext.example",
            ai_model="",
        )


def test_demo_mode_forces_mock() -> None:
    with pytest.raises(ValueError, match="demo flag must never ride"):
        Settings(
            app_environment="production",
            demo_mode=True,
            ai_provider="openai_compatible",
            ai_api_key="secret-key",
            ai_base_url="https://ext.example",
            ai_model="grok-3",
        )


def test_demo_mode_with_mock_is_allowed() -> None:
    Settings(demo_mode=True, ai_provider="mock")


def test_unsupported_ai_provider_is_refused() -> None:
    with pytest.raises(ValueError, match="unsupported ai_provider"):
        Settings(ai_provider="gemini")


def test_fallback_partial_set_refused() -> None:
    with pytest.raises(ValueError, match="all-or-none"):
        Settings(
            ai_fallback_provider="openai_compatible",
            ai_fallback_base_url="https://fallback.example",
            ai_fallback_api_key="fallback-key",
        )


def test_fallback_all_or_none_missing_provider_refused() -> None:
    with pytest.raises(ValueError, match="AI_FALLBACK_PROVIDER"):
        Settings(
            ai_fallback_base_url="https://fallback.example",
            ai_fallback_api_key="fallback-key",
            ai_fallback_model="fallback-model",
        )


def test_fallback_all_or_none_missing_model_refused() -> None:
    with pytest.raises(ValueError, match="AI_FALLBACK_MODEL"):
        Settings(
            ai_fallback_provider="openai_compatible",
            ai_fallback_base_url="https://fallback.example",
            ai_fallback_api_key="fallback-key",
        )


def test_fallback_provider_value_whitelist() -> None:
    with pytest.raises(ValueError, match="ai_fallback_provider must be"):
        Settings(
            ai_fallback_provider="mock",
            ai_fallback_base_url="https://fallback.example",
            ai_fallback_api_key="fallback-key",
            ai_fallback_model="fallback-model",
        )


def test_fallback_complete_set_accepted() -> None:
    settings = Settings(
        ai_fallback_provider="openai_compatible",
        ai_fallback_base_url="https://fallback.example",
        ai_fallback_api_key="fallback-key",
        ai_fallback_model="fallback-model",
    )

    assert settings.ai_fallback_provider == "openai_compatible"
    assert settings.ai_fallback_model == "fallback-model"


def test_ai_timeout_must_honour_ext002_discipline() -> None:
    with pytest.raises(ValueError, match="ai_timeout_seconds"):
        Settings(ai_timeout_seconds=45.0)


def test_egress_transcribe_payload_carries_only_intake_context() -> None:
    request = TranscribeRequest(audio_ref="media/abc", mode="voice", context=_context())

    payload = request.model_dump()
    assert payload == {
        "audio_ref": "media/abc",
        "audio_bytes": None,
        "mode": "voice",
        "context": {"language": "hi", "age_range": "30-40", "sex": "male"},
    }
    assert "name" not in payload
    assert "phone" not in payload


def test_egress_structure_payload_carries_only_intake_context() -> None:
    request = StructureRequest(transcript="mujhe bukhar hai", source="voice", context=_context())

    payload = request.model_dump()
    assert set(payload) == {"transcript", "source", "context"}
    assert "name" not in payload
    assert "phone" not in payload


def test_egress_draft_rx_payload_carries_only_declared_context() -> None:
    request = DraftRxRequest(
        doctor_input_ref="voice_note/1",
        pre_summary_ref="pre_summary/2",
        patient_history_summary="mock history",
        context=_context(),
    )

    payload = request.model_dump()
    assert set(payload) == {
        "doctor_input_ref",
        "pre_summary_ref",
        "patient_history_summary",
        "context",
    }
    assert "name" not in payload
    assert "phone" not in payload


def test_egress_rejects_patient_identifiers() -> None:
    with pytest.raises(ValidationError):
        TranscribeRequest.model_validate(
            {
                "audio_ref": "media/abc",
                "mode": "voice",
                "context": {"language": "hi", "age_range": "30-40", "sex": "male"},
                "name": "Raj",
            }
        )


def test_egress_rejects_unhealthy_sex_value() -> None:
    with pytest.raises(ValidationError):
        AiEgressContext.model_validate({"language": "hi", "age_range": "30-40", "sex": "unknown"})


async def test_build_mock_gateway_typed_as_port() -> None:
    from modules.intake.adapters.ai_gateway import AiGateway

    gateway: AiGateway = build_mock_ai_gateway(confidence_level="low")
    result = await gateway.structure(
        StructureRequest(transcript="x", source="text", context=_context())
    )
    assert result.confidence == MOCK_CONFIDENCE_LOW


async def test_provider_wire_payloads_carry_only_intake_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = Ext002AiProvider(api_key="k", base_url="https://ext.example")
    captured: list[dict[str, object]] = []

    async def _fake_post(path: str, payload: dict[str, object]) -> dict[str, object]:
        captured.append(payload)
        if path.endswith("transcribe"):
            return {"transcript": "t", "confidence": 0.8, "language": "hi"}
        if path.endswith("structure"):
            return {"chief_complaints": [], "symptoms": [], "duration": "", "confidence": 0.8}
        return {"rx_items": [{"name": "n", "dose": "d", "duration": "u"}], "confidence": 0.8}

    monkeypatch.setattr(provider, "_post_json", _fake_post)

    await provider.transcribe(
        TranscribeRequest(audio_ref="media/1", mode="voice", context=_context())
    )
    await provider.structure(StructureRequest(transcript="x", source="text", context=_context()))
    await provider.draft_rx(
        DraftRxRequest(
            doctor_input_ref="voice_note/1",
            pre_summary_ref="pre_summary/2",
            patient_history_summary="mock history",
            context=_context(),
        )
    )

    assert len(captured) == 3
    for payload in captured:
        assert "name" not in payload
        assert "phone" not in payload
    assert set(captured[0]) == {"audio_ref", "mode", "language", "age_range", "sex"}
    assert set(captured[1]) == {"transcript", "source", "language", "age_range", "sex"}
    assert set(captured[2]) == {
        "doctor_input_ref",
        "pre_summary_ref",
        "patient_history_summary",
        "language",
        "age_range",
        "sex",
    }


async def test_breaker_trips_only_on_outage_not_contract_rejection() -> None:
    calls = 0

    class _FailingProvider(Ext002AiProvider):
        async def transcribe(self, request: TranscribeRequest) -> TranscribeResult:
            nonlocal calls
            calls += 1
            raise Ext002CallError("rejected", retries_exhausted=False)

    breaker = CircuitBreakerAiGateway(
        _FailingProvider(api_key="k", base_url="https://ext.example"),
        threshold=2,
        cooldown_seconds=30.0,
        clock=lambda: 0.0,
    )

    for _ in range(4):
        with pytest.raises(Ext002CallError):
            await breaker.transcribe(
                TranscribeRequest(audio_ref="media/1", mode="voice", context=_context())
            )

    assert calls == 4
