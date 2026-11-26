"""v8.3__care_cases_unique_pre_summary - exactly one care case per pre_summary

PHASE-8 review-close T9 (#437, parent #426): close the US2 contract gap - "an
at-least-once outbox delivery never creates duplicate care cases" - at the
database. ``care_cases.pre_summary_id`` (already NOT NULL from v8.2) gains a
UNIQUE index so the case-birth consumer's SELECT-then-INSERT guard is backed by
the schema: two DISTINCT ``pre_summary.ready`` event_ids naming one
pre_summary (intake emits the event at both Draft creation and Final review)
can never double-insert under concurrent delivery. The subscriber insert now
uses ``INSERT ON CONFLICT DO NOTHING`` against this index (no cross-schema
foreign keys, ADR-0003).

Revision ID: 5df27e3710db
Revises: ee3394de5a38
Create Date: 2026-09-15
"""

from collections.abc import Sequence

from alembic import op

revision: str = "5df27e3710db"
down_revision: str | Sequence[str] | None = "ee3394de5a38"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX uq_care_cases_pre_summary_id ON care.care_cases (pre_summary_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX care.uq_care_cases_pre_summary_id")
