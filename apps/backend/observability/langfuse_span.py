"""Langfuse AI-span metadata allow-list (PHASE-14A B2, #700).

The single seam every MOD-005 AI adapter uses to attach metadata to its
``@observe`` span. :data:`ALLOWED_SPAN_METADATA_KEYS` is the exact set the plan
documents (plan-phase14-observability §6): task type, provider, model,
input/output tokens, duration (ms), cost (paise), confidence, status, the
pseudonymous ``intake_id`` / ``ai_job_id``, trace id and prompt version.

:func:`build_span_metadata` is a **hard gate**: a key that is not on the list is
rejected with :class:`SpanMetadataError` rather than silently attached, so no
transcript text, patient identity or raw provider payload can ever reach a span
from an adapter. :func:`set_span_metadata` is the best-effort wrapper the
adapters call - it never raises into the AI call path and is a no-op when the
Langfuse client is unconfigured (keys absent), so ``@observe``'s behaviour is
unchanged when tracing is off.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from observability.langfuse_client import get_configured_client

log = logging.getLogger(__name__)

#: The documented AI-span metadata allow-list (plan-phase14-observability §6).
#: Deliberately excludes transcript text, patient identity (phone, name) and raw
#: provider payloads - a value under a key not listed here is never attached.
ALLOWED_SPAN_METADATA_KEYS: frozenset[str] = frozenset(
    {
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
)


class SpanMetadataError(ValueError):
    """Raised when a span-metadata field is not on the allow-list."""


def build_span_metadata(fields: Mapping[str, object]) -> dict[str, object]:
    """Return ``fields`` reduced to the allow-listed, non-``None`` entries.

    Raises :class:`SpanMetadataError` naming the offending keys when any key is
    not on :data:`ALLOWED_SPAN_METADATA_KEYS`. This is the PHI-free contract in
    one testable place: an adapter that tries to attach ``transcript`` or
    ``patient_name`` fails here instead of leaking it to Langfuse. ``None``
    values are dropped, so a caller can pass a field it only sometimes knows
    without attaching an empty key.
    """
    disallowed = sorted(key for key in fields if key not in ALLOWED_SPAN_METADATA_KEYS)
    if disallowed:
        raise SpanMetadataError(
            "AI span metadata keys not on the allow-list: " + ", ".join(disallowed)
        )
    return {key: value for key, value in fields.items() if value is not None}


def set_span_metadata(**fields: object) -> None:
    """Best-effort attach allow-listed metadata to the current Langfuse span.

    Never raises into the AI call path: a disallowed key is logged (key names
    only, never values) and dropped, and any Langfuse/SDK/network error is
    swallowed. A no-op when the client is unconfigured - keys absent leaves
    ``@observe``'s behaviour untouched and never imports the SDK.
    """
    client = get_configured_client()
    if client is None:
        return
    try:
        metadata = build_span_metadata(fields)
    except SpanMetadataError as exc:
        log.warning("dropped non-allow-listed AI span metadata: %s", exc)
        return
    if not metadata:
        return
    try:
        client.update_current_span(metadata=metadata)
    except Exception:
        log.debug("langfuse span metadata update failed", exc_info=True)


__all__ = [
    "ALLOWED_SPAN_METADATA_KEYS",
    "SpanMetadataError",
    "build_span_metadata",
    "set_span_metadata",
]
