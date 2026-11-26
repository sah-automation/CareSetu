"""v8.1__care_consult_complete - record the consult-complete milestone

PHASE-8 T04 (#420): the consult-complete milestone (CONTEXT.md glossary) is
the audited from-to marker on the ``PreSummary -> PrescriptionPending``
transition when the doctor closes the off-platform consult on-platform in one
action. It is a milestone, never a dwell stage, so it is recorded as two
fields on ``care_cases`` (not a separate table): ``consult_completed_at`` (the
timestamp) and ``consult_completed_by`` (the attributing doctor's MOD-001
gateway identity). No cross-schema foreign key: identity ids are gateway
principals (ADR-0003). Both columns stay NULL until the doctor's one-action
handshake lands.

Revision ID: 384cef07d101
Revises: 145ca8587d12
Create Date: 2026-09-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "384cef07d101"
down_revision: str | Sequence[str] | None = "145ca8587d12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE care.care_cases
            ADD COLUMN consult_completed_at TIMESTAMPTZ,
            ADD COLUMN consult_completed_by BIGINT
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE care.care_cases "
        "DROP COLUMN consult_completed_by, DROP COLUMN consult_completed_at"
    )
