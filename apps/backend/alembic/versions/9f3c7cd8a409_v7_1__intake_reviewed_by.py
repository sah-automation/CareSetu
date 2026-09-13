"""v7.1__intake_reviewed_by - attribute doctor reviews (ticket #353)

PHASE-7 T09 (#353): an attributed doctor review is the hard gate into
``Reviewed`` for a low_confidence pre-summary and the single-action fast path
to ``Final`` for a high-confidence one (spec #344 user story 22: "my review
... attributed to me"). ``intake_pre_summaries.review_attribution`` already
carries the reviewing ROLE (a ``doctor`` and never a patient), but the
specific doctor behind that review was not recorded. This migration adds
``reviewed_by`` - the reviewing doctor's MOD-001 gateway identity - so every
review is attributable to a specific licensed doctor, mirroring the partner
gate's ``decision_by`` attribution column (ADR-0006 precedent). No
cross-schema foreign key: identity ids are gateway principals (ADR-0003).

Revision ID: 9f3c7cd8a409
Revises: 6cb15f638bec
Create Date: 2026-09-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "9f3c7cd8a409"
down_revision: str | Sequence[str] | None = "6cb15f638bec"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE intake.intake_pre_summaries
            ADD COLUMN reviewed_by BIGINT
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE intake.intake_pre_summaries DROP COLUMN reviewed_by")
