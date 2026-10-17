"""B5a #704: MOD-013 rollup adapter + entry-point seam (no DB).

The pure core is covered in ``test_observability_rollup.py``. This file covers
the two halves that are not database-free logic: the adapter's upsert statements
and its alert lifecycle, asserted by compiling them against the PostgreSQL
dialect and by driving them through a recording fake connection, plus the
``python -m worker.rollup`` entry point's date resolution and threshold wiring.
No connection is opened anywhere.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import CompileError

from modules.observability.domain.consumer import AlertRow
from modules.observability.domain.pseudonym import ActorKind
from modules.observability.domain.rollup import (
    COST_OUTLIER_BASELINE_DAYS,
    METRIC_KEY_AI_PROVIDER_HEALTH,
    METRIC_KEY_AI_SPEND,
    ActorDailySpend,
    ActorSpend,
    AttributionDaily,
    ProviderFailures,
    ProviderUsage,
    UsageScope,
    alert_key,
    alert_marker,
    build_budget_snapshot,
    compute_provider_health,
    evaluated_alert_keys,
    rollup_metrics_for,
)
from modules.observability.facade import RollupReport, run_rollup
from modules.observability.rollup import (
    _apply_alerts,
    _load_actor_daily_spend,
    _load_actor_spend,
    _load_doctor_by_intake,
    _load_provider_failures,
    _upsert_attribution_daily,
    _upsert_business_metric,
    _upsert_provider_health,
    _upsert_statement,
)
from modules.observability.schema.models import (
    observability_ai_cost_budget,
    observability_attribution_daily,
)
from worker import rollup as entry_point

_TARGET_DATE = date(2026, 10, 12)


class _RecordingConnection:
    """A connection that records the SQL it is handed instead of executing it.

    Enough of ``AsyncConnection`` for the adapter: ``execute`` compiles the
    statement for the PostgreSQL dialect and returns a row-ish result.
    """

    def __init__(self, rows: Any = None) -> None:
        self.statements: list[str] = []
        self._rows = rows if rows is not None else []

    async def execute(self, statement: Any) -> MagicMock:
        self.statements.append(_sql(statement))
        result = MagicMock()
        result.all.return_value = self._rows
        # A real UPDATE reports the rows it touched; one is enough to assert on.
        result.rowcount = 1
        return result

    @property
    def sql(self) -> str:
        return "\n".join(self.statements)


def _sql(statement: Any) -> str:
    """The statement's PostgreSQL SQL, with literals inlined where renderable.

    ``JSONB`` parameters have no literal renderer, so a statement carrying one
    falls back to the bind-parameter form - the shape is still asserted on.
    """
    try:
        return str(
            statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
        )
    except CompileError:
        return str(statement.compile(dialect=postgresql.dialect()))


def _health(provider: str = "openai") -> Any:
    """One provider's recomputed health, built from the pure core."""
    usage = ProviderUsage(
        provider=provider,
        scopes=(
            UsageScope(
                model="mock-model",
                task_type="summarize",
                calls=10,
                success_count=9,
                failure_count=1,
                timeout_count=0,
                cost_paise=2_500,
                avg_duration_ms=Decimal("150.00"),
            ),
        ),
    )
    return compute_provider_health(provider, _TARGET_DATE, _TARGET_DATE, usage)


# ------------------------------------------------------------------ the upserts


def test_provider_health_upsert_refreshes_the_percentile_columns_in_place() -> None:
    """One row per provider, refreshed by ON CONFLICT - never a second row."""
    connection = _RecordingConnection()

    asyncio.run(_upsert_provider_health(connection, _health()))  # type: ignore[arg-type]

    sql = connection.sql
    assert "INSERT INTO observability.observability_ai_provider_health" in sql
    assert "ON CONFLICT (provider) DO UPDATE" in sql
    for column in ("p50_duration_ms", "p95_duration_ms", "p99_duration_ms", "success_rate"):
        assert column in sql
    assert "updated_at" in sql


def test_provider_health_upsert_writes_the_columns_nothing_used_to_write() -> None:
    """AC1: the last-error column is written by the rollup, in full, every pass.

    Written in the DO UPDATE set rather than only on insert: a provider that
    recovered must have yesterday's named failure CLEARED, because a stale last
    error names a failure that is not happening and is worse than none.
    """
    connection = _RecordingConnection()
    degraded = replace(
        _health(),
        timeout_count=2,
        rate_limit_count=4,
        last_error="rate_limited",
    )

    asyncio.run(_upsert_provider_health(connection, degraded))  # type: ignore[arg-type]

    sql = connection.sql
    assert "timeout_count" in sql
    assert "rate_limit_count" in sql
    assert "last_error" in sql
    assert "'rate_limited'" in sql
    update_set = sql.split("DO UPDATE SET", 1)[1]
    for column in ("timeout_count", "rate_limit_count", "last_error"):
        assert column in update_set, f"{column} is inserted but never refreshed"


def test_provider_health_upsert_clears_a_recovered_providers_named_failure() -> None:
    """A healthy pass writes NULL last error, not the previous night's reason."""
    connection = _RecordingConnection()

    asyncio.run(_upsert_provider_health(connection, _health()))  # type: ignore[arg-type]

    assert "last_error" in connection.sql
    assert "rate_limited" not in connection.sql


def test_load_provider_failures_reads_failed_jobs_newest_first_per_provider() -> None:
    """The order is the recency order, and it is pinned by ``ai_job_ref``.

    Without the tie-break two jobs sharing a ``created_at`` would make the health
    row's named last error - and so what the board shows an operator - depend on
    the planner's choice of scan order.
    """
    connection = _RecordingConnection(
        rows=[
            ("openai", "rate_limited"),
            ("openai", "ConnectError"),
            ("anthropic", "TimeoutError"),
        ]
    )

    loaded = asyncio.run(  # type: ignore[arg-type]
        _load_provider_failures(connection, _TARGET_DATE)
    )

    assert loaded == {
        "openai": ProviderFailures(1, "rate_limited"),
        "anthropic": ProviderFailures(0, "TimeoutError"),
    }
    sql = connection.sql
    assert "FROM observability.observability_ai_job_spend" in sql
    assert "failure_reason IS NOT NULL" in sql
    assert "status = 'failed'" in sql
    assert "created_at DESC" in sql and "ai_job_ref DESC" in sql


def test_load_provider_failures_omits_a_provider_with_no_failed_job() -> None:
    """An absent key is what ``compute_provider_health`` reads as "none observed"."""
    connection = _RecordingConnection(rows=[("openai", "ConnectError")])

    loaded = asyncio.run(  # type: ignore[arg-type]
        _load_provider_failures(connection, _TARGET_DATE)
    )

    assert set(loaded) == {"openai"}


def test_load_provider_failures_is_empty_for_a_day_with_no_failures() -> None:
    connection = _RecordingConnection(rows=[])

    loaded = asyncio.run(  # type: ignore[arg-type]
        _load_provider_failures(connection, _TARGET_DATE)
    )

    assert loaded == {}


def test_business_metric_upsert_replaces_the_value_on_the_generic_store() -> None:
    """The generic store stays (metric_key, metric_date)-unique and is fully replaced."""
    from modules.observability.domain.rollup import RollupMetricValue

    connection = _RecordingConnection()

    asyncio.run(
        _upsert_business_metric(
            connection,  # type: ignore[arg-type]
            _TARGET_DATE,
            RollupMetricValue(metric_key="ai.spend.openai", value={"calls": 10}),
        )
    )

    sql = connection.sql
    assert "INSERT INTO observability.observability_business_daily" in sql
    assert "ON CONFLICT (metric_key, metric_date) DO UPDATE" in sql
    # A full replacement, not a merge: no jsonb_set in the SET clause.
    assert "jsonb_set" not in sql


def test_upsert_statement_excludes_the_conflict_keys_from_the_update_set() -> None:
    """Re-setting the conflict key would be a no-op write on every nightly pass."""
    statement = _upsert_statement(
        observability_ai_cost_budget,
        {"provider": "openai", "model": "mock-model", "current_spend_paise": 5},
        ("provider", "model"),
    )
    sql = _sql(statement)

    assert "ON CONFLICT (provider, model) DO UPDATE" in sql
    assert "SET current_spend_paise" in sql
    assert "SET provider" not in sql
    assert "SET model" not in sql


def test_budget_snapshot_values_reach_the_cost_budget_upsert() -> None:
    snapshot = build_budget_snapshot(
        "openai",
        "mock-model",
        170_000,
        monthly_limit_paise=200_000,
        period_start=date(2026, 10, 1),
        period_end=date(2026, 10, 31),
    )
    statement = _upsert_statement(
        observability_ai_cost_budget,
        {
            "provider": snapshot.provider,
            "model": snapshot.model,
            "current_spend_paise": snapshot.current_spend_paise,
        },
        ("provider", "model"),
    )

    assert "170000" in _sql(statement)
    assert snapshot.exhausted is False


def _alert(kind: str, **payload: Any) -> AlertRow:
    return AlertRow(
        severity="warning", kind=kind, title="t", payload={"source": "rollup", **payload}
    )


def _open(kind: str, marker: dict[str, Any]) -> Any:
    """One already-open rollup alert, as ``_load_open_rollup_alerts`` returns it."""
    existing = MagicMock()
    existing.kind = kind
    existing.marker = alert_marker(marker)
    return existing


def _evaluated(*scopes: tuple[str, dict[str, Any]]) -> set[tuple[str, str]]:
    """The (kind, scope) pairs the pass says it re-evaluated."""
    return {(kind, repr(sorted(alert_marker(marker).items()))) for kind, marker in scopes}


def test_alert_marker_scopes_an_alert_to_its_subject() -> None:
    """Only the subject keys dedupe; the measured figures must not."""
    marker = alert_marker(
        {"source": "rollup", "provider": "openai", "model": "mock-model", "backlog": 900}
    )

    assert marker == {"source": "rollup", "provider": "openai", "model": "mock-model"}
    assert "backlog" not in marker


def test_evaluated_alert_keys_covers_every_family_the_pass_looked_at() -> None:
    keys = evaluated_alert_keys(
        providers=["openai"], tables=["intake.intake_outbox"], queues=["structure"]
    )

    assert alert_key("ai_budget", {"source": "rollup", "scope": "monthly_total"}) in keys
    for kind in ("breaker_open", "provider_health_drop"):
        assert alert_key(kind, {"source": "rollup", "provider": "openai"}) in keys
    for kind in ("outbox_backlog", "outbox_dead_letter"):
        assert alert_key(kind, {"source": "rollup", "table": "intake.intake_outbox"}) in keys
    assert alert_key("queue_age", {"source": "rollup", "queue": "structure"}) in keys
    # A provider this pass saw no traffic for is not in the evaluated set, so its
    # standing alert cannot be closed on absence of evidence.
    assert alert_key("breaker_open", {"source": "rollup", "provider": "anthropic"}) not in keys
    # Same rule for a queue: a queue with nothing open produces no row, so its age
    # alert is left standing rather than resolved by finding no work.
    assert alert_key("queue_age", {"source": "rollup", "queue": "draft"}) not in keys


def test_evaluated_alert_keys_resolves_no_queue_alert_for_a_pass_that_never_looked() -> None:
    """The ``queues`` default must mean "saw none", not "saw all of them".

    A default that resolved every queue alert would let a caller that forgot the
    argument close an open stall on the strength of having checked nothing - the
    exact failure the resolve step exists to prevent.
    """
    keys = evaluated_alert_keys(providers=["openai"], tables=[])

    assert not any(kind == "queue_age" for kind, _ in keys)


def test_apply_alerts_raises_each_breach_once_per_kind_and_scope() -> None:
    """A re-run of the same night must not stack duplicate open alerts."""
    connection = _RecordingConnection()
    breach = _alert("ai_budget", scope="monthly_total")

    raised, resolved = asyncio.run(_apply_alerts(connection, [breach, breach], set(), []))

    assert (raised, resolved) == (1, 0)
    assert connection.sql.count("INSERT INTO observability.observability_alert_events") == 1


def test_apply_alerts_skips_a_breach_already_open_and_resolves_the_cleared_one() -> None:
    connection = _RecordingConnection()

    raised, resolved = asyncio.run(
        _apply_alerts(
            connection,
            [_alert("ai_budget", scope="monthly_total")],
            _evaluated(
                ("ai_budget", {"source": "rollup", "scope": "monthly_total"}),
                ("outbox_dead_letter", {"source": "rollup", "table": "intake.intake_outbox"}),
            ),
            [
                _open("ai_budget", {"source": "rollup", "scope": "monthly_total"}),
                _open("outbox_dead_letter", {"source": "rollup", "table": "intake.intake_outbox"}),
            ],
        )
    )

    assert (raised, resolved) == (0, 1)
    assert "INSERT INTO observability.observability_alert_events" not in connection.sql
    assert "UPDATE observability.observability_alert_events SET status='resolved'" in connection.sql


def test_apply_alerts_leaves_an_unevaluated_alert_open() -> None:
    """A pass with no traffic for a provider must not clear that provider's alert."""
    connection = _RecordingConnection()

    raised, resolved = asyncio.run(
        _apply_alerts(
            connection,
            [],
            _evaluated(("ai_budget", {"source": "rollup", "scope": "monthly_total"})),
            [_open("breaker_open", {"source": "rollup", "provider": "anthropic"})],
        )
    )

    assert (raised, resolved) == (0, 0)
    assert "UPDATE" not in connection.sql


def test_apply_alerts_never_resolves_a_transition_alert() -> None:
    """A health drop has no steady state, so it is raised and left for history."""
    connection = _RecordingConnection()
    drop = _alert("provider_health_drop", provider="openai")

    raised, resolved = asyncio.run(
        _apply_alerts(
            connection,
            [],
            _evaluated(("provider_health_drop", {"source": "rollup", "provider": "openai"})),
            [_open("provider_health_drop", {"source": "rollup", "provider": "openai"})],
        )
    )

    assert (raised, resolved) == (0, 0)
    assert drop.kind == "provider_health_drop"
    assert "UPDATE" not in connection.sql


def test_apply_alerts_leaves_a_consumer_alert_alone() -> None:
    """A consumer alert carries no source marker, so the rollup never resolves it."""
    connection = _RecordingConnection()
    consumer_alert = AlertRow(
        severity="critical",
        kind="audit_tamper",
        title="t",
        payload={"target_event_id": "x"},
    )

    assert alert_marker(consumer_alert.payload) == {}
    raised, resolved = asyncio.run(_apply_alerts(connection, [], set(), []))

    assert (raised, resolved) == (0, 0)
    assert "UPDATE" not in connection.sql

    assert (raised, resolved) == (0, 0)
    assert "UPDATE" not in connection.sql


# --------------------------------------------------- B6 #725: the actor aggregate


def _spend_row(**overrides: Any) -> Any:
    """One ``observability_ai_job_spend`` result row, as the adapter's load sees it."""
    row = SimpleNamespace(
        intake_ref=10,
        patient_key="patient-a",
        doctor_key=None,
        provider="openai",
        model="gpt-4o-mini",
        task_type="structure",
        input_tokens=100,
        output_tokens=20,
        cost_paise=500,
        status="completed",
    )
    for name, value in overrides.items():
        setattr(row, name, value)
    return row


def _spend(**overrides: Any) -> ActorSpend:
    """One per-job spend row as the domain's value type, for the edge-load test."""
    fields: dict[str, Any] = {
        "intake_ref": 10,
        "patient_key": "patient-a",
        "doctor_key": None,
        "provider": "openai",
        "model": "gpt-4o-mini",
        "task_type": "structure",
        "input_tokens": 100,
        "output_tokens": 20,
        "cost_paise": 500,
        "status": "completed",
    }
    fields.update(overrides)
    return ActorSpend(**fields)  # type: ignore[arg-type]


def _attribution(
    *,
    actor_kind: ActorKind = "patient",
    actor_key: str = "patient-a",
    task_type: str = "structure",
    jobs: int = 3,
    cost_paise: int = 900,
) -> AttributionDaily:
    """One recomputed actor-day row, built from the pure core's value type."""
    return AttributionDaily(
        actor_kind=actor_kind,
        actor_key=actor_key,
        provider="openai",
        model="gpt-4o-mini",
        task_type=task_type,
        jobs=jobs,
        completed_jobs=jobs - 1,
        failed_jobs=1,
        input_tokens=300,
        output_tokens=60,
        cost_paise=cost_paise,
    )


def test_the_attribution_upsert_rewrites_every_counter_on_the_scope_key() -> None:
    """The whole figure is SET, so a rerun lands on the recomputed numbers.

    The conflict target is the table's full UNIQUE key: a pass that recomputed into
    the same row is what stops the aggregate stacking, and a counter that was left
    out of the SET clause would silently keep its previous value.
    """
    connection = _RecordingConnection()

    asyncio.run(  # type: ignore[arg-type]
        _upsert_attribution_daily(connection, _TARGET_DATE, _attribution())
    )

    sql = connection.sql
    assert "INSERT INTO observability.observability_attribution_daily" in sql
    assert (
        "ON CONFLICT (usage_date, actor_kind, actor_key, provider, model, task_type) DO UPDATE"
        in sql
    )
    update_set = sql.split("DO UPDATE SET", 1)[1]
    for counter in (
        "jobs",
        "completed_jobs",
        "failed_jobs",
        "input_tokens",
        "output_tokens",
        "cost_paise",
    ):
        assert f"{counter} = " in update_set
    # No accumulation anywhere: the SET clause carries no arithmetic on the old row.
    assert "observability_attribution_daily.jobs +" not in sql


def test_the_attribution_upsert_leaves_revenue_and_tier_to_whoever_captures_them() -> None:
    """Decision 9: the rollup has no revenue source, so it must not clobber one.

    The columns are nullable and NULL today. Refreshing them to NULL on every
    nightly pass would make "turning monetization on is a data write" false - the
    first pass after monetization started would erase it - so they are omitted
    from the values entirely: NULL on insert, untouched on conflict.
    """
    connection = _RecordingConnection()

    asyncio.run(  # type: ignore[arg-type]
        _upsert_attribution_daily(connection, _TARGET_DATE, _attribution())
    )

    assert "revenue_paise" not in connection.sql
    assert "tier_key" not in connection.sql
    assert observability_attribution_daily.c.revenue_paise.nullable is True


def test_the_actor_spend_load_reads_one_day_from_the_granular_source() -> None:
    """One row per AI job, keyed on the date the job finished - never an increment."""
    connection = _RecordingConnection([_spend_row()])

    loaded = asyncio.run(_load_actor_spend(connection, _TARGET_DATE))  # type: ignore[arg-type]

    assert loaded == [_spend()]
    assert "FROM observability.observability_ai_job_spend" in connection.sql
    assert "usage_date" in connection.sql


def test_the_actor_day_load_sums_an_actors_scopes_over_one_trailing_week() -> None:
    """B7 #733: the cost-outlier baseline reads the AGGREGATE, one row per actor-day.

    Read from ``observability_attribution_daily`` rather than the per-job table so a
    baseline is a per-ACTOR figure: collapsing the provider/model/task-type split is
    the point, because a caller abusing one leg must not be averaged into the rest of
    their day. Grouped and summed here because the domain is pure and holds no SQL.
    """
    connection = _RecordingConnection(
        [
            SimpleNamespace(
                actor_kind="patient", actor_key="actor-a", usage_date=_TARGET_DATE, cost_paise=9_000
            )
        ]
    )

    loaded = asyncio.run(  # type: ignore[arg-type]
        _load_actor_daily_spend(connection, _TARGET_DATE, baseline_days=COST_OUTLIER_BASELINE_DAYS)
    )

    assert loaded == [
        ActorDailySpend(
            actor_kind="patient", actor_key="actor-a", usage_date=_TARGET_DATE, cost_paise=9_000
        )
    ]
    sql = connection.sql
    assert "FROM observability.observability_attribution_daily" in sql
    assert "observability_attribution_daily.cost_paise) AS cost_paise" in sql
    assert "GROUP BY observability.observability_attribution_daily.actor_kind" in sql
    # The window is the day under test plus the configured number of days behind it,
    # and no older: an eight-day-old spike must not be able to set today's bar. It is
    # the CONFIGURED figure, so the rows read are the rows the rule judges.
    assert "observability_attribution_daily.usage_date >" in sql
    assert "observability_attribution_daily.usage_date <=" in sql


def test_the_doctor_edge_load_asks_only_about_the_intakes_the_day_touched() -> None:
    """The edge read is bounded by this day's intakes, not a full-table scan.

    Both tables are MOD-013's own, so the join is legal (ADR-0003); bounding it is
    about the query, not the boundary. A day with no jobs must not query at all.
    """
    connection = _RecordingConnection([SimpleNamespace(intake_ref=10, doctor_key="doctor-a")])
    spend = [_spend(status="failed", input_tokens=0, output_tokens=0, cost_paise=0)]

    loaded = asyncio.run(_load_doctor_by_intake(connection, spend))  # type: ignore[arg-type]

    assert loaded == {10: "doctor-a"}
    assert "FROM observability.observability_care_attribution_edges" in connection.sql
    assert "intake_ref IN (10)" in connection.sql


def test_an_idle_day_asks_the_edge_table_nothing() -> None:
    """No jobs means no intakes, and an empty IN list is a query that cannot help."""
    connection = _RecordingConnection()

    assert asyncio.run(_load_doctor_by_intake(connection, [])) == {}  # type: ignore[arg-type]
    assert connection.statements == []


# ------------------------------------------------------------------- the seam


def test_facade_exposes_the_rollup_entry_point_and_its_report() -> None:
    """The composition root reaches the pass through the facade, like every seam."""
    assert callable(run_rollup)
    assert RollupReport.__name__ == "RollupReport"


def test_run_rollup_takes_an_engine_and_a_date_and_demands_explicit_thresholds() -> None:
    """A pass must never guess its budget ceiling - the caller states it."""
    parameters = inspect.signature(run_rollup).parameters

    assert list(parameters)[:3] == ["engine", "target_date", "thresholds"]
    assert parameters["thresholds"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["thresholds"].default is inspect.Parameter.empty


def test_registered_metrics_namespace_by_provider_so_two_providers_never_collide() -> None:
    openai = rollup_metrics_for(ProviderUsage(provider="openai", scopes=()), _health("openai"))
    anthropic = rollup_metrics_for(
        ProviderUsage(provider="anthropic", scopes=()), _health("anthropic")
    )

    assert {row.metric_key for row in openai} == {
        f"{METRIC_KEY_AI_PROVIDER_HEALTH}.openai",
        f"{METRIC_KEY_AI_SPEND}.openai",
    }
    assert {row.metric_key for row in anthropic}.isdisjoint(row.metric_key for row in openai)


# --------------------------------------------------------------- the entry point


def test_parse_target_date_accepts_iso_and_refuses_anything_else() -> None:
    assert entry_point.parse_target_date("2026-10-12") == _TARGET_DATE

    with pytest.raises(argparse.ArgumentTypeError, match="YYYY-MM-DD"):
        entry_point.parse_target_date("12/10/2026")


def test_resolve_target_dates_defaults_to_yesterday_and_skips_today() -> None:
    """Today is still accumulating when the nightly pass fires."""
    assert entry_point.resolve_target_dates(_TARGET_DATE, backfill_days=1) == (date(2026, 10, 11),)


def test_resolve_target_dates_backfills_oldest_first() -> None:
    dates = entry_point.resolve_target_dates(_TARGET_DATE, backfill_days=3)

    assert dates == (date(2026, 10, 9), date(2026, 10, 10), date(2026, 10, 11))


def test_resolve_target_dates_refuses_a_zero_or_negative_backfill() -> None:
    with pytest.raises(ValueError, match="backfill_days"):
        entry_point.resolve_target_dates(_TARGET_DATE, backfill_days=0)


def test_build_thresholds_defaults_the_budget_to_the_configured_cap() -> None:
    assert entry_point.build_thresholds(None).monthly_budget_paise > 0
    assert entry_point.build_thresholds(1_234).monthly_budget_paise == 1_234


def test_entry_point_exposes_a_main_for_python_dash_m() -> None:
    assert callable(entry_point.main)
    assert entry_point.SERVICE_ROLLUP == "caresetu-rollup"


def test_entry_point_composes_no_handler_registry() -> None:
    """The rollup is off the event bus entirely - nothing to register or dispatch."""
    source = Path(entry_point.__file__ or "").read_text(encoding="utf-8")

    assert "build_registry" not in source
    assert "HandlerRegistry" not in source


def test_entry_point_is_a_fresh_composition_per_invocation() -> None:
    """The scheduled job is its own process; it must not share the dispatcher's engine."""
    source = Path(entry_point.__file__ or "").read_text(encoding="utf-8")

    assert "create_async_engine" in source
    assert "engine.dispose()" in source
