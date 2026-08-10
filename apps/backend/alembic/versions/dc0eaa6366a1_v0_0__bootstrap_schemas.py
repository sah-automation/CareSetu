"""v0.0__bootstrap_schemas - create the 11 private module schemas

PHASE-1 T1b (#18): the bootstrap delta of ADR-0003 - one private PostgreSQL
schema per bounded context (iam, partner, health, consent, intake, care,
diagnostics, fulfillment, settlement, notify, audit). The outbox DDL template
ships as Python (``bus/outbox_ddl.py``); per-module ``*_outbox`` and
``consumed_events`` tables are materialized by each module's own migration
from Phase 2 onward, never here.

Revision ID: dc0eaa6366a1
Revises: 3481d39c74cc
Create Date: 2026-08-10 22:37:30.931859

"""

from collections.abc import Sequence

from alembic import op

from bus.bootstrap import MODULE_SCHEMAS

revision: str = "dc0eaa6366a1"
down_revision: str | Sequence[str] | None = "3481d39c74cc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for schema in MODULE_SCHEMAS:
        op.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')


def downgrade() -> None:
    for schema in MODULE_SCHEMAS:
        op.execute(f'DROP SCHEMA IF EXISTS "{schema}"')
