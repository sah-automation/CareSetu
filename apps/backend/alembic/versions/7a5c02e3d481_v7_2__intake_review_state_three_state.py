"""v7.2__intake_review_state_three_state - drop phantom review_state value (ticket #402)

PS-04 (ticket #402): the pre-summary lifecycle is exactly three states
(``draft``, ``reviewed``, ``final`` - ADR-0001); ``low_confidence`` is a
derived flag that forces doctor review and is never a fourth lifecycle
state. v7.0 (#345) shipped a CHECK that also admitted ``review_required`` -
a phantom state the machine never produces. This corrective revision
relaxes the CHECK to the binding three states. v7.0 is not rewritten: the
live database already applied it, so the correction is a new revision that
drops and re-adds the constraint (PostgreSQL has no in-place CHECK alter).

Revision ID: 7a5c02e3d481
Revises: 9f3c7cd8a409
Create Date: 2026-09-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "7a5c02e3d481"
down_revision: str | Sequence[str] | None = "9f3c7cd8a409"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE intake.intake_pre_summaries"
        " DROP CONSTRAINT ck_intake_pre_summaries_review_state"
    )
    op.execute(
        """
        ALTER TABLE intake.intake_pre_summaries
            ADD CONSTRAINT ck_intake_pre_summaries_review_state
            CHECK (review_state IN ('draft', 'reviewed', 'final'))
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE intake.intake_pre_summaries"
        " DROP CONSTRAINT ck_intake_pre_summaries_review_state"
    )
    op.execute(
        """
        ALTER TABLE intake.intake_pre_summaries
            ADD CONSTRAINT ck_intake_pre_summaries_review_state
            CHECK (review_state IN ('draft', 'review_required', 'reviewed', 'final'))
        """
    )
