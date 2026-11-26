"""Sentry exception tracking with PHI scrub (PHASE-14A A4, #696).

Error tracking is gated on ``SENTRY_DSN`` and mirrors the Langfuse/Redis no-op
discipline: when the DSN is empty the integration is inert (the SDK is never even
imported) and boot is unchanged, and an initialisation failure is logged as a
warning and swallowed so a vendor or transport problem can never take the API or
the worker down (plan-phase14 §A.2(c), §4 gate row).

Initialisation happens once per process, at both composition roots (the FastAPI
lifespan and the worker boot). Events carry:

- ``release`` - the git SHA from the A5 ``OTEL_SERVICE_VERSION`` gate, falling
  back to the app version when unset (single source: :data:`app.config.APP_VERSION`).
- ``trace_id`` - the request/outbox correlation id A1 binds in the logging
  context, attached as a tag so a Sentry error links back to its structured logs.

The error-tracking hooks (:func:`scrub_event`, wired as both ``before_send`` and
``before_send_transaction``) reuse A1's documented key denylist
(:func:`observability.logging.redact_value`) rather than re-inventing it, and
additionally drop the raw request body / query string - free text that can carry
PHI - before an event or a performance transaction leaves the process.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol, cast

from app.config import APP_VERSION
from observability.logging import REDACTED_VALUE, get_trace_id, redact_value

if TYPE_CHECKING:
    from sentry_sdk.types import Event, Hint

log = logging.getLogger(__name__)

# Once-per-process guard, mirroring the Langfuse singleton: a second call is a
# no-op so repeated ``create_app`` boots (tests, the in-process dispatcher) never
# re-initialise the SDK. ``_enabled`` records whether init actually succeeded so
# the shutdown flush only runs when there is a client to flush.
_initialised: bool = False
_enabled: bool = False

# Free-text request fields that are not denylisted by key but can still carry a
# phone / OTP / free text in their value (Sentry stores the raw body under
# ``data`` and the raw query under ``query_string``); replaced wholesale.
_REQUEST_FREE_TEXT_KEYS = ("data", "query_string")


class SentrySettings(Protocol):
    """The ``Settings`` slice Sentry reads, typed structurally for test fakes."""

    @property
    def sentry_dsn(self) -> str: ...

    @property
    def sentry_traces_sample_rate(self) -> float: ...

    @property
    def otel_service_version(self) -> str: ...


def resolve_release(settings: SentrySettings) -> str:
    """The Sentry ``release``: the git-SHA gate, else the app version.

    ``OTEL_SERVICE_VERSION`` is the single version source shared by A3 and A4
    (coding-standards §9.2): the deploy pipeline sets it to the git SHA, and when
    it is unset (local dev, tests) the human-maintained app version is used
    rather than an empty release.
    """
    return settings.otel_service_version.strip() or APP_VERSION


def _attach_trace_id(event: dict[str, Any]) -> None:
    """Tag the event with the context's ``trace_id`` when one is bound."""
    trace_id = get_trace_id()
    if trace_id is None:
        return
    tags = event.get("tags")
    if not isinstance(tags, dict):
        tags = {}
        event["tags"] = tags
    tags["trace_id"] = trace_id


def _scrub_request_free_text(event: dict[str, Any]) -> None:
    """Replace the raw request body / query string with the redaction marker."""
    request = event.get("request")
    if not isinstance(request, dict):
        return
    for key in _REQUEST_FREE_TEXT_KEYS:
        if key in request:
            request[key] = REDACTED_VALUE


def scrub_event(event: Event, hint: Hint) -> Event | None:
    """Sentry ``before_send``: strip PHI/secrets and tag the trace id.

    Walks the whole event payload with A1's key denylist so denied keys in
    ``extra``, ``contexts``, ``request``, ``breadcrumbs`` and ``tags`` alike are
    replaced with :data:`~observability.logging.REDACTED_VALUE`, then drops the
    raw request body/query and stamps the request ``trace_id`` as a tag. Returns
    the scrubbed event - never ``None``, so nothing is silently swallowed.
    """
    del hint
    scrubbed = redact_value(event)
    if not isinstance(scrubbed, dict):
        return event
    _scrub_request_free_text(scrubbed)
    _attach_trace_id(scrubbed)
    return cast("Event", scrubbed)


def init_sentry(settings: SentrySettings) -> bool:
    """Initialise the Sentry SDK once per process; never raises, never blocks boot.

    Returns ``True`` when a client was configured. An empty ``SENTRY_DSN``
    returns immediately and disables tracking for the process (like
    :func:`observability.langfuse_client.get_langfuse_client` with no key) - the
    SDK is not imported in that case. Any failure from ``sentry_sdk.init`` is
    logged as a warning and leaves the integration off rather than propagating.
    """
    global _initialised, _enabled

    if _initialised:
        return _enabled
    _initialised = True

    dsn = settings.sentry_dsn.strip()
    if not dsn:
        log.info("sentry dsn absent; error tracking disabled")
        return False

    try:
        import sentry_sdk  # deferred: only imported when configured

        sentry_sdk.init(
            dsn=dsn,
            release=resolve_release(settings),
            traces_sample_rate=settings.sentry_traces_sample_rate,
            before_send=scrub_event,
            # ``before_send`` covers error events only; performance transactions
            # (enabled by the sample rate) are scrubbed by the same hook so no
            # PHI reaches the trace stream either (plan-phase14 §10).
            before_send_transaction=scrub_event,
            send_default_pii=False,
        )
    except Exception:
        log.warning("sentry init failed; error tracking disabled", exc_info=True)
        _enabled = False
        return False

    _enabled = True
    log.info("sentry initialised (release=%s)", resolve_release(settings))
    return True


def flush_sentry(timeout: float = 2.0) -> None:
    """Flush queued events on shutdown; a no-op when Sentry is off.

    Called at both composition roots during shutdown (same discipline as the
    OTel/Langfuse flush, plan-phase14 §5) so a Render spin-down or restart does
    not drop buffered events. A flush failure is logged and swallowed.
    """
    if not _enabled:
        return
    try:
        import sentry_sdk

        sentry_sdk.flush(timeout=timeout)
    except Exception:
        log.warning("sentry flush failed", exc_info=True)
