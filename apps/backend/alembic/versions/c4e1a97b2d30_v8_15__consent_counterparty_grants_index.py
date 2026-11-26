"""v8.15__consent_counterparty_grants_index - index the doctor console reverse lookup

#539 (US-18): ``ConsentFacade.list_counterparty_grants`` filters
``consent_consents`` on ``(counterparty_type, counterparty_id, status)`` and
orders by ``(patient_id, id)``, but the only usable indexes on the lineage
table lead with ``patient_id`` (the unique lineage key and the patient log), so
every doctor Patients-list request full-scanned the table. This index leads
with the counterparty triple, carries the order-by columns as trailing keys so
the read is an ordered index scan, and leaves every existing index in place -
an index only, no schema change.

Revision ID: c4e1a97b2d30
Revises: b8e1d4c7a920
Create Date: 2026-09-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c4e1a97b2d30"
down_revision: str | Sequence[str] | None = "b8e1d4c7a920"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "ix_consent_consents_counterparty_grants"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE INDEX {_INDEX}
            ON consent.consent_consents
            (counterparty_type, counterparty_id, status, patient_id, id);
        """
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX consent.{_INDEX}")
