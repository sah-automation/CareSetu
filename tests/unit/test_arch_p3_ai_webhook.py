"""Unit tests for ARCH-P3 #853: optional AI job completion webhook."""

from __future__ import annotations

import asyncio
import hashlib
import hmac

import httpx
import pytest

from bus.events import EVENT_AI_JOB_COMPLETED, EVENT_AI_JOB_FAILED
from bus.registry import HandlerRegistry
from modules.intake.adapters import register_handlers
from modules.intake.adapters.ai_gateway import Ext002CallError
from modules.intake.adapters.ai_job_webhook import (
    ALLOWED_PAYLOAD_FIELDS,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    AiJobWebhookAdapter,
    build_ai_job_webhook_payload,
)
from modules.intake.domain.events import ai_job_completed_envelope, ai_job_failed_envelope


def _completed_envelope():
    return ai_job_completed_envelope(
        ai_job_id=9,
        intake_id=42,
        task_type="draft",
        provider="openai",
        model="gpt-4o-mini",
        input_tokens=800,
        output_tokens=120,
        cost_paise=21,
        duration_ms=950,
        low_confidence=True,
        patient_id=7,
        doctor_id=8,
        trace_id="c" * 32,
    )


def _failed_envelope():
    return ai_job_failed_envelope(
        ai_job_id=9,
        intake_id=42,
        task_type="summarize",
        reason="Ext002CallError",
        provider="openai",
        model="gpt-4o-mini",
        timeout=True,
        patient_id=7,
        doctor_id=None,
        trace_id="d" * 32,
    )


def test_payload_carries_only_the_allowed_phi_free_fields() -> None:
    payload = build_ai_job_webhook_payload(_completed_envelope())

    assert set(payload) == ALLOWED_PAYLOAD_FIELDS
    assert "patient_id" not in payload
    assert "doctor_id" not in payload
    assert payload["status"] == "completed"
    assert payload["ai_job_id"] == 9
    assert payload["intake_id"] == 42


def test_failed_payload_omits_the_free_text_reason() -> None:
    payload = build_ai_job_webhook_payload(_failed_envelope())

    assert set(payload) == ALLOWED_PAYLOAD_FIELDS
    assert "reason" not in payload
    assert payload["status"] == "failed"


def test_delivery_signs_the_raw_body_and_sends_a_timestamp() -> None:
    captured: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured
        captured = request
        return httpx.Response(200, json={"ok": True})

    adapter = AiJobWebhookAdapter(
        url="https://partner.example/hook",
        secret="s3cret",
        transport=httpx.MockTransport(handler),
        timestamp_factory=lambda: 1_700_000_000,
        max_attempts=1,
    )

    asyncio.run(adapter.deliver(_completed_envelope()))

    assert captured is not None
    expected = hmac.new(b"s3cret", captured.content, hashlib.sha256).hexdigest()
    assert captured.headers[SIGNATURE_HEADER] == expected
    assert captured.headers[TIMESTAMP_HEADER] == "1700000000"


def test_retries_an_outage_using_the_shared_backoff_policy() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json={"ok": True})

    adapter = AiJobWebhookAdapter(
        url="https://partner.example/hook",
        secret="s3cret",
        transport=httpx.MockTransport(handler),
        max_attempts=2,
        sleep=_no_sleep,
    )

    asyncio.run(adapter.deliver(_completed_envelope()))

    assert attempts == 2


def test_failure_never_leaks_the_signing_secret() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad request")

    adapter = AiJobWebhookAdapter(
        url="https://partner.example/hook",
        secret="super-secret-value",
        transport=httpx.MockTransport(handler),
        max_attempts=1,
        sleep=_no_sleep,
    )

    with pytest.raises(Ext002CallError) as raised:
        asyncio.run(adapter.deliver(_completed_envelope()))

    assert "super-secret-value" not in str(raised.value)


def test_handler_is_not_registered_without_a_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "AI_WEBHOOK_URL",
        "AI_JOB_WEBHOOK_URL",
        "AI_WEBHOOK_SECRET",
        "AI_WEBHOOK_SIGNING_SECRET",
        "AI_JOB_WEBHOOK_SECRET",
        "AI_JOB_WEBHOOK_SIGNING_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)

    registry = HandlerRegistry()
    register_handlers(registry)

    assert len(registry.handlers_for(EVENT_AI_JOB_COMPLETED)) == 0
    assert len(registry.handlers_for(EVENT_AI_JOB_FAILED)) == 0


def test_handler_is_registered_when_a_url_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_WEBHOOK_URL", "https://partner.example/hook")
    monkeypatch.setenv("AI_WEBHOOK_SECRET", "s3cret")

    registry = HandlerRegistry()
    register_handlers(registry)

    assert len(registry.handlers_for(EVENT_AI_JOB_COMPLETED)) == 1
    assert len(registry.handlers_for(EVENT_AI_JOB_FAILED)) == 1


async def _no_sleep(_seconds: float) -> None:
    return None
