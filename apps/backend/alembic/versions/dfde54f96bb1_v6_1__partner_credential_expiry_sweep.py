"""v6.1__partner_credential_expiry_sweep - indexed daily expiry sweep (#323)

The daily credential-expiry close-out pass (``close_out_expired_credentials``,
PHASE-6 T04b #316, ADR-0011) selects every live, verified, expired credential
of an ``[Active]`` partner. As the directory grows that SELECT walks the whole
``partner_credentials`` table every day. This adds a partial index - mirroring
the ``ix_partner_credentials_cleanup_due`` pattern - over the sweep's
credential-local eligibility predicates: ``expires_at`` recorded and overdue
(the range, served on the leading column), a NULL ``invalidation_reason`` (the
sweep's idempotency key), and ``verified``, so the pass stays a narrow range
read instead of a full scan. The ``[Active]`` profile-join predicate is a
separate-table residual a single-table partial index cannot cover. Purely a
physical-plan change: the close-out transaction, event emission, and deindex are
untouched.

Revision ID: dfde54f96bb1
Revises: 9f6c2e1b7d3a
Create Date: 2026-09-06
"""

from collections.abc import Sequence

from alembic import op

revision: str = "dfde54f96bb1"
down_revision: str | Sequence[str] | None = "9f6c2e1b7d3a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX ix_partner_credentials_expiry_due
            ON partner.partner_credentials (expires_at)
            WHERE expires_at IS NOT NULL
              AND invalidation_reason IS NULL
              AND verified
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS partner.ix_partner_credentials_expiry_due")
