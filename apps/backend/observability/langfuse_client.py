"""Langfuse client singleton for AI observability (plan-phase7-tracing-prep).

Exposes :func:`get_langfuse_client` which returns a configured ``Langfuse``
instance or ``None`` when the SDK keys are absent from the environment. Lazily
initialised once per process; never blocks boot when unconfigured, so the app
runs cleanly in dev/CI without a Langfuse account.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langfuse import Langfuse

log = logging.getLogger(__name__)

_client: Langfuse | None = None
_initialised: bool = False


def get_langfuse_client(public_key: str, secret_key: str, host: str) -> Langfuse | None:
    """Return the process-wide Langfuse singleton, creating it on first call.

    A blank ``public_key`` (both keys unset in the environment) returns
    ``None`` immediately and disables tracing for the process; the SDK is not
    even imported in that case. Callers must treat ``None`` as the no-op
    client that ``@observe`` already is under the hood.
    """
    global _client, _initialised

    if _initialised:
        return _client

    _initialised = True

    if not public_key:
        log.info("langfuse keys absent; AI tracing disabled")
        return None

    from langfuse import Langfuse  # deferred: only imported when configured

    _client = Langfuse(public_key=public_key, secret_key=secret_key, host=host)
    log.info("langfuse client initialised (host=%s)", host)
    return _client
