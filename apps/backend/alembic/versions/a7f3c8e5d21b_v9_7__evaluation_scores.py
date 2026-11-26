"""v9.7__evaluation_scores - the #751 code-evaluator verdicts, one row per observation and evaluator

PHASE-14A Batch 4 (#751, spec #717 decision 40). Additive only: one new table in
this module's own schema, and no existing table changes semantics.

The daily batch's evaluators are deterministic code - no model call, no
inference money, no clinical content - and every verdict they reach has to be
recorded somewhere it can be aggregated, re-joined and (later) argued with by a
human. ``observability.observability_evaluation_scores`` is that somewhere: one
row per ``(score_date, observation_kind, observation_ref, evaluator)`` holding a
numeric (six-decimal) or boolean (0/1) value, so a query can average a day of a
metric without parsing prose.

The natural key is what makes the nightly step re-runnable: the batch runs on
the same schedule as the #750 metrics pull, and re-running a date after a fix
replaces that date's rows (upsert on the key) instead of stacking a second set
of scores beside the first. ``id`` stays BIGSERIAL for the house style; the
identity is the key.

``trace_id`` is the cross-tool join: it is how #752's annotation queue will
match a human's judgement about one call to this table's technical verdict
about the same call, which is why the queue needs the score shape to be this
table's shape and not a vendor-side export. ``source`` anticipates that handoff
- ``code`` rows are written by this batch today; ``human`` is reserved for the
queue's annotations, so the human signal lands in the same rows later without
a schema change.

``observation_kind`` separates production AI-job telemetry from golden-dataset
examples, so golden scores can be charted as their own series and can never be
mistaken for production quality by a query that forgot to filter.

No PHI (security-phii-standards): evaluator names, a date, a kind, a local
reference, a trace id and a number. Content a score was computed FROM (golden
text, provider payloads) is never copied here - only the verdict.

Written by hand (ADR-0003 - a migration never imports current source), in the raw
``op.execute`` DDL idiom of ``v9_5__ai_queue_open``.

Revision ID: a7f3c8e5d21b
Revises: d3f8c1a9e204
Create Date: 2026-10-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a7f3c8e5d21b"
down_revision: str | Sequence[str] | None = "d3f8c1a9e204"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE observability.observability_evaluation_scores (
            id BIGSERIAL PRIMARY KEY,
            score_date DATE NOT NULL,
            source VARCHAR(10) NOT NULL DEFAULT 'code',
            observation_kind VARCHAR(20) NOT NULL,
            observation_ref VARCHAR(64) NOT NULL,
            trace_id VARCHAR(64),
            evaluator VARCHAR(64) NOT NULL,
            data_type VARCHAR(10) NOT NULL,
            value NUMERIC(12, 6) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_observability_evaluation_scores_key
                UNIQUE (score_date, observation_kind, observation_ref, evaluator),
            CONSTRAINT ck_observability_evaluation_scores_source
                CHECK (source IN ('code', 'human')),
            CONSTRAINT ck_observability_evaluation_scores_data_type
                CHECK (data_type IN ('NUMERIC', 'BOOLEAN')),
            CONSTRAINT ck_observability_evaluation_scores_boolean_value
                CHECK (data_type <> 'BOOLEAN' OR value IN (0, 1))
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_observability_evaluation_scores_trace
        ON observability.observability_evaluation_scores (trace_id)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_observability_evaluation_scores_date
        ON observability.observability_evaluation_scores (score_date)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE observability.observability_evaluation_scores")
