"""v9.12__iam_operator_profile_name_photo - self-service operator profile fields

Adds the nullable ``name`` (display name) and ``photo_ref`` (private profile
media key) columns to ``iam.iam_operator_profiles`` so the operator self-service
profile surface (#869) has somewhere to store its data. Existing rows keep
nulls - no backfill. Reversible.

Revision ID: b7c8d9e0a1f2
Revises: a3ce1ae6240b
Create Date: 2026-11-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b7c8d9e0a1f2"
down_revision: str | Sequence[str] | None = "a3ce1ae6240b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE iam.iam_operator_profiles ADD COLUMN IF NOT EXISTS name VARCHAR(200)")
    op.execute(
        "ALTER TABLE iam.iam_operator_profiles ADD COLUMN IF NOT EXISTS photo_ref VARCHAR(255)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE iam.iam_operator_profiles DROP COLUMN IF EXISTS photo_ref")
    op.execute("ALTER TABLE iam.iam_operator_profiles DROP COLUMN IF EXISTS name")
