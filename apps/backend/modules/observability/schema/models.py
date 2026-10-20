"""MOD-013: SQLAlchemy models for the ``observability`` schema only (ADR-0003).

Table namespace rule (coding-standards §2, T6a checker #26): every table is
prefixed with ``observability_`` and lives in the ``observability`` schema. The
module is telemetry, not a domain bounded context - a sibling of MOD-011 Audit
(plan-phase14 §7.1-7.2). B3 (#701) creates the storage foundation; the B4
consumer accumulates into these aggregates and the B5 rollup recomputes the
percentile-based columns. Column shapes are defined by the same-name
``v9.0__init_observability`` migration, plus the ``v9.1`` run ledger and the
``v9.2`` attribution table set (B6 #723), which adds the granular per-job spend
source, the care-attribution edge and the daily per-actor aggregate, and the
``v9.3`` runtime-capture and product table set (B8 #726), which adds the captured
error stream, the per-minute HTTP counter and the product event ledger with its
daily rollup, and the ``v9.4`` pair of columns (B9 #728) that let the provider
board name a failure - the per-job ``failure_reason`` and the per-provider
``rate_limit_count`` - and the ``v9.5`` queue table (B5 #729) that holds the
still-open AI jobs the enqueue/completion events produce, from which depth and the
oldest queued item's age are derived.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
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
    # How many of the window's calls the provider refused for quota, and how many
    # timed out. Both are rolled up from ``observability_ai_usage_daily`` at the
    # provider's grain rather than joined back at read time, so the board is one
    # table read over rows the SAME pass computed - a read-time join would have to
    # guess which date each provider was last rolled on, and a provider whose
    # traffic stopped would report a different day's timeouts than the success rate
    # beside it. DEFAULT 0 describes the row before the first pass, not a day.
    Column("timeout_count", Integer, nullable=False, server_default=text("0")),
    Column("rate_limit_count", Integer, nullable=False, server_default=text("0")),
    # The most recent failure's reason, so a degraded provider can be NAMED rather
    # than inferred from its counters (#717 decision 18). Written by the nightly
    # rollup from the per-job failure reasons; NULL means the window recorded no
    # failure to name, which is not the same as "no failure" on its own.
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


observability_ai_job_spend = Table(
    "observability_ai_job_spend",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    Column("usage_date", Date, nullable=False),
    # The job's OWN reference, and the grain of the table: UNIQUE, because
    # "one row per AI job" is what every downstream number is computed from.
    # Without it the row's identity would be the event that happened to report
    # the job, and a second event naming an already-recorded job would silently
    # double one patient's spend. The outbox ledger already makes a redelivery of
    # the SAME event_id a no-op; this makes a second event about the same job a
    # visible defect instead of a quiet inflation.
    Column("ai_job_ref", BigInteger, nullable=False),
    # The operational intake reference, NOT an identity: it is the join the
    # doctor edge resolves against, inside this schema. Actor identity never
    # appears here as a raw reference - only as the two hashes below.
    Column("intake_ref", BigInteger, nullable=False),
    Column("patient_key", String(64), nullable=False),
    # Nullable, not absent: transcription and structuring run before a doctor is
    # involved. A drafting job, which runs after the pick, is where it is set.
    Column("doctor_key", String(64), nullable=True),
    Column("provider", String(30), nullable=False),
    Column("model", String(50), nullable=False),
    Column("task_type", String(30), nullable=False),
    Column("input_tokens", BigInteger, nullable=False, server_default=text("0")),
    Column("output_tokens", BigInteger, nullable=False, server_default=text("0")),
    Column("cost_paise", BigInteger, nullable=False, server_default=text("0")),
    # ``completed`` or ``failed``, and nothing finer: the timeout / plain-failure
    # split lives in ``observability_ai_usage_daily`` and is deliberately NOT
    # duplicated here. Attribution needs completed-vs-failed to divide cost by
    # passes, and duplicating the third bucket would give two tables an answer to
    # the same question to drift apart.
    Column("status", String(20), nullable=False),
    # The cross-tool join key: platform logs, tracing backend and AI backend all
    # carry it, so one identifier reaches all three (decision 41).
    Column("trace_id", String(64), nullable=True),
    # The failed job's operational reason, sanitised and length-capped by the
    # consumer before it is written (#728). The granular per-job grain is what the
    # nightly rollup reads to name the provider's ``last_error``: one row per
    # provider could only hold whatever arrived last, with no ordering to resolve
    # a tie on. NULL on every completed job - there was no failure to describe.
    Column("failure_reason", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("ai_job_ref", name="uq_observability_ai_job_spend_job"),
    Index("ix_observability_ai_job_spend_usage_date", "usage_date"),
    Index("ix_observability_ai_job_spend_patient", "patient_key", "usage_date"),
    Index("ix_observability_ai_job_spend_doctor", "doctor_key", "usage_date"),
)


observability_ai_queue_open = Table(
    "observability_ai_queue_open",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    # The AI job's OWN reference and the grain of the table: one row per job that
    # has ENTERED the pipeline and not yet closed, written from ``ai_job.queued``
    # and deleted by ``ai_job.completed`` / ``ai_job.failed`` (B5, #729). UNIQUE
    # for the same reason ``ai_job_ref`` is unique on the spend table: the row's
    # identity is the job, so a second enqueue event about one job is a visible
    # defect rather than a quietly doubled queue depth.
    #
    # Rows are the OPEN set, not a log. That is what makes depth exactly
    # ``enqueued - completed - failed`` rather than an approximation of it, and it
    # is what lets the age come from the oldest row still here - an oldest-stamp
    # column on an aggregate would have to be un-set by a close that did not happen
    # to be the oldest, which is precisely the stall an age figure must not miss.
    Column("ai_job_ref", BigInteger, nullable=False),
    # The QUEUE the work sits in: one queue per pipeline leg, carrying the
    # producer's closed task-type vocabulary (``transcribe``/``structure``/
    # ``draft``/``summarize``). A second vocabulary is deliberately NOT declared
    # here - MOD-013 cannot import the intake module to reuse its enum, and the
    # leg name is not free-form on the producer side either.
    Column("queue", String(30), nullable=False),
    # The enqueue instant, taken from the envelope's ``occurred_at`` rather than a
    # payload field, so the age figure is read from the same clock the delivery
    # carried.
    Column("enqueued_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("ai_job_ref", name="uq_observability_ai_queue_open_job"),
    Index("ix_observability_ai_queue_open_queue", "queue"),
)


observability_care_attribution_edges = Table(
    "observability_care_attribution_edges",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    # UNIQUE because an intake has exactly one doctor: a re-pick overwrites the
    # edge rather than stacking a second one, so a late or repeated event cannot
    # make one intake look like it was attributed twice.
    Column("intake_ref", BigInteger, nullable=False),
    Column("patient_key", String(64), nullable=False),
    Column("doctor_key", String(64), nullable=False),
    # Provenance: which ``intake.doctor_assigned`` delivery wrote this edge. The
    # consumed-event ledger is what makes that delivery exactly-once; this is the
    # audit trail that says so.
    Column("event_id", PgUUID(as_uuid=True), nullable=False),
    Column("assigned_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("intake_ref", name="uq_observability_care_attribution_edges_intake"),
    Index("ix_observability_care_attribution_edges_doctor", "doctor_key"),
)


observability_attribution_daily = Table(
    "observability_attribution_daily",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    Column("usage_date", Date, nullable=False),
    # ``patient`` or ``doctor`` - the two halves of the attribution the business
    # reads are built on. The key is a one-way hash (domain.pseudonym), so the row
    # groups spend per actor without naming one.
    Column("actor_kind", String(20), nullable=False),
    Column("actor_key", String(64), nullable=False),
    Column("provider", String(30), nullable=False),
    Column("model", String(50), nullable=False),
    Column("task_type", String(30), nullable=False),
    # Every counter here is written in FULL by each rollup pass rather than
    # incremented, which is what makes a late-arriving doctor edge idempotent:
    # the next pass fills the doctor key in without double-counting (decision 6).
    Column("jobs", Integer, nullable=False, server_default=text("0")),
    Column("completed_jobs", Integer, nullable=False, server_default=text("0")),
    Column("failed_jobs", Integer, nullable=False, server_default=text("0")),
    Column("input_tokens", BigInteger, nullable=False, server_default=text("0")),
    Column("output_tokens", BigInteger, nullable=False, server_default=text("0")),
    Column("cost_paise", BigInteger, nullable=False, server_default=text("0")),
    # Nullable and EMPTY today: the PRD defers the revenue model entirely, so the
    # dimension exists and switching monetization on is a data write, not a
    # migration (decision 9). NULL means "not captured" and is deliberately NOT
    # the same as 0, which would mean "captured, and it was nothing" - so a
    # reader can tell an unrevenueed day from a free one without a second column.
    Column("revenue_paise", BigInteger, nullable=True),
    # The monetization tier an actor was on, had a tier existed: NULL for every
    # row today for the same reason revenue is NULL. It lives here, rather than
    # on the per-job source, because it is a property of the actor on the day and
    # is read per actor-day - not per job. #725 is the writer when monetization
    # exists; until then there is deliberately nobody.
    Column("tier_key", String(50), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint(
        "usage_date",
        "actor_kind",
        "actor_key",
        "provider",
        "model",
        "task_type",
        name="uq_observability_attribution_daily_scope",
    ),
    Index("ix_observability_attribution_daily_date_kind", "usage_date", "actor_kind"),
)


observability_error_events = Table(
    "observability_error_events",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    # The collapse key (#717 decision 14), UNIQUE: one row per DISTINCT failure,
    # so a loop of identical 5xx is one entry carrying a count instead of a wall
    # of near-identical rows that bury every other error. Derived only from the
    # STABLE attributes of a failure - never from the trace id or a timestamp,
    # either of which would collapse nothing.
    Column("fingerprint", String(64), nullable=False),
    # The ROUTE TEMPLATE, never the concrete request path (#717 decision 13). A
    # concrete path puts an identifier into telemetry and makes cardinality
    # unbounded; the capture seam is what keeps this column honest, and the
    # runtime round trip is what proves it.
    Column("route_template", String(200), nullable=False),
    Column("method", String(10), nullable=False),
    Column("status_code", Integer, nullable=False),
    # The COLLAPSED class, never the raw code, so 500 and 502 on one route are one
    # series and one entry.
    Column("status_class", String(3), nullable=False),
    # ``unhandled_exception`` or ``server_error_response``: both are captured, so a
    # swallowed exception is not invisible.
    Column("kind", String(30), nullable=False),
    # The envelope's stable, human-safe code - never internal detail
    # (error-handling-observability §1).
    Column("code", String(64), nullable=False, server_default=text("''")),
    # The cross-tool join key (#717 decision 41), carrying the MOST RECENT
    # occurrence's - the one an operator jumping from the feed wants.
    Column("trace_id", String(64), nullable=False),
    Column("occurrences", Integer, nullable=False, server_default=text("1")),
    Column("first_seen_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("last_seen_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("fingerprint", name="uq_observability_error_events_fingerprint"),
    Index("ix_observability_error_events_last_seen", "last_seen_at"),
    Index("ix_observability_error_events_route", "route_template"),
)


observability_http_minute = Table(
    "observability_http_minute",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    # Truncated to the minute in UTC: the grain the table exists for
    # (#717 decision 15) - one row per route per minute, never one write per
    # request.
    Column("minute_ts", DateTime(timezone=True), nullable=False),
    Column("route_template", String(200), nullable=False),
    Column("method", String(10), nullable=False),
    Column("status_class", String(3), nullable=False),
    Column("requests", BigInteger, nullable=False, server_default=text("0")),
    # The 5xx subset of ``requests``, carried alongside so the error rate is a
    # stored numerator over a stored denominator instead of a second scan. #727
    # is the writer; this ticket creates the table it writes.
    Column("errors", BigInteger, nullable=False, server_default=text("0")),
    UniqueConstraint(
        "minute_ts",
        "route_template",
        "method",
        "status_class",
        name="uq_observability_http_minute_scope",
    ),
    Index("ix_observability_http_minute_ts", "minute_ts"),
)


observability_product_events = Table(
    "observability_product_events",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    # UNIQUE because the ledger row's identity IS the event that reported it: a
    # redelivery is already a no-op through the consumed-event ledger, and this
    # makes a second event id about the same occurrence a visible defect rather
    # than a silently doubled funnel step - the rule #723 takes on ``ai_job_ref``.
    Column("event_id", PgUUID(as_uuid=True), nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    # ``patient`` or ``doctor``, both NULLABLE TOGETHER: a step a machine
    # finished has no human behind it, and a placeholder actor there would inflate
    # the active-user count derived from exactly this column.
    Column("actor_kind", String(20), nullable=True),
    # A one-way domain-separated hash of the identity reference
    # (domain.pseudonym.actor_key), never the raw reference.
    Column("actor_key", String(64), nullable=True),
    Column("session_key", String(64), nullable=False),
    # NOT NULL: decision 41 makes the trace id the thing that lets any funnel
    # number be traced back to the real user journey.
    Column("trace_id", String(64), nullable=False),
    # Registry-driven names (#717 decision 23): adding a step is a registry
    # entry, never a migration.
    Column("funnel", String(50), nullable=False),
    Column("step", String(50), nullable=False),
    Column("outcome", String(20), nullable=False),
    Column("duration_ms", Integer, nullable=True),
    UniqueConstraint("event_id", name="uq_observability_product_events_event"),
    Index("ix_observability_product_events_occurred", "occurred_at"),
    Index("ix_observability_product_events_funnel_step", "funnel", "step", "outcome"),
    Index("ix_observability_product_events_actor", "actor_key", "occurred_at"),
    Index("ix_observability_product_events_trace", "trace_id"),
)


observability_product_daily = Table(
    "observability_product_daily",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    Column("event_date", Date, nullable=False),
    Column("funnel", String(50), nullable=False),
    Column("step", String(50), nullable=False),
    Column("outcome", String(20), nullable=False),
    # Recomputed in FULL each pass rather than incremented, which is what makes a
    # late-arriving actor key idempotent - the rule ``attribution_daily`` follows
    # (decision 6).
    Column("events", BigInteger, nullable=False, server_default=text("0")),
    # Distinct pseudonymous actors over the day: the daily-active-user numerator
    # decision 26 derives from the ledger, counted here so a long window never
    # re-counts the raw ledger.
    Column("actor_count", Integer, nullable=False, server_default=text("0")),
    # A SUM and a sample count, NOT a median: a median cannot be derived from a
    # total, and a column that reads like a median because it was computed from an
    # aggregate is how a funnel's thinking time quietly becomes a mean.
    Column("total_duration_ms", BigInteger, nullable=False, server_default=text("0")),
    Column("duration_samples", BigInteger, nullable=False, server_default=text("0")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint(
        "event_date",
        "funnel",
        "step",
        "outcome",
        name="uq_observability_product_daily_scope",
    ),
    Index("ix_observability_product_daily_date_funnel", "event_date", "funnel"),
)


observability_product_actor_daily = Table(
    "observability_product_actor_daily",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    # The SAME UTC day grain ``observability_product_daily`` carries, so the two
    # aggregates describe the same journeys.
    Column("event_date", Date, nullable=False),
    # NOT NULL together, unlike the ledger's nullable pair: this table only ever
    # holds actors a person performed a qualifying clinical action behind, and a row
    # whose kind and key disagree would be counted twice by a reader grouping by
    # kind.
    Column("actor_kind", String(20), nullable=False),
    # A one-way domain-separated hash of the identity reference
    # (domain.pseudonym.actor_key), never the raw reference.
    Column("actor_key", String(64), nullable=False),
    # The actor's qualifying clinical actions that day - the registry's
    # active-actor steps, the set ``/product/active-users`` counts too (#741).
    # Carried for context: no retention figure divides by it, because a retention
    # figure divides by the COHORT SIZE and dividing by one person's activity would
    # be a different metric wearing its name. Recomputed whole each pass, exactly as
    # ``observability_product_daily.events`` is (decision 6).
    Column("events", BigInteger, nullable=False, server_default=text("0")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint(
        "event_date",
        "actor_kind",
        "actor_key",
        name="uq_observability_product_actor_daily_scope",
    ),
    # The cohort read opens on its window's oldest day, so the date leads.
    Index("ix_observability_product_actor_daily_date", "event_date"),
    # Retention asks whether ONE cohort member came back on a later day, which is a
    # lookup by actor across dates rather than by date.
    Index(
        "ix_observability_product_actor_daily_actor",
        "actor_kind",
        "actor_key",
        "event_date",
    ),
)


observability_evaluation_scores = Table(
    "observability_evaluation_scores",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    # The batch date the score belongs to - the same UTC day grain the #750
    # metrics pull and the rollup ledger use, so one scheduled run's rows all
    # share it.
    Column("score_date", Date, nullable=False),
    # 'code' today (the deterministic evaluators); 'human' is reserved for the
    # #752 annotation queue so a person's verdict lands in these same rows
    # without a schema change.
    Column("source", String(10), nullable=False, server_default=text("'code'")),
    # 'ai_job' production telemetry versus 'golden' dataset example: a query
    # that forgets to filter must still be able to tell them apart by kind.
    Column("observation_kind", String(20), nullable=False),
    # Local identity of the observation scored: the ai_job_ref for production
    # rows, the golden example id for dataset rows - never content.
    Column("observation_ref", String(64), nullable=False),
    # The cross-tool join #752's annotation queue matches a human judgement to
    # this technical verdict by. Nullable: a job row without a trace id still
    # gets its local score recorded.
    Column("trace_id", String(64), nullable=True),
    Column("evaluator", String(64), nullable=False),
    # NUMERIC or BOOLEAN only - the aggregation rule decision 40 turns on.
    # Six decimals, the precision the domain's EvaluationScore quantizes to.
    Column("data_type", String(10), nullable=False),
    Column("value", Numeric(12, 6), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    # The nightly idempotency key: re-running a date upserts these rows
    # instead of stacking a second set of scores beside the first.
    UniqueConstraint(
        "score_date",
        "observation_kind",
        "observation_ref",
        "evaluator",
        name="uq_observability_evaluation_scores_key",
    ),
    CheckConstraint(
        "source IN ('code', 'human')",
        name="ck_observability_evaluation_scores_source",
    ),
    CheckConstraint(
        "data_type IN ('NUMERIC', 'BOOLEAN')",
        name="ck_observability_evaluation_scores_data_type",
    ),
    CheckConstraint(
        "data_type <> 'BOOLEAN' OR value IN (0, 1)",
        name="ck_observability_evaluation_scores_boolean_value",
    ),
    # The #752 join opens on trace_id; the day aggregate opens on score_date.
    Index("ix_observability_evaluation_scores_trace", "trace_id"),
    Index("ix_observability_evaluation_scores_date", "score_date"),
)
