"""v5.4__seed_daltonganj_service_area

PHASE-5 fix (#265): the ``partner_service_areas`` vocabulary has no default and
``service_area_id`` is unvalidated. This migration seeds the Daltonganj default
(the Phase-5 launch geography, REQ-008) that ``register`` associates a partner
with when no area is declared. The insert is idempotent (``ON CONFLICT DO
NOTHING`` on the unique ``name``) so re-running against an already-seeded
database is safe.

Revision ID: d141437412da
Revises: cc998b0aadf5
Create Date: 2026-09-02 17:44:33.087101
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d141437412da"
down_revision: str | Sequence[str] | None = "cc998b0aadf5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO partner.partner_service_areas (name)
        VALUES ('Daltonganj')
        ON CONFLICT (name) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM partner.partner_service_areas
        WHERE name = 'Daltonganj'
        """
    )
