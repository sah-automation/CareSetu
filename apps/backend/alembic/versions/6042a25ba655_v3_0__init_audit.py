"""v3.0__init_audit - MOD-011 audit schema foundation + tamper trigger

PHASE-4 T1 (#235): create the append-only, hash-chained audit ledger
(``audit_events``) plus a trigger-based tamper-detection safety net and
bus plumbing (outbox + consumed_events) for the audit module.

Revision ID: 6042a25ba655
Revises: b27d495bfe70
Create Date: 2026-08-27
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID

revision = "6042a25ba655"
down_revision = "b27d495bfe70"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- audit schema ---
    op.execute("CREATE SCHEMA IF NOT EXISTS audit")

    # --- audit_events: append-only, hash-chained ledger ---
    op.create_table(
        "audit_events",
        sa.Column(
            "id",
            PgUUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("actor_id", PgUUID(as_uuid=True), nullable=True),
        sa.Column("target_id", PgUUID(as_uuid=True), nullable=True),
        sa.Column("scope", sa.Text, nullable=True),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prev_hash", sa.Text, nullable=False),
        sa.Column("hash", sa.Text, nullable=False),
        schema="audit",
    )
    op.create_index("ix_audit_events_timestamp", "audit_events", ["timestamp"], schema="audit")
    op.create_index(
        "ix_audit_events_actor", "audit_events", ["actor_id", "timestamp"], schema="audit"
    )
    op.create_index(
        "ix_audit_events_target", "audit_events", ["target_id", "timestamp"], schema="audit"
    )
    op.create_index(
        "ix_audit_events_type", "audit_events", ["event_type", "timestamp"], schema="audit"
    )

    # REVOKE UPDATE/DELETE as the primary append-only guard
    op.execute("REVOKE UPDATE, DELETE ON audit.audit_events FROM caresetu")

    # --- audit_tamper_attempts: defense-in-depth log (table first, then trigger) ---
    op.create_table(
        "audit_tamper_attempts",
        sa.Column(
            "id",
            PgUUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempted_operation", sa.Text, nullable=False),
        sa.Column("target_event_id", PgUUID(as_uuid=True), nullable=True),
        sa.Column("attempted_by", PgUUID(as_uuid=True), nullable=True),
        sa.Column("details", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        schema="audit",
    )

    # --- tamper detection trigger (defense-in-depth) ---
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit.fn_audit_tamper_guard()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        AS $$
        BEGIN
            INSERT INTO audit.audit_tamper_attempts
                (attempted_at, attempted_operation, target_event_id, attempted_by, details)
            VALUES
                (
                    now(),
                    TG_OP,
                    COALESCE(OLD.id, NEW.id),
                    NULL,
                    jsonb_build_object(
                        'table_name', TG_TABLE_SCHEMA || '.' || TG_TABLE_NAME,
                        'old_data', to_jsonb(OLD),
                        'new_data', to_jsonb(NEW),
                        'user', current_user
                    )
                );
            RETURN NULL;  -- block the operation
        END;
        $$;
        """
    )
    op.execute(
        "CREATE TRIGGER trg_audit_tamper_guard "
        "BEFORE UPDATE OR DELETE ON audit.audit_events "
        "FOR EACH ROW EXECUTE PROCEDURE audit.fn_audit_tamper_guard()"
    )

    # --- bus plumbing: outbox + consumed_events ---
    op.create_table(
        "audit_outbox",
        sa.Column(
            "id",
            PgUUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("event_id", PgUUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'inflight', 'dead_letter')",
            name="ck_audit_outbox_status",
        ),
        schema="audit",
    )
    op.create_index(
        "ix_audit_outbox_poll", "audit_outbox", ["status", "next_attempt_at"], schema="audit"
    )

    op.create_table(
        "consumed_events",
        sa.Column("event_id", PgUUID(as_uuid=True), primary_key=True),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("handler_result", sa.JSON, nullable=True),
        schema="audit",
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_audit_tamper_guard ON audit.audit_events")
    op.execute("DROP FUNCTION IF EXISTS audit.fn_audit_tamper_guard()")
    op.execute("GRANT UPDATE, DELETE ON audit.audit_events TO caresetu")
    op.drop_table("consumed_events", schema="audit")
    op.drop_index("ix_audit_outbox_poll", schema="audit")
    op.drop_table("audit_outbox", schema="audit")
    op.drop_table("audit_tamper_attempts", schema="audit")
    op.drop_index("ix_audit_events_type", schema="audit")
    op.drop_index("ix_audit_events_target", schema="audit")
    op.drop_index("ix_audit_events_actor", schema="audit")
    op.drop_index("ix_audit_events_timestamp", schema="audit")
    op.drop_table("audit_events", schema="audit")
    op.execute("DROP SCHEMA IF EXISTS audit CASCADE")
