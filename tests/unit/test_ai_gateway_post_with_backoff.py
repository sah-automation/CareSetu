"""Shared post-with-backoff helper unit tests (T08 #405).

The retry/backoff/call-error loop is written once in ``ai_gateway.py`` and
shared by every real provider adapter. These tests pin the discipline directly
on the shared helper, independent of any adapter: JSON and multipart call
shapes both reach the wire, exactly-``max_retries`` retries happen on outage
(network/timeout/429/5xx), contract rejections (4xx, non-JSON, unexpected
payload) never retry and never trip the breaker
(``Ext002CallError(retries_exhausted=False)``), and the exhaustion error after
the retry budget is typed ``retries_exhausted=True``.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from modules.intake.adapters.ai_gateway import Ext002CallError, post_with_backoff

_URL = "https://ext.example/chat/completions"


def _client(handler: object) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0)


async def _noop_sleep(_: float) -> None:
    pass


def _success(payload: dict[str, Any]) -> httpx.Response:
    return httpx.Response(
        status_code=200,
        json=payload,
        request=httpx.Request("POST", _URL),
    )


def _error(status_code: int, body: str = '{"error": "bad"}') -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        content=body.encode(),
        request=httpx.Request("POST", _URL),
    )


def _parse_multipart(request: httpx.Request) -> dict[str, bytes]:
    content_type = request.headers.get("content-type", "")
    assert content_type.startswith("multipart/form-data"), content_type
    boundary = content_type.split("boundary=", 1)[1].strip().strip('"').encode()
    parts: dict[str, bytes] = {}
    for chunk in request.content.split(b"--" + boundary):
        if not chunk or chunk == b"--":
            continue
        if b"\r\n\r\n" not in chunk:
            continue
        head, value = chunk.split(b"\r\n\r\n", 1)
        name: str | None = None
        for line in head.split(b"\r\n"):
            if not line.lower().startswith(b"content-disposition"):
                continue
            for param in line.decode(errors="ignore").split(";"):
                param = param.strip()
                if param.startswith("name="):
                    name = param.split("=", 1)[1].strip('"')
        if name is not None:
            parts[name] = value.removesuffix(b"\r\n")
    return parts


# --- JSON and multipart call shapes ---


async def test_post_json_shape_returns_parsed_body() -> None:
    captured: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _success({"ok": True})

    body = await post_with_backoff(
        _client(_handler),
        _URL,
        headers={"Authorization": "Bearer k"},
        json_body={"model": "m", "messages": []},
        max_retries=3,
        sleep=_noop_sleep,
    )

    assert body == {"ok": True}
    assert len(captured) == 1
    assert captured[0].headers.get("authorization") == "Bearer k"
    assert captured[0].read() is not None


async def test_post_multipart_shape_posts_fields_and_file() -> None:
    captured: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _success({"text": "mujhe bukhar hai"})

    body = await post_with_backoff(
        _client(_handler),
        "https://ext.example/audio/transcriptions",
        headers={"Authorization": "Bearer k"},
        data={"model": "asr", "language": "hi"},
        files={"file": ("clip.mp3", b"audio-bytes", "audio/mpeg")},
        max_retries=3,
        sleep=_noop_sleep,
    )

    assert body == {"text": "mujhe bukhar hai"}
    assert captured[0].url.path == "/audio/transcriptions"
    assert captured[0].headers.get("authorization") == "Bearer k"
    parts = _parse_multipart(captured[0])
    assert parts["model"] == b"asr"
    assert parts["language"] == b"hi"
    assert parts["file"] == b"audio-bytes"
    assert b"Content-Type: audio/mpeg" in captured[0].content


# --- Outage = retryable, exactly max_retries retries ---


async def test_429_retries_then_outage() -> None:
    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return _error(429)

    with pytest.raises(Ext002CallError) as exc_info:
        await post_with_backoff(
            _client(_handler),
            _URL,
            headers={},
            max_retries=2,
            sleep=_noop_sleep,
        )

    assert exc_info.value.retries_exhausted is True
    assert "failed after" in str(exc_info.value)
    assert call_count == 3  # initial + 2 retries


async def test_500_retries_then_outage() -> None:
    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return _error(500)

    with pytest.raises(Ext002CallError) as exc_info:
        await post_with_backoff(
            _client(_handler),
            _URL,
            headers={},
            max_retries=2,
            sleep=_noop_sleep,
        )

    assert exc_info.value.retries_exhausted is True
    assert call_count == 3


async def test_429_then_success_recovers() -> None:
    call_count = 0
    sleeps: list[float] = []

    async def _record_sleep(delay: float) -> None:
        sleeps.append(delay)

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _error(429)
        return _success({"ok": True})

    body = await post_with_backoff(
        _client(_handler),
        _URL,
        headers={},
        max_retries=2,
        sleep=_record_sleep,
    )

    assert body == {"ok": True}
    assert call_count == 2
    assert len(sleeps) == 1  # one backoff before the retry


# --- Network / timeout = retryable outage ---


async def test_network_error_retries_then_outage() -> None:
    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        raise httpx.ConnectError("connection refused")

    with pytest.raises(Ext002CallError) as exc_info:
        await post_with_backoff(
            _client(_handler),
            _URL,
            headers={},
            max_retries=2,
            sleep=_noop_sleep,
        )

    assert exc_info.value.retries_exhausted is True
    assert "network error" in str(exc_info.value)
    assert call_count == 3


async def test_timeout_exception_is_outage() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out")

    with pytest.raises(Ext002CallError) as exc_info:
        await post_with_backoff(
            _client(_handler),
            _URL,
            headers={},
            max_retries=2,
            sleep=_noop_sleep,
        )

    assert exc_info.value.retries_exhausted is True


# --- Contract rejection = non-retryable, never trips the breaker ---


async def test_400_non_retryable_no_retries() -> None:
    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return _error(400, '{"error": "bad request"}')

    with pytest.raises(Ext002CallError) as exc_info:
        await post_with_backoff(
            _client(_handler),
            _URL,
            headers={},
            max_retries=2,
            sleep=_noop_sleep,
        )

    assert exc_info.value.retries_exhausted is False
    assert "HTTP 400" in str(exc_info.value)
    assert call_count == 1


async def test_non_json_response_non_retryable() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            content=b"not json at all",
            request=httpx.Request("POST", _URL),
        )

    with pytest.raises(Ext002CallError) as exc_info:
        await post_with_backoff(
            _client(_handler),
            _URL,
            headers={},
            max_retries=2,
            sleep=_noop_sleep,
        )

    assert exc_info.value.retries_exhausted is False


async def test_unexpected_payload_shape_non_retryable() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json=[1, 2, 3],  # type: ignore[arg-type]
            request=httpx.Request("POST", _URL),
        )

    with pytest.raises(Ext002CallError) as exc_info:
        await post_with_backoff(
            _client(_handler),
            _URL,
            headers={},
            max_retries=2,
            sleep=_noop_sleep,
        )

    assert exc_info.value.retries_exhausted is False


# --- Label surfaced in messages ---


async def test_label_appears_in_outage_message() -> None:
    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return _error(503)

    with pytest.raises(Ext002CallError) as exc_info:
        await post_with_backoff(
            _client(_handler),
            _URL,
            headers={},
            max_retries=0,
            sleep=_noop_sleep,
            label="MyProvider",
        )

    assert exc_info.value.retries_exhausted is True
    assert "MyProvider" in str(exc_info.value)
    assert call_count == 1
