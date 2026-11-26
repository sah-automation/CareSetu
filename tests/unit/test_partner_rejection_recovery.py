"""PHASE-5 T09: the rejected-partner re-submission throttle policy (#253).

Pins the pure domain decision (:func:`modules.partner.domain.rejection
.evaluate_re_submission`) - the business rule that protects the operator queue
(NFR-001 headcount, ADR-0008 recovery) - as a stateless function of the profile
counters and the wall clock, testable without a database.

Contract pinned here:

- A rejected partner re-submits freely while ``count < MAX_RE_SUBMISSIONS``.
- Once ``count >= MAX_RE_SUBMISSIONS`` the next re-submission is blocked with a
  cooldown deadline ``now + cooldown`` (the first attempt past the boundary).
- An in-flight (future) ``blocked_until`` blocks unconditionally.
- A lapsed ``blocked_until`` is ignored - the budget is considered refreshed.
- A naive-``tz`` blocked deadline is normalised to UTC before comparing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from modules.partner.domain.rejection import (
    MAX_RE_SUBMISSIONS,
    RE_SUBMISSION_COOLDOWN,
    ReSubmissionPolicy,
    evaluate_re_submission,
)

_NOW = datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)


def test_allows_within_budget() -> None:
    policy = evaluate_re_submission(
        re_submission_count=2,
        re_submission_blocked_until=None,
        now=_NOW,
    )
    assert policy.allowed is True
    assert policy.blocked_until is None


def test_blocks_when_budget_is_exhausted_and_sets_cooldown() -> None:
    policy = evaluate_re_submission(
        re_submission_count=MAX_RE_SUBMISSIONS,
        re_submission_blocked_until=None,
        now=_NOW,
    )
    assert policy.allowed is False
    assert policy.blocked_until == _NOW + RE_SUBMISSION_COOLDOWN


def test_blocks_while_cooldown_is_in_flight() -> None:
    blocked_until = _NOW + timedelta(days=5)
    policy = evaluate_re_submission(
        re_submission_count=0,
        re_submission_blocked_until=blocked_until,
        now=_NOW,
    )
    assert policy.allowed is False
    assert policy.blocked_until == blocked_until


def test_lapsed_cooldown_refreshes_budget() -> None:
    # The blocked deadline is in the past and the count is below the max: the
    # partner re-applies freely (budget refreshed for the new window).
    lapsed = _NOW - timedelta(hours=1)
    policy = evaluate_re_submission(
        re_submission_count=1,
        re_submission_blocked_until=lapsed,
        now=_NOW,
    )
    assert policy.allowed is True


def test_lapsed_cooldown_allows_even_when_count_still_at_max() -> None:
    # The persisted cooldown is the source of truth: once it lapses the budget
    # has refreshed, so a stale (still-at-max) counter must NOT keep blocking -
    # the facade resets the counter on the next accepted submission.
    lapsed = _NOW - timedelta(hours=1)
    policy = evaluate_re_submission(
        re_submission_count=MAX_RE_SUBMISSIONS,
        re_submission_blocked_until=lapsed,
        now=_NOW,
    )
    assert policy.allowed is True


def test_normalises_naive_tz_blocked_deadline() -> None:
    # A stored deadline may be driver-read without a tz; the decision must still
    # compare correctly (a future naive deadline blocks).
    naive_future = (_NOW + timedelta(days=1)).replace(tzinfo=None)
    policy = evaluate_re_submission(
        re_submission_count=0,
        re_submission_blocked_until=naive_future,
        now=_NOW,
    )
    assert policy.allowed is False


def test_budget_boundary_defaults_match_module_constants() -> None:
    assert MAX_RE_SUBMISSIONS == 3
    policy = evaluate_re_submission(
        re_submission_count=MAX_RE_SUBMISSIONS,
        re_submission_blocked_until=None,
        now=_NOW,
    )
    assert policy == ReSubmissionPolicy(allowed=False, blocked_until=_NOW + RE_SUBMISSION_COOLDOWN)
