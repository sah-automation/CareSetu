"""MOD-013: consumer-side payload mirrors for telemetry accumulation (B4 #702).

The ``observability`` module consumes the ``ai_job.completed`` /
``ai_job.failed`` events MOD-005 publishes. The consumer OWNS these mirror
models (cf. MOD-011's mirrors in ``modules/audit/domain/consumer.py``):
MOD-005 registers the canonical payload models on the registry, so MOD-013
never registers a duplicate - ``run_handler`` re-validates the dispatched
intake payload into the local mirror before the aggregate effect runs. The
mirrors carry only operational METERING facts - no PHI (the transcript,
clinical fields and raw confidence score never travel, security-phii-
standards): provider/model, token use, priced cost, duration and the derived
``low_confidence`` flag on completion; the failure reason, serving
provider/model and the derived ``timeout`` classification on failure.
"""

from __future__ import annotations

from pydantic import BaseModel


class AiJobCompletedUsagePayload(BaseModel):
    """Observability's mirror of the ``ai_job.completed`` payload.

    ``low_confidence`` is the producer's derived flag (always ``False`` for
    transcribe) - never the raw confidence score, which stays in the intake
    schema. MOD-013 accumulates it directly and never recomputes it.
    """

    ai_job_id: int
    intake_id: int
    task_type: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_paise: int
    duration_ms: int
    low_confidence: bool


class AiJobFailedUsagePayload(BaseModel):
    """Observability's mirror of the ``ai_job.failed`` payload.

    ``timeout`` is classified upstream (the producer walks its exception's
    cause chain for ``httpx.TimeoutException``); MOD-013 buckets timeouts
    separately from other failures using only this flag.
    """

    ai_job_id: int
    intake_id: int
    task_type: str
    provider: str
    model: str
    reason: str
    timeout: bool
