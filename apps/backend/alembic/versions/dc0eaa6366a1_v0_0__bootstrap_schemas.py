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

revision: str = "dc0eaa6366a1"
down_revision: str | Sequence[str] | None = "3481d39c74cc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Intentionally frozen by design (issue #47): a migration records the exact
# database state applied at this revision, so it deliberately does not import
# ``bus.bootstrap.MODULE_SCHEMAS`` - re-reading the current source would make
# a historical migration change retroactively as later phases add modules.
# Adding a module requires a NEW migration, never an edit to this tuple.
FROZEN_MODULE_SCHEMAS: tuple[str, ...] = (
    "iam",
    "partner",
    "health",
    "consent",
    "intake",
    "care",
    "diagnostics",
    "fulfillment",
    "settlement",
    "notify",
    "audit",
)


def upgrade() -> None:
    for schema in FROZEN_MODULE_SCHEMAS:
        op.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')


def downgrade() -> None:
    for schema in FROZEN_MODULE_SCHEMAS:
        op.execute(f'DROP SCHEMA IF EXISTS "{schema}"')
