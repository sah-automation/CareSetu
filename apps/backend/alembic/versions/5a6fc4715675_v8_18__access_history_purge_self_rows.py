"""v8.18__access_history_purge_self_rows - #665 purge stored self rows

The record access history answers "who ELSE has seen my record" (spec #662,
US-14/US-15/US-25): owner reads stopped dual-writing an access-history row
and an outbox envelope in the same release, and this migration purges the
self rows already stored before that. The purge uses the same both-columns
predicate the read path filters with (#665): the row's actor is the patient
type AND its accessor is the record's own owner identity. Keying on BOTH
columns matters - doctor rows store partner ids in the same
``accessor_identity_id`` column, so an accessor-only comparison would
mis-handle id-namespace collisions between a patient id and a partner id.

Cross-patient denied rows (a patient-type actor attempting someone else's
record) are NOT self-access and are retained: they are the security signal
the trust view exists for.

Deployment order (spec): the purge ships with the code that stops writing
self rows; the read path applies the same predicate either way, so a code
rollback after this migration still hides self rows (harmless).

ADR-0023 is the written authorization coding-standards §5 requires for
this destructive (data-deleting) migration.

Written by hand (ADR-0003 - a migration never imports current source),
raw ``op.execute`` SQL like the v3.1 enrichment migration.

Revision ID: 5a6fc4715675
Revises: 3e7c5a1d8f24
Create Date: 2026-10-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "5a6fc4715675"
down_revision: str | Sequence[str] | None = "3e7c5a1d8f24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM health.health_record_access_history AS rah
        USING health.health_patient_records AS pr
        WHERE rah.record_id = pr.id
          AND rah.actor_type = 'patient'
          AND rah.accessor_identity_id = pr.identity_id
        """
    )


def downgrade() -> None:
    # The purge is a one-way data deletion - the self rows cannot be
    # reconstructed. The read path hides self rows regardless, so a
    # downgrade is a no-op (same stance as the v8.6 backfill).
    pass
