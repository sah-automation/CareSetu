"""MOD-002: rejected-partner recovery rules (PHASE-5 T09, ticket #253).

Pure decision helpers for the recovery surface - the re-submission throttle and
the one-time appeal - so the boundary is testable without a database and the
business rule (ADR-0008 recovery, NFR-001 queue protection) lives in the domain
core, not in the facade or router (coding-standards §4).

The throttle is a business rule, deliberately NOT an iam/Redis rate limiter:
a ``[Rejected]`` partner may re-submit corrected credentials up to
:data:`MAX_RE_SUBMISSIONS` rounds, after which the operator queue is protected by
a cooldown (:data:`RE_SUBMISSION_COOLDOWN`) before the budget refreshes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

#: The maximum number of re-submission rounds a rejected partner may open before
#: a cooldown (protects the operator queue - NFR-001, ADR-0008).
MAX_RE_SUBMISSIONS = 3

#: The cooldown after which a throttled partner's re-submission budget refreshes.
RE_SUBMISSION_COOLDOWN: timedelta = timedelta(days=30)


@dataclass(frozen=True)
class ReSubmissionPolicy:
    """The decided state of a rejected partner's re-submission right now.

    ``allowed`` is whether a re-submission is permitted at ``now``; when not
    allowed, ``blocked_until`` (if any) names the instant the cooldown lifts.
    """

    allowed: bool
    blocked_until: datetime | None = None


def evaluate_re_submission(
    *,
    re_submission_count: int,
    re_submission_blocked_until: datetime | None,
    now: datetime,
    max_re_submissions: int = MAX_RE_SUBMISSIONS,
    cooldown: timedelta = RE_SUBMISSION_COOLDOWN,
) -> ReSubmissionPolicy:
    """Decide whether a rejected partner may re-submit at ``now``.

    A fresh cooldown expires on the budget boundary: when the count is already at
    (or past) the max the partner must wait out ``cooldown`` before re-applying.
    An in-flight (future) ``re_submission_blocked_until`` blocks unconditionally;
    once it lapses the budget is considered refreshed, so the partner may
    re-apply regardless of the (still-high) counter - the facade resets the
    counter on the next accepted submission.
    """
    if re_submission_blocked_until is not None:
        if re_submission_blocked_until.tzinfo is None:
            re_submission_blocked_until = re_submission_blocked_until.replace(tzinfo=UTC)
        if now < re_submission_blocked_until:
            return ReSubmissionPolicy(allowed=False, blocked_until=re_submission_blocked_until)
        # Cooldown lapsed: the budget has refreshed, re-apply freely.
        return ReSubmissionPolicy(allowed=True)

    if re_submission_count >= max_re_submissions:
        blocked_until = now + cooldown
        return ReSubmissionPolicy(allowed=False, blocked_until=blocked_until)

    return ReSubmissionPolicy(allowed=True)
