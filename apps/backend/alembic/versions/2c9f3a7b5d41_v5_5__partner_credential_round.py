"""v5.5__partner_credential_round

PHASE-5 fix (#266, S13): the credential duplicate gate must scope to the
*current* verification round, so a previously-rejected partner can re-offer a
rejected type in a fresh round without tripping the duplicate check. Today
``partner_credentials`` has no round attribution - credentials carry only a
``profile_id`` and ``created_at``, so the loader approximated round membership
via timestamps (fragile to any future decoupling of ingestion from round
creation). This migration adds an explicit ``round`` column to each credential,
carrying the verification round it was submitted in, and backfills existing rows
from the round whose verification row opened in the same instant (the facade
ingests credentials and opens the round in one transaction, so both share
PostgreSQL's transaction-stable ``now()``).

Revision ID: 2c9f3a7b5d41
Revises: d141437412da
Create Date: 2026-09-02
"""

from collections.abc import Sequence

from alembic import op

revision: str = "2c9f3a7b5d41"
down_revision: str | Sequence[str] | None = "d141437412da"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE partner.partner_credentials
            ADD COLUMN round BIGINT NOT NULL DEFAULT 1
        """
    )
    # Backfill: assign each existing credential the round of the latest
    # verification row opened at-or-before it (they share a transaction's
    # created_at). Stragglers with no matching round keep the default 1.
    op.execute(
        """
        UPDATE partner.partner_credentials AS c
        SET round = COALESCE(
            (
                SELECT v.round
                FROM partner.partner_verifications AS v
                WHERE v.profile_id = c.profile_id
                  AND v.created_at <= c.created_at
                ORDER BY v.created_at DESC
                LIMIT 1
            ),
            1
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_partner_credentials_profile_round "
        "ON partner.partner_credentials (profile_id, round)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS partner.ix_partner_credentials_profile_round")
    op.execute("ALTER TABLE partner.partner_credentials DROP COLUMN round")
