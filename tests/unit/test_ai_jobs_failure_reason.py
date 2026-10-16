"""B9 #728: the AI-job failure reason the provider board is named from.

``modules.intake.adapters.ai_jobs`` classifies a failed provider call into the one
short, PHI-free operational reason that rides ``ai_job.failed`` and, from there,
the observability schema's ``last_error`` column. Two answers are derived off the
exception's cause chain, and both exist because the board (#717 story 42) has to
NAME a degraded provider's failure rather than infer it:

* whether the provider refused for quota - the one case an exception class name
  cannot express, since a 429 exhaustion and a 5xx exhaustion are both
  ``Ext002CallError``;
* whether the call timed out, which the aggregate buckets separately.

Neither reads the provider's response body, which can echo the request content
sent to it. Nothing but the typed error's own flag is consulted.
"""

from __future__ import annotations

import httpx

from modules.intake.adapters.ai_gateway import Ext002CallError
from modules.intake.adapters.ai_jobs import (
    FAILURE_REASON_RATE_LIMITED,
    failure_reason,
    is_timeout,
)
from modules.observability.domain.rollup import summarize_failures


def _exhausted(
    *, rate_limited: bool = False, cause: BaseException | None = None
) -> Ext002CallError:
    """The error ``post_with_backoff`` raises once the retry budget is spent."""
    try:
        raise Ext002CallError(
            "structure https://provider.test failed after 3 attempts (last HTTP 429)",
            retries_exhausted=True,
            rate_limited=rate_limited,
        ) from cause
    except Ext002CallError as raised:
        return raised


def test_a_quota_refusal_is_named_rather_than_left_as_a_class_name() -> None:
    """The whole point: "being throttled" and "being unreachable" are different."""
    assert failure_reason(_exhausted(rate_limited=True)) == FAILURE_REASON_RATE_LIMITED


def test_a_refusal_found_further_down_the_cause_chain_is_still_named() -> None:
    """The flag is walked to, because the fallback chain wraps the gateway error."""
    wrapper = RuntimeError("fallback provider also failed")
    wrapper.__cause__ = _exhausted(rate_limited=True)

    assert failure_reason(wrapper) == FAILURE_REASON_RATE_LIMITED


def test_every_other_failure_keeps_the_reason_it_always_had() -> None:
    """An outage, a contract rejection and a plain bug all still name themselves."""
    assert failure_reason(_exhausted()) == "Ext002CallError"
    assert failure_reason(ValueError("no audio bytes")) == "ValueError"
    assert failure_reason(TimeoutError("too slow")) == "TimeoutError"


def test_a_rate_limited_token_is_matched_against_a_typed_error_not_a_string() -> None:
    """An exception whose MESSAGE mentions 429 is not a quota refusal.

    Only the typed flag counts. Matching on the message would make any provider
    error quoting a 429 - including one echoing a request body back - read as a
    throttle, which is exactly the inference this ticket exists to remove.
    """
    decoy = Ext002CallError(
        'provider rejected: {"error": "429 seen earlier"}',
        retries_exhausted=False,
    )

    assert failure_reason(decoy) == "Ext002CallError"


def test_a_timeout_is_classified_independently_of_the_rate_limit_flag() -> None:
    """A timed-out call that was ALSO refused is still bucketed as a timeout.

    The two buckets are mutually exclusive in the daily aggregate, so the reason
    token and the boolean have to be able to disagree without one overwriting the
    other.
    """
    timed_out = _exhausted(rate_limited=True, cause=httpx.ReadTimeout("no bytes"))

    assert is_timeout(timed_out) is True
    assert failure_reason(timed_out) == FAILURE_REASON_RATE_LIMITED


def test_a_non_timeout_is_not_reported_as_one() -> None:
    assert is_timeout(_exhausted()) is False
    assert is_timeout(ValueError("nope")) is False


def test_the_reason_the_producer_emits_is_the_one_the_rollup_counts() -> None:
    """The two ends of the signal are joined by this test, not by a shared constant.

    The producer names the refusal and the rollup counts the name, and ADR-0003
    forbids the rollup importing the producing module, so each side holds its own
    copy of the token. That is why this test exists: if the copies drift, the board
    would count zero quotas and show a throttled provider as healthy - silently,
    with a green suite.
    """
    named = failure_reason(_exhausted(rate_limited=True))

    failures = summarize_failures([named])

    assert named == FAILURE_REASON_RATE_LIMITED
    assert failures.rate_limit_count == 1
    assert failures.last_error == FAILURE_REASON_RATE_LIMITED
