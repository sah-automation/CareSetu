"""v8.5__consultation_fee - PHASE-8.1 T06 (#444) consultation fee seam

Adds a nullable ``consultation_fee_paise`` column to ``partner.profiles``:
an integer-paise consultation fee settable by the doctor through a
partner-scoped update endpoint, exposed on the directory entry and the
verified-safe provider profile projection. NULL means unset and never
blocks a pick (AC: unset fee stays null, never gates care).

Check constraint enforces non-negative values when set; NULL remains
allowed (unset). No backfill - every existing row stays NULL (unset).

Revision ID: b38d0e62f4a7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b38d0e62f4a7"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE partner.partner_profiles
            ADD COLUMN consultation_fee_paise BIGINT
        """
    )
    op.execute(
        """
        ALTER TABLE partner.partner_profiles
            ADD CONSTRAINT ck_partner_profiles_consultation_fee
            CHECK (consultation_fee_paise IS NULL OR consultation_fee_paise >= 0)
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE partner.partner_profiles "
        "DROP CONSTRAINT IF EXISTS ck_partner_profiles_consultation_fee"
    )
    op.execute("ALTER TABLE partner.partner_profiles DROP COLUMN IF EXISTS consultation_fee_paise")
