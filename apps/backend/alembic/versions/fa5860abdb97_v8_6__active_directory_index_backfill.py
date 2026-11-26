"""v8.6__active_directory_index_backfill - PHASE-6 (#458) backfill for approved Active partners

The runtime activation seam (#456) is the ONLY path that makes an approval
directory-visible - it stamps the approved round's ``partner_credentials`` rows
``verified`` and upserts the ``partner_directory_index`` row in the same
transaction. Approvals made before that seam shipped (and the v6_0 one-shot
backfill) left already-approved ``Active`` partners holding unverified
credentials and no index row, so they stay invisible to
``GET /v1/directory/search`` until an ad-hoc dev-DB repair.

This migration closes that gap with the SAME semantics as the runtime seam, so
backfill and live path agree:

1. Stamp ``verified = true`` on every approved-round credential of an
   ``[Active]`` partner (the seam's round-scoped stamp, applied cumulatively).
   The gate is the round's own ``partner_verifications`` row carrying
   ``status = 'approved'`` - a round the operator never approved is never
   sealed (brief handoff: genuinely-correct data only), and revoked rows are
   left alone (a revoked credential stays invisible regardless). ``verified =
   false`` keeps a re-run a no-op against an already-consistent DB.

2. Upsert ``partner_directory_index`` for every ``[Active]`` partner with an
   approved verification round - the seam's index-upsert carries no
   credential-eligibility gate (it writes the row at approval, when the
   credentials are by construction fresh; the read-side ``provider_visible``
   predicate, #457, hides an expired/revoked credential lazily on every read,
   ADR-0011), so the backfill mirrors that exact condition rather than
   re-deriving eligibility. ``ON CONFLICT (partner_id) DO UPDATE`` keeps the
   seam's refresh semantics: an absent row is inserted, an existing row is
   refreshed from the live profile (location, type, ``is_active = true``),
   never duplicated.

Written by hand (ADR-0003 - a migration never imports current source), raw
``op.execute`` SQL like the rest of the partner migrations.

Revision ID: fa5860abdb97
Revises: b38d0e62f4a7
Create Date: 2026-09-17
"""

from collections.abc import Sequence

from alembic import op

revision: str = "fa5860abdb97"
down_revision: str | Sequence[str] | None = "b38d0e62f4a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1) Seam's verified stamp, cumulatively: every issued credential of an
    #    [Active] partner whose round carries an approved verification row
    #    was sealed by the live seam at its own approval - backfill that. The
    #    round-gate means no unapproved round is ever sealed; ``verified =
    #    false`` makes a re-run a no-op; revoked rows stay untouched.
    op.execute(
        """
        UPDATE partner.partner_credentials AS c
        SET verified = true,
            updated_at = now()
        WHERE c.verified = false
          AND c.revoked_at IS NULL
          AND EXISTS (
                SELECT 1
                FROM partner.partner_profiles AS p
                WHERE p.id = c.profile_id
                  AND p.status = 'Active'
          )
          AND EXISTS (
                SELECT 1
                FROM partner.partner_verifications AS v
                WHERE v.profile_id = c.profile_id
                  AND v.round = c.round
                  AND v.status = 'approved'
          )
        """
    )

    # 2) The seam's directory-index upsert (refresh semantics): one row per
    #    [Active] partner with an approved verification round - the exact
    #    population the seam would have indexed at each approval. No
    #    credential-eligibility gate (the seam upserts at approval when the
    #    credentials are fresh; the read-side provider_visible predicate
    #    hides an expired/revoked credential lazily, ADR-0011). ON CONFLICT
    #    DO UPDATE refreshes an existing row from the live profile (practice
    #    location, partner type, is_active = true) - never a duplicate -
    #    mirroring the runtime seam's on_conflict_do_update.
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
                FROM partner.partner_verifications AS v
                WHERE v.profile_id = p.id
                  AND v.status = 'approved'
          )
        ON CONFLICT (partner_id) DO UPDATE SET
            practice_latitude = EXCLUDED.practice_latitude,
            practice_longitude = EXCLUDED.practice_longitude,
            partner_type = EXCLUDED.partner_type,
            is_active = true,
            updated_at = now()
        """
    )


def downgrade() -> None:
    # The stamp and the index refresh are irreversibly correct - the migration
    # converges data toward the live path's outcome and never invents rows for
    # partners the operator did not approve. A downgrade is a no-op.
    pass
