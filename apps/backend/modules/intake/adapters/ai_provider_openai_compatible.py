"""MOD-005: OpenAI-compatible adapter for standard OpenAI REST endpoints.

This adapter implements the ``AiGateway`` port against any REST endpoint that
conforms to the OpenAI-compatible API. ``structure`` posts to
``{base_url}/chat/completions``; ``transcribe`` posts the decrypted clip as
``multipart/form-data`` (audio file + configured ASR model + declared language)
to ``{base_url}/audio/transcriptions`` (the real-ASR leg, tickets #387/#392).
``draft_rx`` raises the typed non-retryable error with "not supported in this
phase" per ticket #379 scope.

A transcribe outage (network/timeout/429/5xx after retries) is typed
``retries_exhausted=True`` so the fallback chain engages the secondary
provider; a contract rejection (4xx, malformed payload, schema validation
failure, or a request with no clip bytes) is typed ``retries_exhausted=False``
and propagates immediately without tripping the breaker. The degrade-to-raw-
doctor-review path (ticket #386) is the safety net beneath this leg.

Egress carries only the decrypted audio clip plus the ``AiEgressContext``
(declared language) and the pseudonymous ``audio_ref``-derived filename - never
name, phone, or the full record (NFR-SEC-006). Timeout and retry discipline are
reused from the existing ``Ext002AiProvider`` plumbing
(third-party-integration-standards S1): exponential + jitter backoff,
injectable ``sleep``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import posixpath
from collections.abc import Awaitable, Callable
from typing import Literal

import httpx
from langfuse import observe

from app.config import (
    DEFAULT_AI_ASR_MODEL,
    DEFAULT_AI_MAX_RETRIES,
    DEFAULT_AI_TIMEOUT_SECONDS,
)
from modules.intake.adapters.ai_gateway import (
    AiEgressContext,
    AiGateway,
    DraftRxRequest,
    DraftRxResult,
    Ext002CallError,
    StructureRequest,
    StructureResult,
    TranscribeRequest,
    TranscribeResult,
    _backoff_delay,
)

logger = logging.getLogger(__name__)

_SYSTEM_ROLE = (
    "You are a clinical structurer. Given a patient transcript, extract the "
    "chief complaints, symptoms, and duration. Return JSON with keys: "
    "chief_complaints (list[str]), symptoms (list[str]), duration (str), "
    "confidence (float 0.0-1.0)."
)

#: Transcription confidence proxy when the ASR endpoint reports no per-segment
#: confidence (ticket #387). Matches the mock adapter's clean-confidence
#: convention (MOCK_CONFIDENCE_CLEAN) - a successfully produced transcript is
#: treated as a clean transcription; the AMB-006 low-confidence gate operates on
#: the structure leg, not here.
_CONFIDENCE_PROXY_DEFAULT = 0.8


def _clip_filename(audio_ref: str) -> str:
    """A filename for the multipart ``file`` field (pseudonymous, keep the ext).

    Derives the basename from the pseudonymous media reference so the provider
    receives a real audio filename (extension included); falls back to a plain
    ``audio.mp3`` when the reference has none. Never carries an identity field.
    """
    basename = posixpath.basename(audio_ref)
    if basename and "." in basename:
        return basename
    return "audio.mp3"


_AUDIO_MIME_BY_SUFFIX = {
    ".flac": "audio/flac",
    ".m4a": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".mp4": "audio/mp4",
    ".ogg": "audio/ogg",
    ".wav": "audio/wav",
    ".webm": "audio/webm",
}


def _clip_mime_type(filename: str) -> str:
    """The audio content type for the multipart ``file`` field.

    Matches the clip's extension so the provider never sees a format mismatch
    (a ``.wav`` clip labelled ``audio/mpeg``); unknown/absent extensions default
    to ``audio/mpeg``.
    """
    suffix = posixpath.splitext(filename)[1].lower()
    return _AUDIO_MIME_BY_SUFFIX.get(suffix, "audio/mpeg")


class OpenAiCompatibleAdapter:
    """Adapter for any OpenAI-compatible chat /audio transcription endpoint.

    ``structure`` posts to ``{base_url}/chat/completions`` with Bearer auth and
    JSON-mode response format. ``transcribe`` posts the clip bytes as
    ``multipart/form-data`` to ``{base_url}/audio/transcriptions`` and parses
    the result into a ``TranscribeResult`` (tickets #387/#392); a request with
    no clip bytes fails closed as a contract rejection. ``draft_rx`` raises
    ``Ext002CallError(retries_exhausted=False)`` with "not supported in this
    phase" - that leg is not yet implemented.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        asr_model: str = DEFAULT_AI_ASR_MODEL,
        timeout_seconds: float = DEFAULT_AI_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_AI_MAX_RETRIES,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._asr_model = asr_model
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._sleep = sleep
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)

    @property
    def effective_provider(self) -> str:
        """The ``ai_provider`` whitelist value this adapter serves."""
        return "openai_compatible"

    @property
    def effective_model(self) -> str:
        """The configured model name sent in the chat-completions body."""
        return self._model

    def _build_messages(
        self,
        transcript: str,
        context: AiEgressContext,
    ) -> list[dict[str, str]]:
        user_content = f"Transcript: {transcript}\nLanguage: {context.language}"
        return [
            {"role": "system", "content": _SYSTEM_ROLE},
            {"role": "user", "content": user_content},
        ]

    async def _post(
        self,
        path: str,
        *,
        json: dict[str, object] | None = None,
        data: dict[str, str] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
    ) -> dict[str, object]:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        last_status = 0
        for attempt in range(self._max_retries + 1):
            if attempt > 0:
                await self._sleep(_backoff_delay(attempt))
            try:
                response = await self._client.post(
                    f"{self._base_url}{path}",
                    json=json,
                    data=data,
                    files=files,
                    headers=headers,
                )
            except httpx.HTTPError as exc:
                if attempt == self._max_retries:
                    logger.error(
                        "OpenAI-compatible %s failed after %d attempts (network error)",
                        path,
                        self._max_retries + 1,
                    )
                    raise Ext002CallError(
                        f"OpenAI-compatible {path} failed after "
                        f"{self._max_retries + 1} attempts (network error)",
                        retries_exhausted=True,
                    ) from exc
                continue
            if response.status_code == 429 or response.status_code >= 500:
                last_status = response.status_code
                continue
            if response.is_success:
                try:
                    body = response.json()
                except ValueError as exc:
                    logger.error("OpenAI-compatible %s returned a non-JSON response", path)
                    raise Ext002CallError(
                        f"OpenAI-compatible {path} returned a non-JSON response",
                        retries_exhausted=False,
                    ) from exc
                if not isinstance(body, dict):
                    logger.error("OpenAI-compatible %s returned an unexpected payload", path)
                    raise Ext002CallError(
                        f"OpenAI-compatible {path} returned an unexpected payload",
                        retries_exhausted=False,
                    )
                return body
            logger.warning(
                "OpenAI-compatible %s rejected with HTTP %d",
                path,
                response.status_code,
            )
            raise Ext002CallError(
                f"OpenAI-compatible {path} rejected with HTTP {response.status_code}",
                retries_exhausted=False,
            )
        logger.error(
            "OpenAI-compatible %s failed after %d attempts (last HTTP %d)",
            path,
            self._max_retries + 1,
            last_status,
        )
        raise Ext002CallError(
            f"OpenAI-compatible {path} failed after {self._max_retries + 1} "
            f"attempts (last HTTP {last_status})",
            retries_exhausted=True,
        )

    async def _post_chat(
        self,
        messages: list[dict[str, str]],
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": self._model,
            "messages": messages,
            "response_format": {"type": "json_object"},
        }
        return await self._post("/chat/completions", json=payload)

    def _parse_structure_response(
        self,
        data: dict[str, object],
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> StructureResult:
        choices = data.get("choices")
        if not isinstance(choices, list) or len(choices) == 0:
            raise Ext002CallError(
                "OpenAI-compatible /chat/completions returned no choices",
                retries_exhausted=False,
            )
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise Ext002CallError(
                "OpenAI-compatible /chat/completions returned unexpected choice format",
                retries_exhausted=False,
            )
        message = first_choice.get("message")
        if not isinstance(message, dict):
            raise Ext002CallError(
                "OpenAI-compatible /chat/completions returned no message in choice",
                retries_exhausted=False,
            )
        content = message.get("content")
        if not isinstance(content, str):
            raise Ext002CallError(
                "OpenAI-compatible /chat/completions returned non-string content",
                retries_exhausted=False,
            )
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise Ext002CallError(
                "OpenAI-compatible /chat/completions returned malformed JSON in content",
                retries_exhausted=False,
            ) from exc
        try:
            result = StructureResult.model_validate(parsed)
        except Exception as exc:
            raise Ext002CallError(
                "OpenAI-compatible /chat/completions content failed StructureResult validation",
                retries_exhausted=False,
            ) from exc
        return StructureResult(
            chief_complaints=result.chief_complaints,
            symptoms=result.symptoms,
            duration=result.duration,
            confidence=result.confidence,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    def _extract_usage_tokens(
        self,
        data: dict[str, object],
    ) -> tuple[int, int]:
        usage = data.get("usage")
        if not isinstance(usage, dict):
            return 0, 0
        return self._parse_usage(usage)

    def _parse_usage(self, usage: dict[str, object]) -> tuple[int, int]:
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        return (
            int(prompt_tokens) if isinstance(prompt_tokens, (int, float)) else 0,
            int(completion_tokens) if isinstance(completion_tokens, (int, float)) else 0,
        )

    def _extract_transcription_usage_tokens(
        self,
        data: dict[str, object],
    ) -> tuple[int, int]:
        usage = data.get("usage")
        if isinstance(usage, dict):
            return self._parse_usage(usage)
        vendor = data.get("x_groq")
        if isinstance(vendor, dict):
            usage = vendor.get("usage")
            if isinstance(usage, dict):
                return self._parse_usage(usage)
        return 0, 0

    def _transcription_confidence_proxy(self, data: dict[str, object]) -> float:
        segments = data.get("segments")
        if isinstance(segments, list) and segments:
            scores: list[float] = []
            for segment in segments:
                if not isinstance(segment, dict):
                    continue
                confidence = segment.get("confidence")
                if isinstance(confidence, (int, float)):
                    scores.append(float(confidence))
            if scores:
                return sum(scores) / len(scores)
        return _CONFIDENCE_PROXY_DEFAULT

    def _parse_transcribe_response(
        self,
        data: dict[str, object],
        context_language: Literal["hi", "en"],
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> TranscribeResult:
        text = data.get("text")
        if not isinstance(text, str) or not text.strip():
            raise Ext002CallError(
                "OpenAI-compatible /audio/transcriptions returned no transcript text",
                retries_exhausted=False,
            )
        language = data.get("language")
        if not isinstance(language, str):
            language = context_language
        try:
            return TranscribeResult(
                transcript=text.strip(),
                confidence=self._transcription_confidence_proxy(data),
                language=language,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        except Exception as exc:
            raise Ext002CallError(
                "OpenAI-compatible /audio/transcriptions content failed "
                "TranscribeResult validation",
                retries_exhausted=False,
            ) from exc

    @observe
    async def transcribe(self, request: TranscribeRequest) -> TranscribeResult:
        if request.audio_bytes is None:
            logger.error("OpenAI-compatible transcribe called without the audio clip bytes")
            raise Ext002CallError(
                "OpenAI-compatible transcribe requires the audio clip bytes "
                "(audio_bytes); no bytes supplied",
                retries_exhausted=False,
            )
        filename = _clip_filename(request.audio_ref)
        data = await self._post(
            "/audio/transcriptions",
            data={
                "model": self._asr_model,
                "language": request.context.language,
            },
            files={"file": (filename, request.audio_bytes, _clip_mime_type(filename))},
        )
        prompt_tokens, completion_tokens = self._extract_transcription_usage_tokens(data)
        if prompt_tokens or completion_tokens:
            logger.info(
                "OpenAI-compatible transcribe tokens: prompt=%d completion=%d",
                prompt_tokens,
                completion_tokens,
            )
        return self._parse_transcribe_response(
            data,
            request.context.language,
            input_tokens=prompt_tokens,
            output_tokens=completion_tokens,
        )

    @observe
    async def structure(self, request: StructureRequest) -> StructureResult:
        messages = self._build_messages(request.transcript, request.context)
        data = await self._post_chat(messages)
        prompt_tokens, completion_tokens = self._extract_usage_tokens(data)
        if prompt_tokens or completion_tokens:
            logger.info(
                "OpenAI-compatible structure tokens: prompt=%d completion=%d",
                prompt_tokens,
                completion_tokens,
            )
        return self._parse_structure_response(
            data,
            input_tokens=prompt_tokens,
            output_tokens=completion_tokens,
        )

    @observe
    async def draft_rx(self, request: DraftRxRequest) -> DraftRxResult:
        raise Ext002CallError(
            "draft_rx not supported in this phase",
            retries_exhausted=False,
        )


def build_openai_compatible_gateway(
    *,
    api_key: str,
    base_url: str,
    model: str,
    asr_model: str = DEFAULT_AI_ASR_MODEL,
    timeout_seconds: float = DEFAULT_AI_TIMEOUT_SECONDS,
    max_retries: int = DEFAULT_AI_MAX_RETRIES,
    client: httpx.AsyncClient | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> AiGateway:
    """Resolve an OpenAI-compatible adapter typed as the ``AiGateway`` port."""
    return OpenAiCompatibleAdapter(
        api_key=api_key,
        base_url=base_url,
        model=model,
        asr_model=asr_model,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        client=client,
        sleep=sleep,
    )


__all__ = [
    "OpenAiCompatibleAdapter",
    "build_openai_compatible_gateway",
]
