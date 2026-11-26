"""v9.5__ai_queue_open - the still-open AI jobs queue depth and age are derived from (B5 #729)

PHASE-14A Batch 3 (#729, spec #717 decision 16). Additive only: one new table in
this module's own schema, and no existing table changes semantics.

Queue depth is the LAGGING signal and queue age is the LEADING one, so the thing
this table exists to make measurable is the age: a single job wedged for an hour
is invisible to a depth alert that waits for a row count. Depth alone already
exists, as the per-module outbox backlog the dispatcher counts; what was missing
was an enqueue event, so nothing anywhere said a job had entered the pipeline and
both figures had to be guessed from a cross-schema read of ``intake_ai_jobs`` -
forbidden by ADR-0003.

``observability.observability_ai_queue_open`` holds the OPEN SET: one row per AI
job that has entered the pipeline and has not yet completed or failed. The
consumer writes a row per ``ai_job.queued`` (B5's new event) and deletes it on
``ai_job.completed`` / ``ai_job.failed``, so:

* depth is ``enqueued - completed - failed`` exactly, not a counter that has to be
  repaired when a close event is lost;
* the age of the oldest queued item is ``min(enqueued_at)`` over rows still here -
  an ``oldest_enqueued_at`` column on a per-queue aggregate would have to be
  un-set by whichever close happens to be the oldest, and a close that is missed
  leaves the figure pinned at the wrong stamp, which is exactly the stall an age
  must report.

Rows are deleted rather than kept as a log, so the table is bounded by queue depth
and not by traffic.

``ai_job_ref`` is UNIQUE because the row's identity IS the job: the consumed-event
ledger already makes a redelivery of the same ``event_id`` a no-op, and the unique
key makes a second enqueue event about one job a visible defect instead of a
quietly doubled depth.

No PHI: a job reference and a pipeline leg name, the same figures the intake
module's own ``ai_jobs`` table holds (security-phii-standards).

Written by hand (ADR-0003 - a migration never imports current source), in the raw
``op.execute`` DDL idiom of ``v7_0__init_intake``.

Revision ID: b6e2f9a41d07
Revises: a3d81f4c0b72
Create Date: 2026-10-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b6e2f9a41d07"
down_revision: str | Sequence[str] | None = "a3d81f4c0b72"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE observability.observability_ai_queue_open (
            id BIGSERIAL PRIMARY KEY,
            ai_job_ref BIGINT NOT NULL,
            queue VARCHAR(30) NOT NULL,
            enqueued_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_observability_ai_queue_open_job UNIQUE (ai_job_ref)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_observability_ai_queue_open_queue
        ON observability.observability_ai_queue_open (queue)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE observability.observability_ai_queue_open")
