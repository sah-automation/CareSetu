"""The platform's ONE rule for what a trace id may look like.

A trace id crosses more boundaries than any other identifier in the platform:
the gateway echoes a client-supplied one into log lines and error envelopes, the
error feed stores it in ``observability_error_events.trace_id``, the product
ledger stores it in ``observability_product_events.trace_id`` AND
``session_key``, and the operator's deep links put it in a Grafana, Sentry or
Langfuse URL. Every one of those destinations is narrower than "any printable
string", so the rule lives here - in the shared package, beside the logging
seam that binds it - and both the gateway (which accepts the client's value) and
the deep-link builder (which echoes the stored one) read it from here.

**The rule is the platform's own, not a fresh invention.** Two facts fix it:
the ``trace_id`` / ``session_key`` columns are ``VARCHAR(64)``, and a value that
will be placed in a URL path segment must be printable, carry no whitespace,
and carry no separator a URL would have to escape. The shape that satisfies both
is the one the deep-link builder already used, so a stored id and a linked id
cannot drift: ``[A-Za-z0-9._-]+`` at most 64 characters.

Why the gateway has to enforce it (rather than only storing what it is given):
a client-supplied id longer than the column reaches the ledger unclamped, the
insert raises on length, and the product-event row for that step is never
written - a client can wedge their own request's telemetry by sending a long
``X-Request-Id``. An id carrying ``/`` or a quote reaches a deep link that the
link builder then refuses or, worse, one that points somewhere else. Both are
closed by the same single check, here.

A rejected id is MINTED, never dropped: the request still gets an id, the
client's correlation is lost, and nothing about the request changes.
"""

from __future__ import annotations

import re

#: The longest trace id the platform can store. Every column that holds one
#: (``observability_error_events.trace_id``,
#: ``observability_ai_job_spend.trace_id``,
#: ``observability_product_events.trace_id`` and ``session_key``) is
#: ``VARCHAR(64)``, so a value longer than this cannot be written at all.
MAX_TRACE_ID_LENGTH = 64

#: What an identifier may be: printable ASCII, no whitespace, and no separator
#: a URL would have to escape - so a trace id can never rewrite the query around
#: it, break out of a Sentry/Langfuse filter value, or walk a path segment
#: backwards. This is the SAME shape the deep-link builder accepts for a path
#: segment, which is why one constant serves both.
SAFE_TRACE_ID = re.compile(r"\A[A-Za-z0-9._-]+\Z")


def is_safe_trace_id(trace_id: str) -> bool:
    """Whether ``trace_id`` is an identifier this platform can store and link.

    A client-supplied value is untrusted input, so the answer is "no" unless
    the value matches the platform's identifier shape exactly: non-empty, at
    most :data:`MAX_TRACE_ID_LENGTH` characters, and nothing but the safe
    characters.
    """
    if not trace_id or len(trace_id) > MAX_TRACE_ID_LENGTH:
        return False
    return SAFE_TRACE_ID.match(trace_id) is not None


def normalize_trace_id(trace_id: str | None) -> str | None:
    """The trimmed id when it is one this platform can store, else ``None``.

    The trim is the only transformation: an id is echoed, never rebuilt, so a
    value that reaches a link is the value that was stored.
    """
    if trace_id is None:
        return None
    candidate = trace_id.strip()
    return candidate if is_safe_trace_id(candidate) else None


def clamp_trace_id(trace_id: str) -> str:
    """``trace_id`` cut to the width every trace column can hold.

    The DEFENCE-IN-DEPTH half of the rule. :func:`normalize_trace_id` is the
    gate at the edge, where an untrusted value arrives; this is the net under
    the ledger, for a value that reached a writer by some other path. A trace
    id's job is correlation, so a truncated one still correlates the rows of one
    step, while a rejected one is a lost write - and a lost write inside a
    transaction takes the whole transaction with it.
    """
    return trace_id[:MAX_TRACE_ID_LENGTH]
