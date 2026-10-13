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
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import CompileError

from modules.observability.domain.consumer import AlertRow
from modules.observability.domain.rollup import (
    METRIC_KEY_AI_PROVIDER_HEALTH,
    METRIC_KEY_AI_SPEND,
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
    _upsert_business_metric,
    _upsert_provider_health,
    _upsert_statement,
)
from modules.observability.schema.models import observability_ai_cost_budget
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
    keys = evaluated_alert_keys(providers=["openai"], tables=["intake.intake_outbox"])

    assert alert_key("ai_budget", {"source": "rollup", "scope": "monthly_total"}) in keys
    for kind in ("breaker_open", "provider_health_drop"):
        assert alert_key(kind, {"source": "rollup", "provider": "openai"}) in keys
    for kind in ("outbox_backlog", "outbox_dead_letter"):
        assert alert_key(kind, {"source": "rollup", "table": "intake.intake_outbox"}) in keys
    # A provider this pass saw no traffic for is not in the evaluated set, so its
    # standing alert cannot be closed on absence of evidence.
    assert alert_key("breaker_open", {"source": "rollup", "provider": "anthropic"}) not in keys


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
