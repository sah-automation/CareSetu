"""v6.0__directory_index - PHASE-6 T01 (#307) database foundation

The provider directory's read-side cache and the credential close-out fields
that enable expiry/revocation tracking:

1. ``partner.partner_credentials`` gains the close-out bookkeeping fields
   (``revoked_at``, ``revoked_by``, ``invalidation_reason``) that record WHY/HOW
   a credential stopped being valid, alongside the existing ``expires_at``
   (ADR-0011 - lazy read-hide + daily sweep, no background scanner).
   ``invalidation_reason`` is a closed enum (expired | revoked |
   reverification_failed) enforced by a CHECK constraint.

2. ``partner.partner_directory_index`` is created - one read-side row per
   [Active] partner (ADR-0012), forking the practice geo point, partner type,
   specialty (doctors only) and the active flag from the partner's own profile
   so search is a self-contained cached read (MOD-002, FEAT-004). The physical
   name carries the ``partner_`` prefix per the module-namespace rule
   (T6a checker #26); the directory's logical ``directory_index`` entity maps
   to this table.

3. An idempotent backfill seeds the index with every current [Active] partner
   (any partner type) whose credentials are all valid (verified, unexpired,
   unrevoked). Specialty is NULL today because no specialty data exists yet in
   the schema - partners declare it later; the field stays on the closed list.

Written by hand (ADR-0003 - a migration never imports current source), raw
``op.execute`` SQL like the rest of the partner migrations.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "9f6c2e1b7d3a"
down_revision: str | Sequence[str] | None = "2c9f3a7b5d41"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1) partner_credentials close-out bookkeeping columns + closed reason.
    op.execute(
        """
        ALTER TABLE partner.partner_credentials
            ADD COLUMN revoked_at TIMESTAMPTZ,
            ADD COLUMN revoked_by UUID,
            ADD COLUMN invalidation_reason VARCHAR(40)
        """
    )
    op.execute(
        """
        ALTER TABLE partner.partner_credentials
            ADD CONSTRAINT ck_partner_credentials_invalidation_reason
            CHECK (
                invalidation_reason IS NULL
                OR invalidation_reason IN ('expired', 'revoked', 'reverification_failed')
            )
        """
    )

    # 2) directory_index - one row per [Active] partner (ADR-0012).
    op.execute(
        """
        CREATE TABLE partner.partner_directory_index (
            partner_id BIGINT PRIMARY KEY,
            practice_latitude NUMERIC(9,6) NOT NULL,
            practice_longitude NUMERIC(9,6) NOT NULL,
            partner_type VARCHAR(20) NOT NULL,
            specialty VARCHAR(40),
            is_active BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT fk_partner_directory_index_partner
                FOREIGN KEY (partner_id) REFERENCES partner.partner_profiles (id),
            CONSTRAINT ck_partner_directory_index_partner_type
                CHECK (partner_type IN ('doctor', 'lab', 'chemist')),
            CONSTRAINT ck_partner_directory_index_specialty
                CHECK (
                    specialty IS NULL
                    OR (
                        partner_type = 'doctor'
                        AND specialty IN (
                            'General Physician', 'Pediatrician',
                            'Gynecologist', 'Dentist'
                        )
                    )
                ),
            CONSTRAINT ck_partner_directory_index_longitude
                CHECK (practice_longitude BETWEEN -180 AND 180),
            CONSTRAINT ck_partner_directory_index_latitude
                CHECK (practice_latitude BETWEEN -90 AND 90)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_partner_directory_index_type_active "
        "ON partner.partner_directory_index (partner_type, is_active)"
    )

    # 3) Idempotent backfill: every [Active] partner of any type whose
    # credentials are all valid. A credential is invalid if it is not verified,
    # past its recorded expiry date, or already closed out (revoked). Specialty
    # is left NULL (no specialty data exists in the schema yet - the value is
    # declared later). ON CONFLICT DO NOTHING keeps the fill idempotent.
    op.execute(
        """
        INSERT INTO partner.partner_directory_index
            (partner_id, practice_latitude, practice_longitude, partner_type,
             specialty, is_active)
        SELECT
            p.id,
            p.practice_latitude,
            p.practice_longitude,
            p.partner_type,
            NULL,
            true
        FROM partner.partner_profiles AS p
        WHERE p.status = 'Active'
          AND EXISTS (
                SELECT 1
                FROM partner.partner_credentials AS c
                WHERE c.profile_id = p.id
          )
          AND NOT EXISTS (
                SELECT 1
                FROM partner.partner_credentials AS c
                WHERE c.profile_id = p.id
                  AND (
                      c.verified = false
                      OR (c.expires_at IS NOT NULL AND c.expires_at <= now())
                      OR c.revoked_at IS NOT NULL
                  )
          )
        ON CONFLICT (partner_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS partner.partner_directory_index")
    op.execute(
        "ALTER TABLE partner.partner_credentials "
        "DROP CONSTRAINT IF EXISTS ck_partner_credentials_invalidation_reason"
    )
    op.execute(
        "ALTER TABLE partner.partner_credentials "
        "DROP COLUMN revoked_at, DROP COLUMN revoked_by, "
        "DROP COLUMN invalidation_reason"
    )
