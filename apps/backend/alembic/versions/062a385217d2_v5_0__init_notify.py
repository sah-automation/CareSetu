"""v5_0__init_notify - MOD-010 notify schema foundation + outbox

T11 (#246): the notify module's delivery-state table (``notify_notifications``
tracks send attempts / delivery state for the WhatsApp-first / SMS-fallback
channel, ADR-0009) plus its transactional outbox and idempotent-subscriber
ledger (ADR-0002, ADR-0003).

Revision ID: 062a385217d2
Revises: ec072bada6d3
Create Date: 2026-08-31 18:37:13.675165
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID

revision: str = "062a385217d2"
down_revision: str | Sequence[str] | None = "ec072bada6d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- notify schema (created in the v0.0 bootstrap; ensure for safety) ---
    op.execute("CREATE SCHEMA IF NOT EXISTS notify")

    # --- notify_notifications: send-attempt / delivery-state tracking ---
    op.create_table(
        "notify_notifications",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("recipient_phone_e164", sa.String(32), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("channel", sa.String(20), nullable=False, server_default="wa"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("last_error_code", sa.String(50), nullable=True),
        sa.Column("delivery_attempts", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "channel IN ('wa', 'sms')",
            name="ck_notify_notifications_channel",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'delivering', 'delivered', 'failed')",
            name="ck_notify_notifications_status",
        ),
        schema="notify",
    )

    # --- bus plumbing: outbox + consumed_events ---
    op.create_table(
        "notify_outbox",
        sa.Column(
            "id",
            PgUUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("event_id", PgUUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'inflight', 'dead_letter')",
            name="ck_notify_outbox_status",
        ),
        schema="notify",
    )
    op.create_index(
        "ix_notify_outbox_poll", "notify_outbox", ["status", "next_attempt_at"], schema="notify"
    )

    op.create_table(
        "consumed_events",
        sa.Column("event_id", PgUUID(as_uuid=True), primary_key=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("handler_result", sa.JSON, nullable=True),
        schema="notify",
    )


def downgrade() -> None:
    op.drop_table("consumed_events", schema="notify")
    op.drop_index("ix_notify_outbox_poll", schema="notify")
    op.drop_table("notify_outbox", schema="notify")
    op.drop_table("notify_notifications", schema="notify")
    op.execute("DROP SCHEMA IF EXISTS notify")
