"""v8.2__care_vocabulary_hardening - enforce the canonical Phase 8 vocabulary

PHASE-8 review-close T1 (#427, parent #426): harden the ``care`` schema so the
database enforces what the glossary and the two state machines already forbid.
``consult_complete`` is the audited milestone on the ``PreSummary ->
PrescriptionPending`` transition, never a dwell stage, so it is dropped from the
``ck_care_cases_stage`` CHECK; ``approved`` is not a prescription dwell status
(revision-freeze approval lands directly in ``issued``), so it is dropped from
the ``ck_care_prescriptions_status`` CHECK. The ``verification_declaration``
column on ``care_rx_approvals`` becomes a real boolean with a false default
(no free-text write), ``care_cases.pre_summary_id`` becomes NOT NULL (a care
case never exists without the finalized pre-summary it was born from), and the
``forced_review`` boolean (false default) records the low-confidence forced
review for case views. No cross-schema foreign keys (ADR-0003).

Revision ID: ee3394de5a38
Revises: 384cef07d101
Create Date: 2026-09-15
"""

from collections.abc import Sequence

from alembic import op

revision: str = "ee3394de5a38"
down_revision: str | Sequence[str] | None = "384cef07d101"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # care_cases: forced_review boolean (false default) + non-null pre_summary_id
    op.execute(
        "ALTER TABLE care.care_cases ADD COLUMN forced_review BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute("ALTER TABLE care.care_cases ALTER COLUMN pre_summary_id SET NOT NULL")

    # Case-stage CHECK admits only the dwell stages (consult_complete is a
    # milestone, never a stage).
    op.execute(
        "ALTER TABLE care.care_cases "
        "DROP CONSTRAINT ck_care_cases_stage, "
        "ADD CONSTRAINT ck_care_cases_stage "
        "CHECK (stage IN ('pre_summary', 'prescription_pending', 'closed'))"
    )

    # Prescription-status CHECK admits only the machine's real statuses.
    op.execute(
        "ALTER TABLE care.care_prescriptions "
        "DROP CONSTRAINT ck_care_prescriptions_status, "
        "ADD CONSTRAINT ck_care_prescriptions_status "
        "CHECK (status IN ('draft', 'doctor_reviewed', 'rejected', 'issued', 'fulfilled'))"
    )

    # care_rx_approvals: the mandatory double-check is a real boolean, false
    # default (rejection rows keep no declaration).
    op.execute(
        "ALTER TABLE care.care_rx_approvals "
        "ALTER COLUMN verification_declaration TYPE BOOLEAN "
        "USING (verification_declaration::boolean), "
        "ALTER COLUMN verification_declaration SET DEFAULT false"
    )


def downgrade() -> None:
    # care_rx_approvals back to free-text declaration.
    op.execute(
        "ALTER TABLE care.care_rx_approvals "
        "ALTER COLUMN verification_declaration DROP DEFAULT, "
        "ALTER COLUMN verification_declaration TYPE TEXT "
        "USING (verification_declaration::text)"
    )

    # Restore the pre-hardening CHECKs.
    op.execute(
        "ALTER TABLE care.care_prescriptions "
        "DROP CONSTRAINT ck_care_prescriptions_status, "
        "ADD CONSTRAINT ck_care_prescriptions_status "
        "CHECK (status IN "
        "('draft', 'doctor_reviewed', 'approved', 'rejected', 'issued', 'fulfilled'))"
    )
    op.execute(
        "ALTER TABLE care.care_cases "
        "DROP CONSTRAINT ck_care_cases_stage, "
        "ADD CONSTRAINT ck_care_cases_stage "
        "CHECK (stage IN "
        "('pre_summary', 'consult_complete', 'prescription_pending', 'closed'))"
    )

    # care_cases back to nullable pre_summary_id and no forced_review.
    op.execute("ALTER TABLE care.care_cases ALTER COLUMN pre_summary_id DROP NOT NULL")
    op.execute("ALTER TABLE care.care_cases DROP COLUMN forced_review")
