"""v8.7__iam_partner_phone_verified - partner login phone-verified marker (FEAT-014, #463)

F014-T03 (#463): ``iam.iam_identities.phone_verified`` records that a partner
demonstrated control of the phone by consuming a one-time code through the
dedicated ``POST /v1/auth/partner/verify`` route (ADR-0016). The later session
mint (F014-T04, #464) gates the partner session on this marker, so knowing a
partner's number is no longer enough to become them.

The column is NULL for every existing row - deliberately not backfilled:
parent spec #460 decides existing partners verify on their next login, and a
fresh registrant stays NULL until a partner login verifies the phone. The iam
schema model adds the matching ``nullable`` column (single source of truth:
the model and the migration must agree).

No cross-schema foreign key (ADR-0003).

Revision ID: 0f205ff8f67d
Revises: fa5860abdb97
Create Date: 2026-09-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0f205ff8f67d"
down_revision: str | Sequence[str] | None = "fa5860abdb97"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE iam.iam_identities
            ADD COLUMN phone_verified BOOLEAN NULL
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE iam.iam_identities DROP COLUMN phone_verified")
