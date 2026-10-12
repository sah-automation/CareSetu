"""MOD-005: deterministic in-process EXT-002 mock (PHASE-7 T05 #348).

The CI/dev/test default adapter. It implements the same ``AiGateway`` port as
the real provider but makes no external call - it returns a fixed structured
result whose confidence is switched by a knob, so the unit/integration suites
(and the pipeline tests in later tickets) can exercise the clean (~0.8) and low
(~0.5) confidence paths deterministically without any provider.

Clean confidence (default) maps to "at-or-above the 0.70 structuring
threshold", i.e. not low_confidence; low confidence (0.5) maps to
"strictly below 0.70", forcing doctor review (ADR-0001). The mock records every
call so a test can assert what would have been sent to the provider - and, by
construction, that only the intake context was in it.
"""

from __future__ import annotations

import time
from typing import Literal

from langfuse import observe

from modules.intake.adapters.ai_gateway import (
    AiGateway,
    DraftRxRequest,
    DraftRxResult,
    RxItem,
    StructureRequest,
    StructureResult,
    TranscribeRequest,
    TranscribeResult,
)
from observability.langfuse_span import set_span_metadata

MOCK_CONFIDENCE_CLEAN = 0.8
MOCK_CONFIDENCE_LOW = 0.5

#: The mock's identity on the ``intake_ai_jobs`` provider/model columns
#: (``{provider}-model`` convention). Owned here - the mock adapter is the only
#: thing that knows its own name - and re-exported from ``adapters/__init__.py``
#: so the pipeline bookkeeping reads one constant.
MOCK_AI_PROVIDER = "mock"
MOCK_AI_MODEL = "mock-model"

ConfidenceLevel = Literal["clean", "low"]


class MockAiProvider:
    """Deterministic EXT-002 mock - no external call, switchable confidence.

    ``confidence_level`` selects whether returned confidence is clean (~0.8,
    default - not low_confidence) or low (~0.5, forces doctor review). Tests and
    CI switch the knob to drive both pipeline branches.
    """

    def __init__(self, *, confidence_level: ConfidenceLevel = "clean") -> None:
        if confidence_level not in {"clean", "low"}:
            raise ValueError(
                f"unsupported mock confidence_level {confidence_level!r}; expected 'clean' or 'low'"
            )
        self._confidence = (
            MOCK_CONFIDENCE_CLEAN if confidence_level == "clean" else MOCK_CONFIDENCE_LOW
        )
        self._calls: list[object] = []

    @property
    def confidence(self) -> float:
        """The confidence value this mock currently returns."""
        return self._confidence

    @property
    def effective_provider(self) -> str:
        """The mock's provider identity (the ``ai_provider`` whitelist value)."""
        return MOCK_AI_PROVIDER

    @property
    def effective_model(self) -> str:
        """The mock's model identity, stable regardless of the confidence knob."""
        return MOCK_AI_MODEL

    @property
    def calls(self) -> list[object]:
        """Every request this mock has received (for test assertions)."""
        return list(self._calls)

    def _record_span(self, task_type: str, *, started: float) -> None:
        """Attach the allow-listed span metadata for a mock call (PHASE-14A B2).

        The mock reports zero tokens and its canned confidence; the call goes
        through the same allow-list seam as the real adapter so the PHI-free
        contract is identical. A no-op when Langfuse is off, and never raises.
        """
        set_span_metadata(
            task_type=task_type,
            provider=self.effective_provider,
            model=self.effective_model,
            input_tokens=0,
            output_tokens=0,
            duration_ms=int((time.monotonic() - started) * 1000),
            cost_paise=0,
            confidence=self._confidence,
            status="success",
        )

    @observe(name="ai_transcribe", capture_input=False, capture_output=False)
    async def transcribe(self, request: TranscribeRequest) -> TranscribeResult:
        started = time.monotonic()
        self._calls.append(request)
        result = TranscribeResult(
            transcript="mock transcript",
            confidence=self._confidence,
            language=request.context.language,
            input_tokens=0,
            output_tokens=0,
        )
        self._record_span("transcribe", started=started)
        return result

    @observe(name="ai_structure", capture_input=False, capture_output=False)
    async def structure(self, request: StructureRequest) -> StructureResult:
        started = time.monotonic()
        self._calls.append(request)
        result = StructureResult(
            chief_complaints=["mock chief complaint"],
            symptoms=["mock symptom"],
            duration="1 week",
            confidence=self._confidence,
            input_tokens=0,
            output_tokens=0,
        )
        self._record_span("structure", started=started)
        return result

    @observe(name="ai_draft_rx", capture_input=False, capture_output=False)
    async def draft_rx(self, request: DraftRxRequest) -> DraftRxResult:
        started = time.monotonic()
        self._calls.append(request)
        result = DraftRxResult(
            rx_items=[
                RxItem(
                    name="mock medication",
                    dose="1 tablet",
                    duration="5 days",
                    frequency="once daily",
                )
            ],
            confidence=self._confidence,
            input_tokens=0,
            output_tokens=0,
        )
        self._record_span("draft_rx", started=started)
        return result


def build_mock_ai_gateway(
    *,
    confidence_level: ConfidenceLevel = "clean",
) -> AiGateway:
    """Resolve the mock adapter for CI/dev/tests.

    Returns the mock typed as the ``AiGateway`` port so callers depend only on
    the interface. ``confidence_level`` maps to the provider-selection knob for
    tests that must force the low-confidence branch.
    """
    return MockAiProvider(confidence_level=confidence_level)


__all__ = [
    "MOCK_AI_MODEL",
    "MOCK_AI_PROVIDER",
    "MOCK_CONFIDENCE_CLEAN",
    "MOCK_CONFIDENCE_LOW",
    "ConfidenceLevel",
    "MockAiProvider",
    "build_mock_ai_gateway",
]
