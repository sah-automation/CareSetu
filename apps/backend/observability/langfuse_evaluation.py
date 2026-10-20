"""The vendor half of #751: record evaluation scores at observation level (#751).

Trace-level evaluation at Langfuse is deprecated with the November 2026 cloud
cutover, so every score this module posts carries its ``observationId``
beside the ``traceId``, and a score that cannot name its observation is
refused rather than quietly downgraded to the deprecated path. The
observations being scored are the golden run's own: this module creates them
under one deterministic per-day trace - metadata only, gated by the shared
allow-list, never input or output - so the vendor gets a chartable
evaluation history while no clinical content ever leaves Postgres (spec #717
decision 40).

Like ``observability.langfuse_metrics`` this is plain ``httpx`` with an
injectable transport: tests count the requests a run makes against a fake
API. At most two requests per nightly run - one ingestion batch creating the
day's golden observations, one scores request attaching every golden score to
its observation. The scores endpoint upserts on the score id, and
:func:`observability.domain.evaluation.vendor_score_id` derives that id from
the observation and the evaluator, so re-running a date replaces its rows
instead of stacking duplicates. An absent ``public_key`` returns ``None``
without sending anything: the unconfigured-vendor no-op the whole Langfuse
integration shares.

Production scores are deliberately NOT posted here. Their observations are
real vendor traces whose ids we do not mint, and naming them would mean
guessing ids or walking the deprecated trace-level path - so the production
``job_succeeded`` score stays in Postgres, where the #752 annotation queue
joins it to human judgement by ``trace_id``.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, time

import httpx

from modules.observability.domain.evaluation import (
    EvaluationScore,
    golden_observation_metadata,
    golden_trace_id,
    vendor_score_id,
)
from modules.observability.domain.evaluation import (
    observation_metadata as gate_metadata,
)
from modules.observability.domain.golden_dataset import (
    GOLDEN_DATASET_VERSION,
    GOLDEN_STRUCTURINGS,
    GOLDEN_TRANSCRIPTIONS,
)

log = logging.getLogger(__name__)

#: The ingestion endpoint (observation and trace creates) and the scores
#: endpoint (numeric/boolean scores, upsert-on-id), both relative to host.
INGESTION_PATH = "api/public/ingestion"
SCORES_PATH = "api/public/scores"

#: Deterministic event ids for the ingestion batch (uuid5): the same date and
#: example re-post the same event id, so the vendor deduplicates instead of
#: accumulating a second copy of the same observation create.
_EVENT_NAMESPACE = uuid.NAMESPACE_URL
_EVENT_ID_ROOT = "caresetu://observability/evaluation/"


def _event_id(kind: str, *parts: str) -> str:
    return str(uuid.uuid5(_EVENT_NAMESPACE, _EVENT_ID_ROOT + kind + ":" + "\x1f".join(parts)))


def _utc_stamp(target_date: date) -> str:
    """One fixed timestamp per run date, so re-runs build identical events."""
    return datetime.combine(target_date, time.min, tzinfo=UTC).isoformat().replace("+00:00", "Z")


def _golden_task_types() -> dict[str, str]:
    """example_id -> task_type for every golden example (synthetic labels)."""
    task_types = {example.example_id: "transcription" for example in GOLDEN_TRANSCRIPTIONS}
    task_types.update({example.example_id: "structuring" for example in GOLDEN_STRUCTURINGS})
    return task_types


def _require_observation_level(scores: Sequence[EvaluationScore]) -> None:
    """Refuse any score that cannot name its observation (AC: observation-level)."""
    unnamed = [score for score in scores if score.observation_id is None]
    if unnamed:
        raise ValueError(
            "every score posted to Langfuse needs an observation_id; "
            f"{len(unnamed)} of {len(scores)} lack one "
            f"(first: {unnamed[0].observation_kind}/{unnamed[0].observation_ref})"
        )
    untraced = [score for score in scores if score.trace_id is None]
    if untraced:
        raise ValueError(
            "every score posted to Langfuse needs its trace_id; "
            f"{len(untraced)} of {len(scores)} lack one"
        )


def build_ingestion_batch(
    target_date: date, scores: Sequence[EvaluationScore]
) -> dict[str, object]:
    """The ingestion batch that creates the golden run's trace and observations.

    One ``trace-create`` for the day's deterministic trace plus one
    ``observation-create`` per distinct scored example. Every metadata object
    in the batch is produced through the shared allow-list gate: the batch
    can carry a task type, provider and dataset version, and cannot carry a
    transcript, a field value or any identifier we did not mint.
    """
    _require_observation_level(scores)
    stamp = _utc_stamp(target_date)
    task_types = _golden_task_types()
    observations: dict[str, tuple[str, str]] = {}
    for score in scores:
        observations.setdefault(
            str(score.observation_id), (str(score.trace_id), score.observation_ref)
        )
    batch: list[dict[str, object]] = [
        {
            "type": "trace-create",
            "id": _event_id("trace", target_date.isoformat()),
            "timestamp": stamp,
            "body": {
                "id": golden_trace_id(target_date),
                "name": f"golden-eval/{GOLDEN_DATASET_VERSION}",
                "timestamp": stamp,
                "tags": ["caresetu", "golden-eval"],
                "metadata": gate_metadata({"provider": "golden", "model": GOLDEN_DATASET_VERSION}),
            },
        }
    ]
    for observation_id, (trace_id, example_ref) in sorted(
        observations.items(), key=lambda item: item[1][1]
    ):
        try:
            task_type = task_types[example_ref]
        except KeyError as exc:
            raise ValueError(
                f"golden observation {example_ref!r} is not part of the golden dataset"
            ) from exc
        batch.append(
            {
                "type": "observation-create",
                "id": _event_id("observation", target_date.isoformat(), example_ref),
                "timestamp": stamp,
                "body": {
                    "id": observation_id,
                    "traceId": trace_id,
                    "type": "SPAN",
                    "name": f"golden-eval/{example_ref}",
                    "startTime": stamp,
                    "endTime": stamp,
                    "metadata": golden_observation_metadata(task_type),
                },
            }
        )
    return {"batch": batch}


def build_score_bodies(scores: Sequence[EvaluationScore]) -> list[dict[str, object]]:
    """The score array for the scores endpoint - observation-level, deterministic.

    Each entry names its observation and trace, and its id is the derived
    :func:`vendor_score_id`, so a repeat post of the same date upserts the
    same rows. Sorted by ``(observation, evaluator)`` so the request body is
    byte-identical across re-runs.
    """
    _require_observation_level(scores)
    ordered = sorted(scores, key=lambda score: (str(score.observation_id), score.evaluator))
    return [
        {
            "id": vendor_score_id(str(score.observation_id), score.evaluator),
            "name": score.evaluator,
            "value": score.value,
            "dataType": score.data_type,
            "traceId": score.trace_id,
            "observationId": score.observation_id,
        }
        for score in ordered
    ]


async def post_evaluation_scores(
    target_date: date,
    scores: Sequence[EvaluationScore],
    *,
    public_key: str,
    secret_key: str,
    host: str,
    timeout_seconds: float,
    client: httpx.AsyncClient | None = None,
) -> int | None:
    """Create the golden observations and post their scores in two requests.

    Returns ``None`` without sending anything when ``public_key`` is absent -
    the unconfigured-vendor no-op - and the number of scores posted otherwise.
    A non-2xx response raises (``httpx.HTTPStatusError``): one failed night
    reports loudly and the operator re-runs the step for that date, which is
    idempotent on both requests. ``client`` is injectable so tests point the
    run at a fake API (``httpx.MockTransport``).
    """
    if not public_key:
        log.info("langfuse keys absent; evaluation score post skipped")
        return None
    _require_observation_level(scores)
    if not scores:
        return 0

    owns_client = client is None
    http = client if client is not None else httpx.AsyncClient(timeout=timeout_seconds)
    try:
        ingestion = await http.post(
            f"{host.rstrip('/')}/{INGESTION_PATH}",
            json=build_ingestion_batch(target_date, scores),
            auth=httpx.BasicAuth(public_key, secret_key),
        )
        ingestion.raise_for_status()
        response = await http.post(
            f"{host.rstrip('/')}/{SCORES_PATH}",
            json=build_score_bodies(scores),
            auth=httpx.BasicAuth(public_key, secret_key),
        )
        response.raise_for_status()
    finally:
        if owns_client:
            await http.aclose()
    return len(scores)


__all__ = [
    "INGESTION_PATH",
    "SCORES_PATH",
    "build_ingestion_batch",
    "build_score_bodies",
    "post_evaluation_scores",
]
