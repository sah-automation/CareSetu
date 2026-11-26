"""v3.1__record_access_history_actor_details - enrich the read-access ledger

PHASE-4 T7 (#241): ``health.health_record_access_history`` grows the columns
the patient access-history view (``AccessHistoryEntry``) answers - who read
over which scope (``actor_type`` / ``scope``) and, for denied attempts, why
(``denial_reason``). PHASE-3 T1 (#235) shipped the ledger with only the
actor's identity id and a binary outcome; those three facts ride the
``record.accessed`` / ``record_view_denied`` outbox payload (T5) but were
never persisted next to the fast patient view, so ``get_access_history``
could not answer FEAT-003's "who / how / why" without them. Columns are
NULLABLE - additive and safe against any pre-existing ledger rows written
by the earlier phases; fresh rows from ``_log_access`` always populate them.
``actor_type`` is CHECK-pinned to the closed counterparty vocabulary exactly
like the consent egress log (PHASE-3 FIX-2, #221) - every write path derives
it from a bounded source (the ``counterparty_type`` Literal or a module
constant). ``scope`` is deliberately NOT pinned: the ledger is a happened-
events record that also captures DENIED attempts, and the consent gate
(MOD-004 ``_scope_subsumes``) is engineered to fail closed against unknown
requested scopes - a denial for scope ``'everything'`` must still be recorded
as it happened. The consent egress log pins ``record_scope`` only because it
exclusively records allowed egress after the grant triple was validated.

Revision ID: 57256bcd989c
Revises: 6042a25ba655
Create Date: 2026-08-30

"""

from collections.abc import Sequence

from alembic import op

revision: str = "57256bcd989c"
down_revision: str | Sequence[str] | None = "6042a25ba655"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE health.health_record_access_history
            ADD COLUMN actor_type VARCHAR(20),
            ADD COLUMN scope VARCHAR(40),
            ADD COLUMN denial_reason TEXT,
            ADD CONSTRAINT ck_health_record_access_history_actor_type
                CHECK (actor_type IN ('patient', 'doctor', 'lab', 'chemist'))
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE health.health_record_access_history "
        "DROP CONSTRAINT IF EXISTS ck_health_record_access_history_actor_type"
    )
    op.execute(
        "ALTER TABLE health.health_record_access_history DROP COLUMN IF EXISTS denial_reason"
    )
    op.execute("ALTER TABLE health.health_record_access_history DROP COLUMN IF EXISTS scope")
    op.execute("ALTER TABLE health.health_record_access_history DROP COLUMN IF EXISTS actor_type")
