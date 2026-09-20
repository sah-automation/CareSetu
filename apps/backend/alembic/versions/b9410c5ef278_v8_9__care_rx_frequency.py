"""v8.9__care_rx_frequency - PHASE-8.1 T10a (#493) rx item frequency column

Adds a nullable ``frequency`` column to ``care.care_rx_items``: the doctor-
entered "how often to take a medicine" value that survives the whole
prescription journey (manual authoring, AI drafts, revision save and the
issued e-prescription read). NULL means the doctor left it blank - never
required and never gating an edit or approval. No backfill: every existing
row stays NULL (unset).

Revision ID: b9410c5ef278
Revises: ac4f18be6d92
Create Date: 2026-09-19
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b9410c5ef278"
down_revision: str | Sequence[str] | None = "ac4f18be6d92"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE care.care_rx_items ADD COLUMN frequency VARCHAR(100)")


def downgrade() -> None:
    op.execute("ALTER TABLE care.care_rx_items DROP COLUMN IF EXISTS frequency")
