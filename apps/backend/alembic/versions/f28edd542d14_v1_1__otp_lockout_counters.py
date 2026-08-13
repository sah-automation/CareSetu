"""v1.1__otp_lockout_counters - brute-force lockout counters on ``iam_identities``

PHASE-2 T5 (#56): the temporary 15-minute phone lockout after 10 consecutive
verification failures. The lockout is a counter, never identity state: two new
columns carry it - ``lockout_failed_attempts`` (the consecutive-failure counter
across challenges) and ``lockout_until`` (when the lockout lifts). ``status``
is untouched: ``Suspended`` remains reachable only via the operator status
change interface (spec #51 §2.4, Phase 5). The counter lives on the identity
row because it is tied to the phone and must survive challenge replacement
(resend is latest-wins), not on a single challenge row.

Revision ID: f28edd542d14
Revises: 817e4c49f32c
Create Date: 2026-08-13

"""

from collections.abc import Sequence

from alembic import op

revision: str = "f28edd542d14"
down_revision: str | Sequence[str] | None = "817e4c49f32c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE iam.iam_identities
            ADD COLUMN lockout_failed_attempts INT NOT NULL DEFAULT 0,
            ADD COLUMN lockout_until TIMESTAMPTZ
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE iam.iam_identities
            DROP COLUMN lockout_until,
            DROP COLUMN lockout_failed_attempts
        """
    )
