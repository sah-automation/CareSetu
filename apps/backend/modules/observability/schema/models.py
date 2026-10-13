"""MOD-013: SQLAlchemy models for the ``observability`` schema only (ADR-0003).

Table namespace rule (coding-standards §2, T6a checker #26): every table is
prefixed with ``observability_`` and lives in the ``observability`` schema. The
module is telemetry, not a domain bounded context - a sibling of MOD-011 Audit
(plan-phase14 §7.1-7.2). B3 (#701) creates the storage foundation; the B4
consumer accumulates into these aggregates and the B5 rollup recomputes the
percentile-based columns. Column shapes are defined by the same-name
``v9.0__init_observability`` migration, plus the ``v9.1`` run ledger.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID

from bus.outbox_ddl import consumed_events_table, outbox_table

MODULE_METADATA = MetaData(schema="observability")


observability_ai_usage_daily = Table(
    "observability_ai_usage_daily",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    Column("usage_date", Date, nullable=False),
    Column("provider", String(30), nullable=False),
    Column("model", String(50), nullable=False),
    Column("task_type", String(30), nullable=False),
    Column("calls", Integer, nullable=False, server_default=text("0")),
    Column("success_count", Integer, nullable=False, server_default=text("0")),
    Column("failure_count", Integer, nullable=False, server_default=text("0")),
    Column("timeout_count", Integer, nullable=False, server_default=text("0")),
    Column("low_confidence_count", Integer, nullable=False, server_default=text("0")),
    Column("input_tokens", BigInteger, nullable=False, server_default=text("0")),
    Column("output_tokens", BigInteger, nullable=False, server_default=text("0")),
    Column("cost_paise", BigInteger, nullable=False, server_default=text("0")),
    Column("avg_duration_ms", Numeric(10, 2), nullable=True),
    Column("p95_duration_ms", Numeric(10, 2), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint(
        "usage_date",
        "provider",
        "model",
        "task_type",
        name="uq_observability_ai_usage_daily_scope",
    ),
    Index("ix_observability_ai_usage_daily_date", "usage_date"),
)


observability_ai_cost_budget = Table(
    "observability_ai_cost_budget",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    Column("provider", String(30), nullable=False),
    Column("model", String(50), nullable=False),
    Column("monthly_limit_paise", BigInteger, nullable=False, server_default=text("0")),
    Column("alert_threshold_pct", Integer, nullable=False, server_default=text("80")),
    Column("current_spend_paise", BigInteger, nullable=False, server_default=text("0")),
    Column("billing_period_start", Date, nullable=True),
    Column("billing_period_end", Date, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("provider", "model", name="uq_observability_ai_cost_budget_scope"),
)


observability_ai_provider_health = Table(
    "observability_ai_provider_health",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    Column("provider", String(30), nullable=False),
    Column("window_start", DateTime(timezone=True), nullable=True),
    Column("window_end", DateTime(timezone=True), nullable=True),
    Column("sample_count", Integer, nullable=False, server_default=text("0")),
    Column("success_rate", Numeric(5, 4), nullable=True),
    Column("p50_duration_ms", Numeric(10, 2), nullable=True),
    Column("p95_duration_ms", Numeric(10, 2), nullable=True),
    Column("p99_duration_ms", Numeric(10, 2), nullable=True),
    Column("breaker_state", String(20), nullable=False, server_default=text("'closed'")),
    Column("last_error", Text, nullable=True),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("provider", name="uq_observability_ai_provider_health_provider"),
)


observability_business_daily = Table(
    "observability_business_daily",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    Column("metric_key", String(100), nullable=False),
    Column("metric_date", Date, nullable=False),
    Column("value", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("metric_key", "metric_date", name="uq_observability_business_daily_metric"),
)


observability_alert_events = Table(
    "observability_alert_events",
    MODULE_METADATA,
    Column(
        "id",
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    ),
    Column("severity", String(20), nullable=False),
    Column("kind", String(50), nullable=False),
    Column("title", Text, nullable=False),
    Column("payload", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("status", String(20), nullable=False, server_default=text("'open'")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("acked_by", BigInteger, nullable=True),
    Column("acked_at", DateTime(timezone=True), nullable=True),
    Index("ix_observability_alert_events_status", "status", "created_at"),
)


observability_rollup_runs = Table(
    "observability_rollup_runs",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    # The UTC day the pass rolled. UNIQUE, so re-running a date overwrites its row
    # instead of stacking a second one - the ledger is the pass's idempotency key
    # AND its last-run marker (B5b #705).
    Column("rollup_date", Date, nullable=False),
    # ``backfill`` (the first-run history sweep) or ``daily``; free text with a CHECK
    # so a later mode is a migration, not a silent third value.
    Column("mode", String(20), nullable=False),
    # The calendar month the budget snapshot was taken against. Records which
    # billing period the run rolled INTO, so a period reset is observable.
    Column("billing_period_start", Date, nullable=False),
    Column("providers", Integer, nullable=False, server_default=text("0")),
    Column("health_rows", Integer, nullable=False, server_default=text("0")),
    Column("metric_rows", Integer, nullable=False, server_default=text("0")),
    Column("budget_snapshots", Integer, nullable=False, server_default=text("0")),
    Column("alerts_raised", Integer, nullable=False, server_default=text("0")),
    Column("alerts_resolved", Integer, nullable=False, server_default=text("0")),
    Column("ran_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("rollup_date", name="uq_observability_rollup_runs_date"),
)


observability_outbox = outbox_table("observability_outbox", "observability", MODULE_METADATA)
observability_consumed_events = consumed_events_table("observability")
