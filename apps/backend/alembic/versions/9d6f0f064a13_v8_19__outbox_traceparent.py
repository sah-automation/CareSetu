"""v8.19__outbox_traceparent - carry W3C traceparent across the async seam

PHASE-14A A2 (#695): the API mints a request trace id and the outbox seam does
not carry it, so the worker's log/trace context cannot link back to the request
that produced the event. This single additive migration adds a nullable
``traceparent`` column to every existing module outbox table (``VARCHAR(64)``,
a W3C ``traceparent`` is at most 55 chars, null when no request context
existed). The shared ``bus/outbox_ddl.py`` template gains the same column so
future tables - and modules whose outbox is materialized at runtime - get it
too.

One migration, every existing outbox table, enumerated deliberately (never
dynamic at migration time):

- iam.iam_outbox, partner.partner_outbox, health.health_outbox
- consent.consent_outbox, intake.intake_outbox, care.care_outbox
- audit.audit_outbox, notify.notify_outbox

Written by hand (ADR-0003 - a migration never imports current source), in the
raw ``op.execute`` DDL idiom of ``v2_0__init_health``.

Revision ID: 9d6f0f064a13
Revises: 5a6fc4715675
Create Date: 2026-10-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "9d6f0f064a13"
down_revision: str | Sequence[str] | None = "5a6fc4715675"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TRACEPARENT_COLUMN = "traceparent VARCHAR(64)"

OUTBOX_TABLES: tuple[str, ...] = (
    "iam.iam_outbox",
    "partner.partner_outbox",
    "health.health_outbox",
    "consent.consent_outbox",
    "intake.intake_outbox",
    "care.care_outbox",
    "audit.audit_outbox",
    "notify.notify_outbox",
)


def upgrade() -> None:
    for table in OUTBOX_TABLES:
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {_TRACEPARENT_COLUMN}")


def downgrade() -> None:
    for table in OUTBOX_TABLES:
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS traceparent")
