"""MOD-005: OpenAI-compatible adapter for any standard chat-completions endpoint.

This adapter implements the ``AiGateway`` port against any REST endpoint that
conforms to the OpenAI chat-completions API (POST /chat/completions). It covers
the structure leg only - ``transcribe`` and ``draft_rx`` raise the typed
non-retryable error with "not supported in this phase" per ticket #379 scope.

Egress carries only the ``AiEgressContext`` plus the transcript - never name,
phone, or the full record (NFR-SEC-006). Timeout and retry discipline are
reused from the existing ``Ext002AiProvider`` plumbing (third-party-integration-
standards S1): exponential + jitter backoff, injectable ``sleep``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

import httpx
from langfuse import observe

from app.config import DEFAULT_AI_MAX_RETRIES, DEFAULT_AI_TIMEOUT_SECONDS
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


class OpenAiCompatibleAdapter:
    """Adapter for any OpenAI-compatible chat-completions endpoint (structure leg).

    ``transcribe`` and ``draft_rx`` raise ``Ext002CallError(retries_exhausted=False)``
    with "not supported in this phase" - those legs are not yet implemented.
    ``structure`` posts to ``{base_url}/chat/completions`` with Bearer auth and
    JSON-mode response format.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float = DEFAULT_AI_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_AI_MAX_RETRIES,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
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
        user_content = (
            f"Transcript: {transcript}\n"
            f"Language: {context.language}\n"
            f"Age range: {context.age_range}\n"
            f"Sex: {context.sex}"
        )
        return [
            {"role": "system", "content": _SYSTEM_ROLE},
            {"role": "user", "content": user_content},
        ]

    async def _post_chat(
        self,
        messages: list[dict[str, str]],
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": self._model,
            "messages": messages,
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        last_status = 0
        for attempt in range(self._max_retries + 1):
            if attempt > 0:
                await self._sleep(_backoff_delay(attempt))
            try:
                response = await self._client.post(
                    f"{self._base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                )
            except httpx.HTTPError as exc:
                if attempt == self._max_retries:
                    logger.error(
                        "OpenAI-compatible /chat/completions failed after %d attempts "
                        "(network error)",
                        self._max_retries + 1,
                    )
                    raise Ext002CallError(
                        f"OpenAI-compatible /chat/completions failed after "
                        f"{self._max_retries + 1} attempts (network error)",
                        retries_exhausted=True,
                    ) from exc
                continue
            if response.status_code == 429 or response.status_code >= 500:
                last_status = response.status_code
                continue
            if response.is_success:
                try:
                    data = response.json()
                except ValueError as exc:
                    logger.error("OpenAI-compatible /chat/completions returned a non-JSON response")
                    raise Ext002CallError(
                        "OpenAI-compatible /chat/completions returned a non-JSON response",
                        retries_exhausted=False,
                    ) from exc
                if not isinstance(data, dict):
                    logger.error(
                        "OpenAI-compatible /chat/completions returned an unexpected payload"
                    )
                    raise Ext002CallError(
                        "OpenAI-compatible /chat/completions returned an unexpected payload",
                        retries_exhausted=False,
                    )
                return data
            logger.warning(
                "OpenAI-compatible /chat/completions rejected with HTTP %d",
                response.status_code,
            )
            raise Ext002CallError(
                f"OpenAI-compatible /chat/completions rejected with HTTP {response.status_code}",
                retries_exhausted=False,
            )
        logger.error(
            "OpenAI-compatible /chat/completions failed after %d attempts (last HTTP %d)",
            self._max_retries + 1,
            last_status,
        )
        raise Ext002CallError(
            f"OpenAI-compatible /chat/completions failed after {self._max_retries + 1} "
            f"attempts (last HTTP {last_status})",
            retries_exhausted=True,
        )

    def _parse_structure_response(
        self,
        data: dict[str, object],
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
        return result

    def _extract_usage_tokens(
        self,
        data: dict[str, object],
    ) -> tuple[int, int]:
        usage = data.get("usage")
        if not isinstance(usage, dict):
            return 0, 0
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        return (
            int(prompt_tokens) if isinstance(prompt_tokens, (int, float)) else 0,
            int(completion_tokens) if isinstance(completion_tokens, (int, float)) else 0,
        )

    @observe
    async def transcribe(self, request: TranscribeRequest) -> TranscribeResult:
        raise Ext002CallError(
            "transcribe not supported in this phase",
            retries_exhausted=False,
        )

    @observe
    async def structure(self, request: StructureRequest) -> StructureResult:
        messages = self._build_messages(request.transcript, request.context)
        data = await self._post_chat(messages)
        result = self._parse_structure_response(data)
        prompt_tokens, completion_tokens = self._extract_usage_tokens(data)
        if prompt_tokens or completion_tokens:
            logger.info(
                "OpenAI-compatible structure tokens: prompt=%d completion=%d",
                prompt_tokens,
                completion_tokens,
            )
        return result

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
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        client=client,
        sleep=sleep,
    )


__all__ = [
    "OpenAiCompatibleAdapter",
    "build_openai_compatible_gateway",
]
