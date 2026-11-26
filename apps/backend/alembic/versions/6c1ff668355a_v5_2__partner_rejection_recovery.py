"""v5_2__partner_rejection_recovery

PHASE-5 T9 (#253): the rejected-partner recovery surface - a one-time appeal and
a re-submission throttle - carried on ``partner.partner_profiles``. ``appeal_used``
is the one-flag (consumed on first use) that lets a ``[Rejected]`` partner
re-enter the operator queue exactly once. ``re_submission_count`` + the optional
``re_submission_blocked_until`` cooldown enforce the max-3 re-submissions-then-
cooldown business rule that protects the operator queue (NFR-001, ADR-0008). The
throttle is a domain/business rule on the profile - deliberately NOT an iam/Redis
rate limiter, which is not this module's seam.

Revision ID: 6c1ff668355a
Revises: 2c0922461a39
Create Date: 2026-09-01 01:36:53.195751

"""

from collections.abc import Sequence

from alembic import op

revision: str = "6c1ff668355a"
down_revision: str | Sequence[str] | None = "2c0922461a39"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE partner.partner_profiles
            ADD COLUMN appeal_used BOOLEAN NOT NULL DEFAULT false,
            ADD COLUMN re_submission_count BIGINT NOT NULL DEFAULT 0,
            ADD COLUMN re_submission_blocked_until TIMESTAMPTZ
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE partner.partner_profiles
            DROP COLUMN appeal_used,
            DROP COLUMN re_submission_count,
            DROP COLUMN re_submission_blocked_until
        """
    )
