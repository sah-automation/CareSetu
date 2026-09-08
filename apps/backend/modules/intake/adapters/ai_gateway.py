"""MOD-005: EXT-002 AI gateway port (standard A6, PHASE-7 T05 #348).

The single typed seam every LLM adapter satisfies. All LLM calls for the
transcribe -> structure -> pre-summary pipeline (and Phase 8's rx drafting)
flow through this port; domain code never touches a concrete provider. The
provider is selected by configuration (``ai_provider`` in ``Settings``), never
by code - swapping a provider is a new adapter, zero domain changes
(third-party-integration-standards §7).

The request models declare the **egress boundary** (``NFR-SEC-006``): a call to
EXT-002 may carry only intake context - the declared language, age range, and
sex, plus the transcript/text (and the audio clip being transcribed) - never a
patient's name, phone, or the full record. ``AiEgressContext`` is the one
patient-shaped thing that may cross the wire.

This module carries the DTOs and the abstract ``AiGateway`` protocol only; the
concrete adapters (mock and provider) live next to it and implement the port.
The protocol methods are abstract stubs, so no tracing is required here - the
concrete LLM-calling methods carry the ``@observe`` annotations where the
concrete adapters are defined.
"""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

LANG_HI = "hi"
LANG_EN = "en"

SEX_MALE = "male"
SEX_FEMALE = "female"
SEX_OTHER = "other"


class AiEgressContext(BaseModel):
    """The only patient context allowed to leave MOD-005 (NFR-SEC-006).

    Egress to EXT-002 carries intake context only - the declared language, the
    age range, and sex - never name, phone, or the full record. Every request
    model that travels to the provider embeds exactly this. Unknown fields are
    rejected (fail-closed), never silently carried.
    """

    model_config = ConfigDict(extra="forbid")

    language: Literal["hi", "en"]
    age_range: str
    sex: Literal["male", "female", "other"]


class TranscribeRequest(BaseModel):
    """Input to the transcribe leg: one intake audio clip plus minimal context.

    ``audio_ref`` is a pseudonymous reference to the intake media (the patient's
    own words, expected by the transcribe leg), not a patient identifier. The
    patient-shaped context is bounded to ``AiEgressContext``; extra fields are
    rejected (fail-closed).
    """

    model_config = ConfigDict(extra="forbid")

    audio_ref: str
    mode: Literal["voice"]
    context: AiEgressContext


class TranscribeResult(BaseModel):
    """The transcript plus the provider's measured transcription confidence."""

    transcript: str
    confidence: float
    language: Literal["hi", "en"]


class StructureRequest(BaseModel):
    """Input to the structure leg: the transcribed text plus minimal context."""

    model_config = ConfigDict(extra="forbid")

    transcript: str
    source: Literal["voice", "text"]
    context: AiEgressContext


class StructureResult(BaseModel):
    """The structured clinical fields plus provider self-reported confidence.

    ``confidence`` is the provider's ``structuring_confidence`` (ADR-0001 /
    glossary): compared against the 0.70 threshold downstream to derive the
    ``low_confidence`` flag and force doctor review when below.
    """

    chief_complaints: list[str]
    symptoms: list[str]
    duration: str
    confidence: float


class DraftRxRequest(BaseModel):
    """Phase 8 contract-only input to the rx-drafting leg (declared now).

    Carries only reference ids plus the patient history summary - the drafting
    input, never name/phone/full record (NFR-SEC-006). This leg becomes live in
    Phase 8; the port declares the contract before any caller uses it. Extra
    fields are rejected (fail-closed).
    """

    model_config = ConfigDict(extra="forbid")

    doctor_input_ref: str
    pre_summary_ref: str
    patient_history_summary: str
    context: AiEgressContext


class RxItem(BaseModel):
    """One drafted prescription line (name, dose, duration)."""

    name: str
    dose: str
    duration: str


class DraftRxResult(BaseModel):
    """The drafted prescription lines plus provider confidence."""

    rx_items: list[RxItem]
    confidence: float


class AiGateway(Protocol):
    """Port every EXT-002 adapter satisfies (A6) - the three egress operations.

    Abstract by declaration; concrete adapters implement each operation and own
    the tracing (``@observe``) on the methods that make the LLM call.
    """

    async def transcribe(self, request: TranscribeRequest) -> TranscribeResult: ...

    async def structure(self, request: StructureRequest) -> StructureResult: ...

    async def draft_rx(self, request: DraftRxRequest) -> DraftRxResult: ...


__all__ = [
    "LANG_EN",
    "LANG_HI",
    "SEX_FEMALE",
    "SEX_MALE",
    "SEX_OTHER",
    "AiEgressContext",
    "AiGateway",
    "DraftRxRequest",
    "DraftRxResult",
    "RxItem",
    "StructureRequest",
    "StructureResult",
    "TranscribeRequest",
    "TranscribeResult",
]
