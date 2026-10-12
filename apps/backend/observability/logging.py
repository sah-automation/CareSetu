"""Structured logging for the API, worker and dispatcher (PHASE-14A A1, #694).

One :func:`configure_logging` call configures the whole process - the FastAPI
app (``app/main.py``), the worker (``worker/main.py``) and the outbox dispatcher
(``bus/dispatcher.py``) all flow through it. ``LOG_FORMAT`` selects the renderer:
``json`` emits one JSON object per line (production / Render stdout), ``console``
emits a readable line (local dev). Every line carries the service identity and,
when a request or outbox event is in flight, a ``trace_id`` read from a
:class:`~contextvars.ContextVar` - so no ``Request`` is threaded through call
sites.

Configuration mirrors the Redis/Langfuse no-op discipline: a setup failure is
logged as a warning and swallowed, never raised at boot (plan-phase14 §A.2(c)).

PHI / secret redaction (error-handling-observability §2, NFR-SEC) is done by
key, before render, by :func:`redact_processor`. Any event-dict key whose
lower-cased name contains one of the fragments in
:data:`REDACTION_KEY_FRAGMENTS` has its value replaced with
:data:`REDACTED_VALUE`; nested mappings and sequences are walked too. The
fragment list is the single documented denylist - the Sentry ``before_send``
scrub (A4, #696) reuses the same rule rather than re-inventing it.

Denylist fragments (case-insensitive substring match on the key):

- identity: ``phone``, ``msisdn``, ``mobile``, ``contact``
- one-time codes: ``otp``, ``code``, ``pin``
- credentials: ``token``, ``secret``, ``password``, ``passwd``, ``credential``,
  ``api_key``, ``apikey``, ``authorization``, ``cookie``, ``session``
- free text / raw payloads: ``transcript``, ``free_text``, ``freetext``,
  ``freeform``, ``free_form``, ``raw``, ``payload``, ``body``

The redaction is deliberately over-broad (it may hide a benign ``status_code``
or ``country_code``): losing a non-PHI value from a log line is cheap, leaking a
phone number or OTP is not.
"""

from __future__ import annotations

import logging
import re
import sys
import uuid
from collections.abc import Mapping
from contextvars import ContextVar, Token
from typing import IO, Any, Protocol

import structlog
from structlog.typing import EventDict, Processor

# Rendering the standard field set needs the caller's module name
# (error-handling-observability §2). CallsiteParameterAdder inspects the call
# frame, so it reports the module of the logging call site - not structlog's.
_CALLSITE_ADDER = structlog.processors.CallsiteParameterAdder(
    parameters=[structlog.processors.CallsiteParameter.MODULE],
)


class LoggingSettings(Protocol):
    """The ``Settings`` slice logging needs, so this module imports no app layer."""

    @property
    def log_format(self) -> str: ...


REDACTED_VALUE = "[redacted]"

# Service identities carried on every line (error-handling-observability §2).
SERVICE_API = "caresetu-api"
SERVICE_WORKER = "caresetu-worker"

# The documented key denylist; see the module docstring. Substring match, so
# ``patient_phone`` / ``PHONE`` / ``otp_code`` are all caught.
REDACTION_KEY_FRAGMENTS: tuple[str, ...] = (
    "phone",
    "msisdn",
    "mobile",
    "contact",
    "otp",
    "code",
    "pin",
    "token",
    "secret",
    "password",
    "passwd",
    "credential",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "session",
    "transcript",
    "free_text",
    "freetext",
    "freeform",
    "free_form",
    "raw",
    "payload",
    "body",
)

# The one request/outbox-scoped correlation id (PHASE-14A A1): set by
# ``TraceMiddleware`` per request and around each dispatcher fan-out, read by
# ``add_trace_id`` so every line carries it without threading a Request.
_trace_id_var: ContextVar[str | None] = ContextVar("caresetu_trace_id", default=None)

# W3C trace-context (PHASE-14A A2, #695): the async seam carries a well-formed
# ``traceparent`` per row (``00-<32 hex trace-id>-<16 hex parent-id>-<01>``) so
# a worker's log/trace context links back to the originating API request. Only
# lowercase hex ids are honoured - a client-supplied id that is not a valid
# trace-id never enters the seam.
_TRACEPARENT_VERSION = "00"
_TRACEPARENT_FLAGS = "01"
_TRACE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_TRACEPARENT_PATTERN = re.compile(
    rf"^{_TRACEPARENT_VERSION}-[0-9a-f]{{32}}-[0-9a-f]{{16}}-{_TRACEPARENT_FLAGS}$"
)

# The handler this module owns, so re-configuring (app + worker in one process,
# or repeated ``create_app`` calls in tests) replaces it instead of stacking
# duplicate lines. Other handlers - notably pytest's log capture - are left
# untouched.
_installed_handler: logging.Handler | None = None


def set_trace_id(trace_id: str | None) -> Token[str | None]:
    """Bind ``trace_id`` for the current context; returns a reset token."""
    return _trace_id_var.set(trace_id)


def reset_trace_id(token: Token[str | None]) -> None:
    """Restore the trace id that was in effect before the matching ``set``."""
    _trace_id_var.reset(token)


def get_trace_id() -> str | None:
    """The trace id bound to the current context, or ``None`` outside one."""
    return _trace_id_var.get()


def is_valid_trace_id(trace_id: str) -> bool:
    """Whether ``trace_id`` is a valid W3C trace-id segment (32 lowercase hex).

    W3C trace-context forbids the all-zero trace-id; the OTel SDK consumes this
    seam's value downstream (PHASE-14A A3), so an all-zero id is rejected here
    rather than stored and later dropped.
    """
    return _TRACE_ID_PATTERN.match(trace_id) is not None and trace_id != "0" * 32


def build_traceparent(trace_id: str | None) -> str | None:
    """A W3C ``traceparent`` rooted at ``trace_id``, or ``None`` when malformed.

    The outbox writer stores the result per row so A3 (the OTel SDK) can consume
    it directly (plan-phase14-observability §5). A fresh random parent-id is
    minted per call because each outbox row's fan-out is its own span. A trace
    id that is not 32 lowercase hex - e.g. a client-supplied ``X-Request-Id`` of
    another shape - yields ``None`` so a malformed value never enters the seam
    and the row stays null.
    """
    if trace_id is None or not is_valid_trace_id(trace_id):
        return None
    parent_id = uuid.uuid4().hex[:16]
    return f"{_TRACEPARENT_VERSION}-{trace_id}-{parent_id}-{_TRACEPARENT_FLAGS}"


def trace_id_from_traceparent(traceparent: str | None) -> str | None:
    """The trace-id segment of a stored W3C ``traceparent``, or ``None``.

    The dispatcher binds the extracted id into the logging context before any
    handler runs so worker lines inherit the originating request's id. A row
    written with no request context has a null column and yields ``None``; a
    malformed stored value is ignored rather than echoed.
    """
    if traceparent is None or _TRACEPARENT_PATTERN.match(traceparent) is None:
        return None
    return traceparent.split("-", 3)[1]


def _is_denied(key: str) -> bool:
    """Whether ``key`` matches the documented denylist fragments."""
    lowered = key.lower()
    return any(fragment in lowered for fragment in REDACTION_KEY_FRAGMENTS)


def _redact(value: Any) -> Any:
    """Recursively replace denied-key values in mappings/sequences with a marker."""
    if isinstance(value, Mapping):
        return {
            key: (REDACTED_VALUE if _is_denied(str(key)) else _redact(item))
            for key, item in value.items()
        }
    if isinstance(value, list | tuple | set | frozenset):
        return [_redact(item) for item in value]
    return value


def redact_value(value: Any) -> Any:
    """Recursively redact denied-key values in an arbitrary structure.

    Public entry point for the same rule :func:`redact_processor` applies to a
    log event; the Sentry ``before_send`` scrub (A4, #696) walks its event
    payload with this so both surfaces share the one documented denylist.
    """
    return _redact(value)


def redact_processor(logger: Any, method_name: str, event_dict: EventDict) -> EventDict:
    """Strip PHI/secrets from top-level keys and nested structures before emit.

    A structlog processor: it mutates ``event_dict`` in place and returns it.
    Private keys (``_record``, ``_from_structlog``) are left alone - they carry
    log-record plumbing, not user data.
    """
    del logger, method_name
    for key in list(event_dict.keys()):
        if key.startswith("_"):
            continue
        if _is_denied(key):
            event_dict[key] = REDACTED_VALUE
        else:
            event_dict[key] = _redact(event_dict[key])
    return event_dict


def add_trace_id(logger: Any, method_name: str, event_dict: EventDict) -> EventDict:
    """Attach the context's ``trace_id`` to every line that has one."""
    del logger, method_name
    trace_id = _trace_id_var.get()
    if trace_id is not None:
        event_dict["trace_id"] = trace_id
    return event_dict


def _service_processor(service: str) -> Processor:
    """Build a processor that stamps the constant ``service`` identity."""

    def add_service(logger: Any, method_name: str, event_dict: EventDict) -> EventDict:
        del logger, method_name
        event_dict["service"] = service
        return event_dict

    return add_service


def _build_processors(service: str) -> list[Processor]:
    """The shared processor chain, run for both structlog and stdlib records."""
    return [
        _CALLSITE_ADDER,
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _service_processor(service),
        add_trace_id,
        redact_processor,
    ]


def configure_logging(
    settings: LoggingSettings,
    *,
    service: str = SERVICE_API,
    stream: IO[str] | None = None,
    force: bool = False,
) -> None:
    """Configure structlog once for this process; never raises.

    ``settings.log_format`` (``json`` / ``console``) picks the renderer. The
    shared processors stamp ``service``, ``module``, ``trace_id`` and the
    redaction pass on every record - structlog-native calls and the existing
    ``logging.getLogger(...)`` call sites alike (the latter via
    ``ProcessorFormatter``'s foreign pre-chain).

    Configuration is first-call-wins: a second call without ``stream``/``force``
    is a no-op, so the in-process dispatcher (which shares the API process, plan
    §3) never re-stamps API lines with the worker's service identity. That is the
    "configured once" the acceptance criterion asks for. ``stream`` (a test
    sink) or ``force=True`` installs again.

    Any failure is logged as a warning and swallowed: a logging misconfiguration
    must not take down the API or the worker (plan-phase14 §A.2(c)).
    """
    if _installed_handler is not None and stream is None and not force:
        return
    try:
        _install_logging(settings, service=service, stream=stream)
    except Exception:
        logging.getLogger(__name__).warning(
            "structured logging setup failed; continuing with stdlib defaults",
            exc_info=True,
        )


def _install_logging(settings: LoggingSettings, *, service: str, stream: IO[str] | None) -> None:
    global _installed_handler

    log_format = settings.log_format.strip().lower()
    renderer: Processor
    if log_format == "json":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=False)

    shared_processors = _build_processors(service)
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    root = logging.getLogger()
    if _installed_handler is not None:
        root.removeHandler(_installed_handler)
        _installed_handler = None

    handler = logging.StreamHandler(stream if stream is not None else sys.stdout)
    handler.setFormatter(formatter)
    root.addHandler(handler)
    _installed_handler = handler

    # Only raise verbosity to INFO; never clobber a more verbose pre-set level
    # (e.g. a test that asked for DEBUG).
    if root.level > logging.INFO or root.level == logging.NOTSET:
        root.setLevel(logging.INFO)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
