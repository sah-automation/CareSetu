"""v3.2__audit_tamper_detected_event - publish tamper telemetry to the outbox

PHASE-4 review fix (issue #234 user story 11): the tamper guard must not only
record the attempt in ``audit_tamper_attempts`` but also publish
``audit.tamper_detected`` into ``audit.audit_outbox`` so telemetry consumers
can alert. The trigger is recreated with an additional INSERT into the module's
outbox in the same statement - the block and the publication are atomic, and
at-least-once delivery fans it out to MOD-011's logging consumer (real-time
alerting itself stays deferred).

Revision ID: 1c8a3f72e905
Revises: 57256bcd989c
Create Date: 2026-08-30
"""

from alembic import op

revision: str = "1c8a3f72e905"
down_revision: str = "57256bcd989c"
branch_labels = None
depends_on = None

_TAMPER_GUARD_FN = """
CREATE OR REPLACE FUNCTION audit.fn_audit_tamper_guard()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_attempted_at timestamptz := now();
    v_target_event_id uuid := COALESCE(OLD.id, NEW.id);
    v_details jsonb := jsonb_build_object(
        'table_name', TG_TABLE_SCHEMA || '.' || TG_TABLE_NAME,
        'old_data', to_jsonb(OLD),
        'new_data', to_jsonb(NEW),
        'user', current_user
    );
BEGIN
    INSERT INTO audit.audit_tamper_attempts
        (attempted_at, attempted_operation, target_event_id, attempted_by, details)
    VALUES
        (v_attempted_at, TG_OP, v_target_event_id, NULL, v_details);

    INSERT INTO audit.audit_outbox
        (event_id, event_type, payload, occurred_at)
    VALUES
        (
            gen_random_uuid(),
            'audit.tamper_detected',
            jsonb_build_object(
                'attempted_operation', TG_OP,
                'target_event_id', v_target_event_id::text,
                'details', v_details,
                'attempted_at', v_attempted_at
            ),
            v_attempted_at
        );

    RETURN NULL;  -- block the operation
END;
$$;
"""


def upgrade() -> None:
    op.execute(_TAMPER_GUARD_FN)


def downgrade() -> None:
    # Restore the v3.0 body: record the attempt, block the op, no outbox publish.
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
