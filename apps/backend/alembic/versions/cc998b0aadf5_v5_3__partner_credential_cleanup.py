"""v5.3__partner_credential_cleanup

US-27 (ticket #263): credential documents are deleted 30 days after permanent
rejection so the platform does not hoard identity documents (spec phase-5,
implementation decision "Credential document storage"). ``cleanup_due_at`` is
the schedule the rejection path writes (``now() + cleanup window``); a later
``purge_expired_credentials`` seam deletes the row (and its artifact files)
once the deadline lapses and the profile is still ``[Rejected]``. A NULL
``cleanup_due_at`` means no cleanup is scheduled. The partial index keeps the
purge scan scoped to scheduled rows only.

Revision ID: cc998b0aadf5
Revises: 6c1ff668355a
Create Date: 2026-09-01
"""

from collections.abc import Sequence

from alembic import op

revision: str = "cc998b0aadf5"
down_revision: str | Sequence[str] | None = "6c1ff668355a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE partner.partner_credentials
            ADD COLUMN cleanup_due_at TIMESTAMPTZ
        """
    )
    op.execute(
        """
        CREATE INDEX ix_partner_credentials_cleanup_due
            ON partner.partner_credentials (cleanup_due_at)
            WHERE cleanup_due_at IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS partner.ix_partner_credentials_cleanup_due")
    op.execute("ALTER TABLE partner.partner_credentials DROP COLUMN cleanup_due_at")
