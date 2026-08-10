"""empty async baseline - migration harness foundation

The async Alembic harness (PHASE-1 T1a) is exercised through this empty
baseline revision: it anchors a single migration head and gives
`alembic upgrade head` / `alembic downgrade base` a no-op round-trip on a
fresh database. The 11 private schemas and outbox DDL template arrive in the
next versioned delta (T1b).

Revision ID: 3481d39c74cc
Revises:
Create Date: 2026-08-10

"""

from collections.abc import Sequence

revision: str = "3481d39c74cc"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
