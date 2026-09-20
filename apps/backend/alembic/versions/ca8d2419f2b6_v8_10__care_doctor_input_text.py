"""v8.10__care_doctor_input_text - typed addendum as a real doctor input type

Review fix for #492: the prescription-pending workspace's typed addendum was
mislabelled as a ``voice`` input (D-B / US15 of #479 - "voice note, photo, or
typed addendum"). With only ``voice``/``photo`` in the ``care_doctor_inputs``
CHECK, a text addendum is stored as ``input_type='voice'`` pointing at a
``.txt`` blob, so the input audit row lies about the input kind. This widens
the constraint to admit ``text`` so a typed addendum is recorded honestly as
what it is.

Revision ID: ca8d2419f2b6
Revises: b9410c5ef278
Create Date: 2026-09-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "ca8d2419f2b6"
down_revision: str | Sequence[str] | None = "b9410c5ef278"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE care.care_doctor_inputs "
        "DROP CONSTRAINT ck_care_doctor_inputs_input_type, "
        "ADD CONSTRAINT ck_care_doctor_inputs_input_type "
        "CHECK (input_type IN ('voice', 'photo', 'text'))"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE care.care_doctor_inputs "
        "DROP CONSTRAINT ck_care_doctor_inputs_input_type, "
        "ADD CONSTRAINT ck_care_doctor_inputs_input_type "
        "CHECK (input_type IN ('voice', 'photo'))"
    )
