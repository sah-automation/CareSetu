"""v8.11__consent_health_background_scope - additive health_background scope

US-35 of #529: patient-authored health background becomes a first-class
shareable record area, so its consent gate needs its own ``health_background``
record scope - independent of ``full_record`` but still subsumed by it
(ADR-004). The change is purely additive: the ``record_scope IN (...)` lists
on ``consent_consents`` and ``consent_egress_log`` widen to admit the new
value, so every existing row stays valid and migrations cleanly. PostgreSQL
has no in-place CHECK alter, so each constraint is dropped and re-added.

Revision ID: c3c52295eabf
Revises: ca8d2419f2b6
Create Date: 2026-09-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c3c52295eabf"
down_revision: str | Sequence[str] | None = "ca8d2419f2b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCOPES = (
    "('consultations', 'prescriptions', 'lab_results', 'metrics', "
    "'health_background', 'full_record')"
)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE consent.consent_consents "
        "DROP CONSTRAINT ck_consent_consents_record_scope, "
        f"ADD CONSTRAINT ck_consent_consents_record_scope CHECK (record_scope IN {_SCOPES})"
    )
    op.execute(
        "ALTER TABLE consent.consent_egress_log "
        "DROP CONSTRAINT ck_consent_egress_log_record_scope, "
        f"ADD CONSTRAINT ck_consent_egress_log_record_scope CHECK (record_scope IN {_SCOPES})"
    )


def downgrade() -> None:
    old_scopes = "('consultations', 'prescriptions', 'lab_results', 'metrics', 'full_record')"
    op.execute(
        "ALTER TABLE consent.consent_egress_log "
        "DROP CONSTRAINT ck_consent_egress_log_record_scope, "
        f"ADD CONSTRAINT ck_consent_egress_log_record_scope CHECK (record_scope IN {old_scopes})"
    )
    op.execute(
        "ALTER TABLE consent.consent_consents "
        "DROP CONSTRAINT ck_consent_consents_record_scope, "
        f"ADD CONSTRAINT ck_consent_consents_record_scope CHECK (record_scope IN {old_scopes})"
    )
