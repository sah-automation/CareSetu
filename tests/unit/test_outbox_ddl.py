"""PHASE-1 T1b: outbox/consumed_events DDL template contract (#18).

Regression-guards the shared row contract (issue #16) without a database: the
column set, key, and not-null rules the round-trip harness (T2c) and later
module migrations depend on. Schema creation itself is exercised by the
integration suite (tests/integration/test_bootstrap_schemas.py).
"""

from sqlalchemy.dialects.postgresql import JSONB

from bus.bootstrap import MODULE_SCHEMAS
from bus.outbox_ddl import OUTBOX_STATUSES, consumed_events_table, outbox_table

EXPECTED_MODULE_SCHEMAS = (
    "iam",
    "partner",
    "health",
    "consent",
    "intake",
    "care",
    "diagnostics",
    "fulfillment",
    "settlement",
    "notify",
    "audit",
)


def test_module_schemas_match_adr_0003_layout() -> None:
    assert MODULE_SCHEMAS == EXPECTED_MODULE_SCHEMAS


def test_outbox_table_contract() -> None:
    table = outbox_table("iam_outbox", "iam")

    assert table.schema == "iam"
    assert {column.name for column in table.columns} == {
        "id",
        "event_id",
        "event_type",
        "payload",
        "occurred_at",
        "status",
        "attempts",
        "next_attempt_at",
    }
    assert list(table.primary_key.columns) == [table.c.id]
    assert not table.c.event_id.nullable
    assert not table.c.payload.nullable
    assert isinstance(table.c.payload.type, JSONB)
    assert table.c.status.server_default is not None
    assert table.c.attempts.server_default is not None
    assert OUTBOX_STATUSES == ("pending", "inflight", "dead_letter")


def test_consumed_events_table_contract() -> None:
    table = consumed_events_table("iam")

    assert table.schema == "iam"
    assert {column.name for column in table.columns} == {
        "event_id",
        "event_type",
        "processed_at",
        "handler_result",
    }
    assert list(table.primary_key.columns) == [table.c.event_id]
    assert not table.c.event_id.nullable
    assert not table.c.processed_at.nullable
