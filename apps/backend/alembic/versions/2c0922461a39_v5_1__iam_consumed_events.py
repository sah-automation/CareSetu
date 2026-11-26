"""v5_1__iam_consumed_events - materialize the iam idempotent-subscriber ledger

PHASE-5 T3 (#248): the iam module becomes a bus consumer for the first time
(the event-driven partner role grant/deny chain - ``partner.activated`` /
``partner.rejected`` / ``credential.invalidated``). Module consumers must
record consumed event ids in an idempotent-subscriber ledger in their own
schema (ADR-0002, ADR-0003). Materialize ``iam.consumed_events`` here, using
the same shape as the other modules' ledgers (help ``health.consumed_events``).

Revision ID: 2c0922461a39
Revises: 062a385217d2
Create Date: 2026-08-31
"""

from collections.abc import Sequence

from alembic import op

revision: str = "2c0922461a39"
down_revision: str | Sequence[str] | None = "062a385217d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE iam.consumed_events (
            event_id UUID NOT NULL PRIMARY KEY,
            event_type VARCHAR(100) NOT NULL,
            processed_at TIMESTAMPTZ NOT NULL,
            handler_result JSONB
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS iam.consumed_events")
