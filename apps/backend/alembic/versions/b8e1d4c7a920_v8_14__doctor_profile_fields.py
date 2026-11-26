from collections.abc import Sequence

from alembic import op

revision: str = "b8e1d4c7a920"
down_revision: str | Sequence[str] | None = "d3a7c1e90562"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE partner.partner_profiles
            ADD COLUMN photo_ref VARCHAR(255),
            ADD COLUMN experience_years INTEGER,
            ADD COLUMN languages JSONB NOT NULL DEFAULT '[]'::jsonb,
            ADD COLUMN about TEXT,
            ADD COLUMN availability TEXT,
            ADD COLUMN notification_preferences JSONB NOT NULL DEFAULT '{}'::jsonb,
            ADD CONSTRAINT ck_partner_profiles_experience_years
                CHECK (
                    experience_years IS NULL
                    OR experience_years BETWEEN 0 AND 100
                );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE partner.partner_profiles
            DROP CONSTRAINT ck_partner_profiles_experience_years,
            DROP COLUMN notification_preferences,
            DROP COLUMN availability,
            DROP COLUMN about,
            DROP COLUMN languages,
            DROP COLUMN experience_years,
            DROP COLUMN photo_ref;
        """
    )
