"""v8.4__intake_assigned_partner - patient pick-a-doctor assignment (ticket #443)

PHASE-8.1 T05 (#443): the patient pick-a-doctor write atomically records
the chosen doctor and the consent grant. ``intake_intakes.assigned_partner_id``
is the chosen doctor's partner identity - set once by the patient's pick,
never changed thereafter. Before the pick it is NULL; after the pick only
the assigned doctor may read the pre-summary (assigned-partner scoping).
No cross-schema foreign key: partner ids are gateway principals (ADR-0003).

Revision ID: a1b2c3d4e5f6
Revises: 5df27e3710db
Create Date: 2026-09-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "5df27e3710db"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE intake.intake_intakes
            ADD COLUMN assigned_partner_id BIGINT NULL
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE intake.intake_intakes DROP COLUMN assigned_partner_id")
