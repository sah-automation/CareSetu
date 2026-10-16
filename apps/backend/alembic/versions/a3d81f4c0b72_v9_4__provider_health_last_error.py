"""v9.4__provider_health_last_error - the columns the provider board names failures with (B9 #728)

PHASE-14A Batch 3 (#728, spec #717 decision 18). Additive only: no existing
table changes semantics, and both new columns are nullable or defaulted, so this
is safe to run against a live deployment with rows already written.

``observability_ai_job_spend.failure_reason`` - the per-job failure reason, on the
granular source rather than on the health row. The provider health row's
``last_error`` column has existed since ``v9.0`` and nothing has ever written it,
so a degraded provider could only be INFERRED from its counters; the whole point
of the board is to NAME the failure. The reason reaches this column through the
``ai_job.failed`` event's own ``reason`` field and lands here at consume time,
because the rollup runs nightly and needs a per-job record to pick the most
recent failure from - one row per provider could only ever hold whatever arrived
last, with no ordering to resolve ties on.

The column is ``TEXT`` and nullable rather than a closed vocabulary because the
reason is the producer's to choose and MOD-013 must not refuse a reason it does
not recognise. What makes that safe is upstream: the producer that feeds it
(``modules.intake.adapters.ai_jobs.failure_reason``) emits a short operational
token or an exception class name, never a provider response body - which can echo
the request content sent to it - and the consumer (``sanitize_failure_reason``)
bounds what is written before the value is stored: control characters replaced,
the echoed continuation after the first line break dropped, length capped. The
first of those two is what keeps PHI out; the second keeps one bounded line.

``observability_ai_provider_health.rate_limit_count`` - how many of the day's
calls the provider refused for quota. The health row already carries the counters
this board reads (``sample_count``, ``success_rate``, the three percentiles and
``breaker_state``) but has nowhere to count the one condition that most changes
an operator's response: being throttled is not being unreachable. ``NOT NULL
DEFAULT 0`` rather than nullable because zero is the honest answer for a provider
that was never refused, and a NULL here would be indistinguishable from "not yet
rolled" on a column that IS rolled.

``observability_ai_provider_health.timeout_count`` - how many of the window's
calls timed out. The timeout / plain-failure split lives on
``observability_ai_usage_daily`` per scope, and it is deliberately NOT duplicated
onto the per-job source; this is its per-provider roll-up, at the grain the board
reads. Rolled onto the health row rather than joined back from the daily aggregate
at read time, so the board is one table read over rows the SAME pass computed: a
read-time join would have to guess which date each provider was last rolled on, and
a provider whose traffic stopped would silently report a different day's timeouts
than the success rate standing beside it.

Both counters are ``NOT NULL DEFAULT 0`` rather than nullable because zero is the
honest answer for a provider that had neither, and a NULL would be
indistinguishable from "not yet rolled" on a column that IS rolled.

Derived, never stored: the healthy/degraded/down status this read resolves is
NOT a column here. A stored status would be a second source of truth the nightly
recompute could contradict, so the read derives it from the counters above and
the breaker state (#717 decision 18).

Written by hand (ADR-0003 - a migration never imports current source), in the raw
``op.execute`` DDL idiom of ``v7_0__init_intake``.

Revision ID: a3d81f4c0b72
Revises: c7a4e9b1d268
Create Date: 2026-10-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a3d81f4c0b72"
down_revision: str | Sequence[str] | None = "c7a4e9b1d268"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE observability.observability_ai_job_spend
        ADD COLUMN failure_reason TEXT
        """
    )
    op.execute(
        """
        ALTER TABLE observability.observability_ai_provider_health
        ADD COLUMN timeout_count INT NOT NULL DEFAULT 0
        """
    )
    op.execute(
        """
        ALTER TABLE observability.observability_ai_provider_health
        ADD COLUMN rate_limit_count INT NOT NULL DEFAULT 0
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE observability.observability_ai_provider_health
        DROP COLUMN rate_limit_count
        """
    )
    op.execute(
        """
        ALTER TABLE observability.observability_ai_provider_health
        DROP COLUMN timeout_count
        """
    )
    op.execute(
        """
        ALTER TABLE observability.observability_ai_job_spend
        DROP COLUMN failure_reason
        """
    )
