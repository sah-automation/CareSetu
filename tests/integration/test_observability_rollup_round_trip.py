"""B5a #704: the MOD-013 nightly rollup against real PostgreSQL.

Seeds ``observability_ai_usage_daily`` exactly as the B4a consumer leaves it
(per ``(date, provider, model, task_type)`` scopes with counters, cost and a
running mean), parks a dead-letter row in an outbox table, and runs the pass for
that date. Asserts the three writes the ticket names: ``observability_ai_provider_health``
refreshed with the recomputed percentiles and breaker state,
``observability_ai_cost_budget`` snapshotted, and the threshold alerts in
``observability_alert_events`` - plus that re-running the same date is a no-op
that neither duplicates the alerts nor stacks the aggregates.

Requires the native PostgreSQL; the suite skips cleanly when it is unreachable.
The shared integration conftest migrates to head once per file, empties the
observability aggregates and the outboxes before each test, and downgrades
afterwards.

The B5b (#705) half at the bottom drives the SCHEDULE: the first-run backfill over
seeded AI-job history, the previous-day pass after it, a re-run's idempotency, a
missed night's catch-up, and the calendar-month budget-period reset - each against
the ``observability_rollup_runs`` ledger the plan is read from.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from modules.observability.domain.pseudonym import (
    ACTOR_KIND_DOCTOR,
    ACTOR_KIND_PATIENT,
    actor_key,
)
from modules.observability.domain.rollup import (
    ALERT_KIND_AI_BUDGET,
    ALERT_KIND_OUTBOX_DEAD_LETTER,
    ALERT_KIND_PROVIDER_HEALTH_DROP,
    ALERT_KIND_QUEUE_AGE,
    DEFAULT_QUEUE_AGE_ALERT_THRESHOLD_SECONDS,
    METRIC_KEY_AI_PROVIDER_HEALTH,
    METRIC_KEY_AI_SPEND,
    ROLLUP_MODE_BACKFILL,
    ROLLUP_MODE_DAILY,
    RollupThresholds,
    plan_rollup_dates,
)
from modules.observability.facade import load_rollup_state, run_rollup
from worker.rollup import plan_from_state, resolve_dates

_TARGET_DATE = date(2026, 10, 12)
_PERIOD_START = date(2026, 10, 1)
_PERIOD_END = date(2026, 10, 31)
#: A budget the seeded spend breaches past the default 80% threshold.
_THRESHOLDS = RollupThresholds(monthly_budget_paise=100_000)


async def _seed_usage(connection: AsyncConnection) -> None:
    """Three scopes across two providers on the target date, as B4a accumulates them.

    ``openai`` is 3/4 successful across two task scopes with different means, so
    the recomputed percentiles must rank the weighted sample rather than average
    the two means. ``anthropic`` is a clean 4/4. The ``openai`` rows cost 85,000
    paise month-to-date, past 80% of the seeded 100,000 paise budget.
    """
    await connection.execute(
        text(
            "INSERT INTO observability.observability_ai_usage_daily "
            "(usage_date, provider, model, task_type, calls, success_count, "
            "failure_count, timeout_count, input_tokens, output_tokens, cost_paise, "
            "avg_duration_ms, p95_duration_ms) VALUES "
            "(:day, 'openai', 'gpt-4o-mini', 'structure', 3, 3, 0, 0, 10, 20, 25000, "
            " 100.00, NULL), "
            "(:day, 'openai', 'gpt-4o-mini', 'summarize', 1, 0, 1, 0, 0, 0, 60000, NULL, NULL), "
            "(:day, 'openai', 'gpt-4o-mini', 'suggest', 1, 1, 0, 0, 5, 5, 30000, "
            " 400.00, NULL), "
            "(:day, 'anthropic', 'claude-haiku', 'structure', 4, 4, 0, 0, 12, 8, 5000, "
            " 250.00, NULL)"
        ),
        {"day": _TARGET_DATE},
    )


async def _seed_dead_letter(connection: AsyncConnection) -> None:
    """One terminal dead-letter row in the intake outbox, as a poisoned event leaves."""
    await connection.execute(
        text(
            "INSERT INTO intake.intake_outbox "
            "(event_id, event_type, payload, occurred_at, status, attempts) "
            "VALUES (:event_id, 'intake.ai_job_completed', '{}'::jsonb, now(), "
            " 'dead_letter', 5)"
        ),
        {"event_id": uuid4()},
    )


async def _seed_open_queue(
    connection: AsyncConnection,
    *,
    age_seconds: int,
    queue: str = "structure",
    ai_job_ref: int = 4242,
) -> None:
    """One still-open AI job, enqueued ``age_seconds`` ago, as a stalled leg leaves.

    Seeded by inserting the row the ``ai_job.queued`` handler would have written, so
    the pass is exercised against the real table rather than a stub of it. The age
    is anchored to the clock, because the alert compares the oldest open row's age
    against the threshold AT THE MOMENT the pass runs.
    """
    await connection.execute(
        text(
            "INSERT INTO observability.observability_ai_queue_open "
            "(ai_job_ref, queue, enqueued_at) VALUES "
            "(:ref, :queue, now() - make_interval(secs => :age))"
        ),
        {"ref": ai_job_ref, "queue": queue, "age": age_seconds},
    )


async def _open_queue_rows(connection: AsyncConnection) -> list[Any]:
    result = await connection.execute(
        text(
            "SELECT ai_job_ref, queue, enqueued_at FROM "
            "observability.observability_ai_queue_open ORDER BY ai_job_ref"
        )
    )
    return list(result.mappings().all())


async def _seed_previous_health(connection: AsyncConnection) -> None:
    """A previous pass recorded a perfect success rate, so a drop is measurable."""
    await connection.execute(
        text(
            "INSERT INTO observability.observability_ai_provider_health "
            "(provider, sample_count, success_rate, breaker_state) "
            "VALUES ('openai', 10, 1.0000, 'closed')"
        )
    )


async def _health_row(connection: AsyncConnection, provider: str) -> Any:
    result = await connection.execute(
        text(
            "SELECT sample_count, success_rate, p50_duration_ms, p95_duration_ms, "
            "p99_duration_ms, breaker_state, timeout_count, rate_limit_count, last_error "
            "FROM observability.observability_ai_provider_health WHERE provider = :provider"
        ),
        {"provider": provider},
    )
    return result.mappings().one()


async def _budget_row(connection: AsyncConnection) -> Any:
    result = await connection.execute(
        text(
            "SELECT monthly_limit_paise, alert_threshold_pct, current_spend_paise, "
            "billing_period_start, billing_period_end FROM "
            "observability.observability_ai_cost_budget "
            "WHERE provider = 'openai' AND model = 'gpt-4o-mini'"
        )
    )
    return result.mappings().one()


async def _alert_rows(connection: AsyncConnection) -> list[Any]:
    result = await connection.execute(
        text(
            "SELECT kind, status, severity, payload FROM "
            "observability.observability_alert_events ORDER BY kind"
        )
    )
    return list(result.all())


async def _open_alert_kinds(connection: AsyncConnection) -> list[str]:
    return [row.kind for row in await _alert_rows(connection) if row.status == "open"]


async def _open_alert_count(engine: AsyncEngine) -> int:
    async with engine.connect() as connection:
        return len(await _open_alert_kinds(connection))


async def _metric_value(
    connection: AsyncConnection, metric_key: str, day: date = _TARGET_DATE
) -> Any:
    """The generic-store JSON value for one metric, or ``None`` when unwritten."""
    result = await connection.execute(
        text(
            "SELECT value FROM observability.observability_business_daily "
            "WHERE metric_key = :metric_key AND metric_date = :day"
        ),
        {"metric_key": metric_key, "day": day},
    )
    row = result.mappings().first()
    return None if row is None else row["value"]


async def _run_rows(connection: AsyncConnection) -> list[Any]:
    result = await connection.execute(
        text(
            "SELECT rollup_date, mode, billing_period_start, health_rows, alerts_raised "
            "FROM observability.observability_rollup_runs ORDER BY rollup_date"
        )
    )
    return list(result.mappings().all())


async def _run_row_count(engine: AsyncEngine) -> int:
    async with engine.connect() as connection:
        return len(await _run_rows(connection))


# ------------------------------------------ B9 #728: naming the provider failure


def _at_hour(hour: int) -> datetime:
    """An aware instant on the target date, for seeding a per-job ``created_at``."""
    return datetime.combine(_TARGET_DATE, time(hour), tzinfo=UTC)


async def _seed_failed_jobs(connection: AsyncConnection) -> None:
    """Three failed jobs on the target date, as #723's consumer leaves them.

    Jobs 9002 and 9004 were refused for quota and job 9003 dropped its connection,
    so the newest failure is the connection drop and the quota count is two. The
    rows carry their own ``created_at`` so "most recent" is a fact about the seed
    rather than about insertion order - the quota refusals are inserted first and
    last, so insertion order would pick the wrong one.
    """
    await connection.execute(
        text(
            "INSERT INTO observability.observability_ai_job_spend "
            "(usage_date, ai_job_ref, intake_ref, patient_key, doctor_key, provider, "
            "model, task_type, input_tokens, output_tokens, cost_paise, status, "
            "failure_reason, created_at) VALUES "
            "(:day, 9002, 502, :patient_one, NULL, 'openai', 'gpt-4o-mini', "
            " 'summarize', 0, 0, 0, 'failed', 'rate_limited', :first), "
            "(:day, 9003, 503, :patient_one, NULL, 'openai', 'gpt-4o-mini', "
            " 'summarize', 0, 0, 0, 'failed', 'ConnectError', :last), "
            "(:day, 9004, 504, :patient_one, NULL, 'openai', 'gpt-4o-mini', "
            " 'summarize', 0, 0, 0, 'failed', 'rate_limited', :middle)"
        ),
        {
            "day": _TARGET_DATE,
            "patient_one": _PATIENT_ONE,
            "first": _at_hour(1),
            "middle": _at_hour(2),
            "last": _at_hour(3),
        },
    )


async def _seed_completed_job_with_reason(connection: AsyncConnection, *, ai_job_ref: int) -> None:
    """A COMPLETED job that nonetheless carries a reason, as a bad write would.

    The loader must ignore it: the board names the newest FAILURE, and counting a
    completed job's leftover reason would report a throttle for a call that
    succeeded.
    """
    await connection.execute(
        text(
            "INSERT INTO observability.observability_ai_job_spend "
            "(usage_date, ai_job_ref, intake_ref, patient_key, provider, model, "
            "task_type, input_tokens, output_tokens, cost_paise, status, failure_reason, "
            " created_at) VALUES "
            "(:day, :ref, 505, :patient_one, 'openai', 'gpt-4o-mini', 'summarize', "
            " 10, 20, 500, 'completed', 'rate_limited', :late)"
        ),
        {
            "day": _TARGET_DATE,
            "ref": ai_job_ref,
            "patient_one": _PATIENT_ONE,
            "late": _at_hour(4),
        },
    )


@pytest.mark.asyncio
async def test_the_rollup_writes_the_last_error_nothing_used_to_write(
    engine: AsyncEngine,
) -> None:
    """AC1: a degraded provider can be NAMED rather than inferred from its counters."""
    async with engine.begin() as connection:
        await _seed_usage(connection)
        await _seed_failed_jobs(connection)

    await run_rollup(engine, _TARGET_DATE, thresholds=_THRESHOLDS)

    async with engine.connect() as connection:
        openai = await _health_row(connection, "openai")
        # The newest failure was a dropped connection, so that is what is named -
        # not either of the two quota refusals, which happened earlier in the day.
        assert openai["last_error"] == "ConnectError"
        assert openai["rate_limit_count"] == 2
        # The timeouts come from the day's own usage scopes, not from the failures.
        assert openai["timeout_count"] == 0
        # A provider whose jobs all completed has no failure to name.
        assert (await _health_row(connection, "anthropic"))["last_error"] is None
        assert (await _health_row(connection, "anthropic"))["rate_limit_count"] == 0


@pytest.mark.asyncio
async def test_the_rollup_names_the_newest_failure_by_its_timestamp_not_its_insert(
    engine: AsyncEngine,
) -> None:
    """Two jobs sharing a ``created_at`` are ordered by their job reference.

    Without the tie-break the named last error would depend on the planner's
    choice of scan order, so the same seeded day could name either failure.
    """
    async with engine.begin() as connection:
        await _seed_usage(connection)
        await connection.execute(
            text(
                "INSERT INTO observability.observability_ai_job_spend "
                "(usage_date, ai_job_ref, intake_ref, patient_key, provider, model, "
                "task_type, input_tokens, output_tokens, cost_paise, status, "
                "failure_reason, created_at) VALUES "
                "(:day, 9101, 601, :patient_one, 'openai', 'gpt-4o-mini', 'summarize', "
                " 0, 0, 0, 'failed', 'OlderFailure', :same), "
                "(:day, 9102, 602, :patient_one, 'openai', 'gpt-4o-mini', 'summarize', "
                " 0, 0, 0, 'failed', 'NewerFailure', :same)"
            ),
            {
                "day": _TARGET_DATE,
                "patient_one": _PATIENT_ONE,
                "same": _at_hour(5),
            },
        )

    await run_rollup(engine, _TARGET_DATE, thresholds=_THRESHOLDS)

    async with engine.connect() as connection:
        # 9102 > 9101, so the higher job reference wins the tie.
        assert (await _health_row(connection, "openai"))["last_error"] == "NewerFailure"


@pytest.mark.asyncio
async def test_the_rollup_names_a_failed_job_not_a_completed_one_that_carries_a_reason(
    engine: AsyncEngine,
) -> None:
    """The newest reason is the newest FAILURE's, whatever row happens to be newer."""
    async with engine.begin() as connection:
        await _seed_usage(connection)
        await _seed_failed_jobs(connection)
        await _seed_completed_job_with_reason(connection, ai_job_ref=9999)

    await run_rollup(engine, _TARGET_DATE, thresholds=_THRESHOLDS)

    async with engine.connect() as connection:
        openai = await _health_row(connection, "openai")
        # The completed job is the newest row by a wide margin and is still ignored.
        assert openai["last_error"] == "ConnectError"
        assert openai["rate_limit_count"] == 2


@pytest.mark.asyncio
async def test_a_recovered_provider_has_its_named_failure_cleared(engine: AsyncEngine) -> None:
    """A stale last error is worse than none: it names a failure that is not happening.

    Written in FULL on every pass, so the second pass - which sees a provider with
    no failures at all - blanks the column rather than leaving yesterday's reason
    under a healthy status.
    """
    async with engine.begin() as connection:
        await _seed_usage(connection)
        await _seed_failed_jobs(connection)
    await run_rollup(engine, _TARGET_DATE, thresholds=_THRESHOLDS)

    async with engine.connect() as connection:
        assert (await _health_row(connection, "openai"))["last_error"] == "ConnectError"

    # The next night's pass rolls a day whose openai traffic all succeeded, with no
    # failed job to name.
    recovered = _TARGET_DATE + timedelta(days=1)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO observability.observability_ai_usage_daily "
                "(usage_date, provider, model, task_type, calls, success_count, "
                "failure_count, timeout_count, input_tokens, output_tokens, cost_paise, "
                "avg_duration_ms) VALUES "
                "(:day, 'openai', 'gpt-4o-mini', 'structure', 4, 4, 0, 0, 10, 20, 1000, "
                "  120.00)"
            ),
            {"day": recovered},
        )
    await run_rollup(engine, recovered, thresholds=_THRESHOLDS)

    async with engine.connect() as connection:
        openai = await _health_row(connection, "openai")
        assert openai["last_error"] is None
        assert openai["rate_limit_count"] == 0
        assert openai["timeout_count"] == 0
        assert openai["success_rate"] == Decimal("1.0000")


@pytest.mark.asyncio
async def test_the_provider_health_row_stores_no_status_column(engine: AsyncEngine) -> None:
    """AC: healthy/degraded/down is DERIVED, not stored (#717 decision 18).

    Asserted against the real table because the claim is about the schema: a
    stored status would be a second source of truth the nightly recompute could
    leave contradicting the counters it was derived from.
    """
    async with engine.begin() as connection:
        await _seed_usage(connection)
    await run_rollup(engine, _TARGET_DATE, thresholds=_THRESHOLDS)

    async with engine.connect() as connection:
        result = await connection.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'observability' "
                "AND table_name = 'observability_ai_provider_health'"
            )
        )
        stored = {row[0] for row in result.all()}

    assert not {"status", "health_status", "provider_status"} & stored
    # The two columns #728 added ARE there, which is what the assertion above guards.
    assert {"last_error", "timeout_count", "rate_limit_count"} <= stored


@pytest.mark.asyncio
async def test_a_rolled_day_with_no_failures_writes_no_name_and_no_count(
    engine: AsyncEngine,
) -> None:
    """The pre-#728 behaviour survives as an honest zero/NULL, not a failure."""
    async with engine.begin() as connection:
        await _seed_usage(connection)
        await _seed_actor_spend(connection)

    await run_rollup(engine, _TARGET_DATE, thresholds=_THRESHOLDS)

    async with engine.connect() as connection:
        openai = await _health_row(connection, "openai")
        assert openai["last_error"] is None
        assert openai["rate_limit_count"] == 0
        # anthropic has no per-job rows at all, so it is absent from the load map
        # entirely rather than being counted as a provider with zero failures.
        assert (await _health_row(connection, "anthropic"))["last_error"] is None


# ------------------------------------------ B6 #725: the daily per-actor aggregate

#: The 64-char hex the domain's ``actor_key`` produces for each of these refs, so
#: the assertions name the same pseudonyms the consumer writes rather than
#: re-deriving a second hashing convention in the test.
_PATIENT_ONE = actor_key(ACTOR_KIND_PATIENT, 101)
_PATIENT_TWO = actor_key(ACTOR_KIND_PATIENT, 102)
_DOCTOR_ONE = actor_key(ACTOR_KIND_DOCTOR, 201)
_DOCTOR_TWO = actor_key(ACTOR_KIND_DOCTOR, 202)

#: Every column the aggregate is read back through, minus the two maintenance
#: timestamps. Compared as a whole so an accidental per-unit column cannot be added
#: without this failing.
_ATTRIBUTION_COLUMNS = (
    "id",
    "usage_date",
    "actor_kind",
    "actor_key",
    "provider",
    "model",
    "task_type",
    "jobs",
    "completed_jobs",
    "failed_jobs",
    "input_tokens",
    "output_tokens",
    "cost_paise",
    "revenue_paise",
    "tier_key",
    "created_at",
    "updated_at",
)


async def _seed_actor_spend(connection: AsyncConnection) -> None:
    """Four per-job spend rows on the target date, as #723's consumer leaves them.

    Intake 501 belongs to patient 101 and is transcribed BEFORE any doctor pick, so
    its doctor key is NULL - the late-attribution case. Intake 502 is a second job
    for the same patient on a different task type. Intake 503 is patient 102's, and
    its drafting job carries its own doctor key because a pick had already happened.
    One job (504) failed, recording the attempt at zero tokens and zero paise.
    """
    await connection.execute(
        text(
            "INSERT INTO observability.observability_ai_job_spend "
            "(usage_date, ai_job_ref, intake_ref, patient_key, doctor_key, provider, "
            "model, task_type, input_tokens, output_tokens, cost_paise, status) VALUES "
            "(:day, 9001, 501, :patient_one, NULL, 'openai', 'gpt-4o-mini', "
            " 'transcribe', 1000, 200, 4_500, 'completed'), "
            "(:day, 9002, 502, :patient_one, NULL, 'openai', 'gpt-4o-mini', "
            " 'structure', 300, 60, 1_200, 'completed'), "
            "(:day, 9003, 503, :patient_two, :doctor_one, 'anthropic', 'claude-haiku', "
            " 'draft', 800, 400, 9_000, 'completed'), "
            "(:day, 9004, 504, :patient_two, :doctor_one, 'anthropic', 'claude-haiku', "
            " 'draft', 0, 0, 0, 'failed')"
        ),
        {
            "day": _TARGET_DATE,
            "patient_one": _PATIENT_ONE,
            "patient_two": _PATIENT_TWO,
            "doctor_one": _DOCTOR_ONE,
        },
    )


async def _seed_care_edge(
    connection: AsyncConnection, *, intake_ref: int, patient_key: str, doctor_key: str
) -> None:
    """One ``intake.doctor_assigned`` edge, as #724's consumer records it."""
    await connection.execute(
        text(
            "INSERT INTO observability.observability_care_attribution_edges "
            "(intake_ref, patient_key, doctor_key, event_id, assigned_at) "
            "VALUES (:intake_ref, :patient_key, :doctor_key, :event_id, now())"
        ),
        {
            "intake_ref": intake_ref,
            "patient_key": patient_key,
            "doctor_key": doctor_key,
            "event_id": uuid4(),
        },
    )


async def _seed_every_doctor_edge(connection: AsyncConnection) -> None:
    """A pick for all three intakes, so every job is attributed to a doctor."""
    await _seed_care_edge(
        connection, intake_ref=501, patient_key=_PATIENT_ONE, doctor_key=_DOCTOR_ONE
    )
    await _seed_care_edge(
        connection, intake_ref=502, patient_key=_PATIENT_ONE, doctor_key=_DOCTOR_ONE
    )
    await _seed_care_edge(
        connection, intake_ref=503, patient_key=_PATIENT_TWO, doctor_key=_DOCTOR_ONE
    )


async def _attribution_rows(
    connection: AsyncConnection, *, actor_kind: str | None = None
) -> list[Any]:
    """The actor aggregate as a plain dict per row, ordered so a rerun compares.

    Every column is read INCLUDING ``id`` and ``created_at`` and EXCLUDING only
    ``updated_at`` - the one column a recompute deliberately advances, because it
    is the pass's own audit stamp and says when this scope was last re-derived.
    Everything an operator reads a number from is therefore comparable.
    """
    where = "WHERE actor_kind = :actor_kind" if actor_kind is not None else ""
    result = await connection.execute(
        text(
            "SELECT id, created_at, usage_date, actor_kind, actor_key, provider, model, "
            "task_type, jobs, completed_jobs, failed_jobs, input_tokens, output_tokens, "
            f"cost_paise, revenue_paise, tier_key "
            f"FROM observability.observability_attribution_daily "
            f"{where} ORDER BY actor_kind, actor_key, provider, model, task_type"
        ),
        {"actor_kind": actor_kind} if actor_kind is not None else {},
    )
    return [dict(row) for row in result.mappings().all()]


async def _attribution_updated_at(connection: AsyncConnection) -> list[Any]:
    """The aggregate's one moving column, so a rerun's audit stamp can be asserted."""
    result = await connection.execute(
        text(
            "SELECT updated_at FROM observability.observability_attribution_daily "
            "ORDER BY actor_kind, actor_key, provider, model, task_type"
        )
    )
    return [row[0] for row in result.all()]


async def _attribution_row(
    connection: AsyncConnection, *, actor_kind: str, actor_key: str, task_type: str
) -> Any:
    result = await connection.execute(
        text(
            "SELECT jobs, completed_jobs, failed_jobs, input_tokens, output_tokens, "
            "cost_paise, revenue_paise, tier_key FROM "
            "observability.observability_attribution_daily "
            "WHERE actor_kind = :actor_kind AND actor_key = :actor_key "
            "AND task_type = :task_type"
        ),
        {"actor_kind": actor_kind, "actor_key": actor_key, "task_type": task_type},
    )
    return result.mappings().one()


@pytest.mark.asyncio
async def test_the_rollup_derives_a_daily_actor_aggregate_recomputed_from_the_jobs(
    engine: AsyncEngine,
) -> None:
    """The acceptance criterion: per-patient and per-doctor spend, summed not merged."""
    async with engine.begin() as connection:
        await _seed_actor_spend(connection)
        await _seed_every_doctor_edge(connection)

    report = await run_rollup(engine, _TARGET_DATE, thresholds=_THRESHOLDS)

    # Three patient rows (one per task type) and three doctor rows.
    assert report.attribution_rows == 6

    async with engine.connect() as connection:
        patients = await _attribution_rows(connection, actor_kind="patient")
        # Patient 101 paid 5,700 paise across two task types; nothing is summed
        # across them, so the task-type breakdown stays a plain group-by.
        assert {(row["actor_key"], row["task_type"], row["cost_paise"]) for row in patients} == {
            (_PATIENT_ONE, "structure", 1_200),
            (_PATIENT_ONE, "transcribe", 4_500),
            (_PATIENT_TWO, "draft", 9_000),
        }
        # Patient 102's failed job is counted as attempted and never as spend.
        failed_leg = next(row for row in patients if row["actor_key"] == _PATIENT_TWO)
        assert (failed_leg["jobs"], failed_leg["completed_jobs"], failed_leg["failed_jobs"]) == (
            2,
            1,
            1,
        )

        # One rupee of spend is recorded against the patient who paid and the doctor
        # whose case it served, so the two sides reconcile exactly.
        doctors = await _attribution_rows(connection, actor_kind="doctor")
        assert (
            sum(row["cost_paise"] for row in doctors)
            == sum(row["cost_paise"] for row in patients)
            == 14_700
        )


@pytest.mark.asyncio
async def test_a_care_edge_that_lands_after_its_job_fills_the_doctor_in_with_no_double_count(
    engine: AsyncEngine,
) -> None:
    """The late-arriving attribution edge, which is what "recomputed, not accumulated" buys.

    The transcription job is metered while the patient has no doctor yet, so the
    first pass can only produce the patient row - a gap an operator can see, not a
    doctor key invented to fill it. The pick then lands, and the next pass for the
    SAME date adds the doctor while the patient's figure comes back unchanged. An
    incrementing rollup could not do this without counting the day twice.
    """
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO observability.observability_ai_job_spend "
                "(usage_date, ai_job_ref, intake_ref, patient_key, doctor_key, provider, "
                "model, task_type, input_tokens, output_tokens, cost_paise, status) VALUES "
                "(:day, 9001, 501, :patient, NULL, 'openai', 'gpt-4o-mini', "
                " 'transcribe', 1000, 200, 4500, 'completed')"
            ),
            {"day": _TARGET_DATE, "patient": _PATIENT_ONE},
        )

    first = await run_rollup(engine, _TARGET_DATE, thresholds=_THRESHOLDS)

    async with engine.connect() as connection:
        assert first.attribution_rows == 1
        before = await _attribution_rows(connection)
        assert [row["actor_kind"] for row in before] == ["patient"]

    # The patient picks a doctor some time after the job finished.
    async with engine.begin() as connection:
        await _seed_care_edge(
            connection, intake_ref=501, patient_key=_PATIENT_ONE, doctor_key=_DOCTOR_ONE
        )

    second = await run_rollup(engine, _TARGET_DATE, thresholds=_THRESHOLDS)

    assert second.attribution_rows == 2

    async with engine.connect() as connection:
        after = await _attribution_rows(connection)
        assert [(row["actor_kind"], row["actor_key"], row["cost_paise"]) for row in after] == [
            ("doctor", _DOCTOR_ONE, 4_500),
            ("patient", _PATIENT_ONE, 4_500),
        ]
        # The patient row is byte-identical to the first pass: the day was recomputed,
        # not added to, so the patient's spend did not double.
        assert next(row for row in after if row["actor_kind"] == "patient") == before[0]


@pytest.mark.asyncio
async def test_rolling_the_same_date_twice_leaves_identical_aggregate_rows(
    engine: AsyncEngine,
) -> None:
    """A retried nightly job converges: the same rows, the same figures, one row each.

    The strong form of idempotency: the same ROWS, carrying the same primary key
    and the same ``created_at``, with every figure identical - not merely the same
    totals. A recompute-in-full that inserted a second row per scope, or rebuilt a
    row from scratch, would show up here.
    """
    async with engine.begin() as connection:
        await _seed_actor_spend(connection)
        await _seed_every_doctor_edge(connection)

    first = await run_rollup(engine, _TARGET_DATE, thresholds=_THRESHOLDS)
    async with engine.connect() as connection:
        after_first = await _attribution_rows(connection)
        stamped_first = await _attribution_updated_at(connection)

    second = await run_rollup(engine, _TARGET_DATE, thresholds=_THRESHOLDS)
    async with engine.connect() as connection:
        after_second = await _attribution_rows(connection)
        stamped_second = await _attribution_updated_at(connection)

    assert second.attribution_rows == first.attribution_rows == 6
    assert after_second == after_first
    # ``updated_at`` is the single deliberate exception: it is the pass's own audit
    # stamp, and refreshing it is how an operator tells "re-derived last night" from
    # "never rolled". Every other column is byte-identical.
    assert stamped_second and all(
        new >= old for new, old in zip(stamped_second, stamped_first, strict=True)
    )


@pytest.mark.asyncio
async def test_the_daily_actor_aggregate_ships_with_revenue_and_tier_empty(
    engine: AsyncEngine,
) -> None:
    """Decision 9: the monetization dimensions are present and NULL, not zero.

    NULL reads as "not captured"; a 0 would read as "captured, and it was nothing",
    which is how an unrevenueed day would get mistaken for a free one. The columns
    are asserted here rather than in a unit test because this is the whole claim:
    a nightly pass leaves them empty, so turning monetization on is a data write.
    """
    async with engine.begin() as connection:
        await _seed_actor_spend(connection)
        await _seed_every_doctor_edge(connection)

    await run_rollup(engine, _TARGET_DATE, thresholds=_THRESHOLDS)

    async with engine.connect() as connection:
        rows = await _attribution_rows(connection)
        assert rows
        for row in rows:
            assert row["revenue_paise"] is None
            assert row["tier_key"] is None


@pytest.mark.asyncio
async def test_the_actor_aggregate_stores_counters_and_no_derived_figure(
    engine: AsyncEngine,
) -> None:
    """Decision 8, against the real table: cost per thousand tokens and friends stay derived."""
    async with engine.begin() as connection:
        await _seed_actor_spend(connection)
        await _seed_every_doctor_edge(connection)
    await run_rollup(engine, _TARGET_DATE, thresholds=_THRESHOLDS)

    async with engine.connect() as connection:
        result = await connection.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'observability' "
                "AND table_name = 'observability_attribution_daily'"
            )
        )
        stored = {row[0] for row in result.all()}

    assert stored == set(_ATTRIBUTION_COLUMNS)
    assert (
        not {
            "cost_per_thousand_input_tokens",
            "cost_per_thousand_output_tokens",
            "cost_per_request",
            "cost_per_completed_task",
            "cost_per_patient",
            "cost_per_doctor",
            "cost_of_pass",
            "gross_margin",
        }
        & stored
    )


@pytest.mark.asyncio
async def test_a_recompute_of_an_already_rolled_date_is_reachable_from_the_entry_point(
    engine: AsyncEngine,
) -> None:
    """How a rerun-for-a-date is ASKED FOR, driven through the real operator path.

    The run ledger is a coverage marker: once it is current the planner plans
    nothing, which is correct and would otherwise make a recompute unreachable -
    and the whole late-attribution story depends on being able to re-derive a day
    that has already been rolled. The existing ``--date`` override is that path, and
    this asserts it end to end rather than trusting the docstring: the override
    names the date, the pass re-derives it, and the ledger still holds one row.
    """
    async with engine.begin() as connection:
        await _seed_actor_spend(connection)
    await run_rollup(engine, _TARGET_DATE, thresholds=_THRESHOLDS)

    # The scheduled planner is now current and plans nothing - the correct no-op.
    assert (await plan_from_state(engine, _TARGET_DATE + timedelta(days=1))).dates == ()

    # The operator asks for that same date by hand, through the same seam the CLI uses.
    rerun = resolve_dates(_TARGET_DATE + timedelta(days=1), target_date=_TARGET_DATE)
    assert rerun is not None
    assert rerun.dates == (_TARGET_DATE,)
    # It is recorded as the daily shape, so the ledger's mode column stays honest.
    assert rerun.mode == ROLLUP_MODE_DAILY

    async with engine.begin() as connection:
        await _seed_every_doctor_edge(connection)
    for target in rerun.dates:
        await run_rollup(engine, target, thresholds=_THRESHOLDS, mode=rerun.mode)

    async with engine.connect() as connection:
        # The re-derivation filled the doctors in, and the ledger is still one row.
        assert len(await _attribution_rows(connection, actor_kind="doctor")) == 3
    assert await _run_row_count(engine) == 1


@pytest.mark.asyncio
async def test_a_monetization_write_survives_a_recompute(engine: AsyncEngine) -> None:
    """Decision 9's actual claim: turning monetization on is a data write.

    The rollup has no revenue source, so it must not blank the columns on every
    nightly pass - otherwise the first pass after monetization began would erase
    it and the "data write, not a migration" promise would be false. Proven here
    against the real table rather than asserted on the compiled SQL: a monetization
    writer's row is still standing after the next pass recomputes the counters.
    """
    async with engine.begin() as connection:
        await _seed_actor_spend(connection)
        await _seed_every_doctor_edge(connection)
    await run_rollup(engine, _TARGET_DATE, thresholds=_THRESHOLDS)

    # Monetization arrives as a plain data write, with no code change anywhere.
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE observability.observability_attribution_daily "
                "SET revenue_paise = 250_000, tier_key = 'pro' "
                "WHERE actor_kind = 'doctor'"
            )
        )

    await run_rollup(engine, _TARGET_DATE, thresholds=_THRESHOLDS)

    async with engine.connect() as connection:
        rows = await _attribution_rows(connection)
        doctors = [row for row in rows if row["actor_kind"] == "doctor"]
        assert doctors
        for row in doctors:
            assert (row["revenue_paise"], row["tier_key"]) == (250_000, "pro")
        # The counters were still recomputed, so the write is not what froze them.
        assert {row["cost_paise"] for row in doctors} == {4_500, 1_200, 9_000}


@pytest.mark.asyncio
async def test_a_day_with_no_ai_jobs_writes_no_actor_rows(engine: AsyncEngine) -> None:
    """An idle day invents nothing: there is no actor to attribute zero spend to."""
    async with engine.begin() as connection:
        await _seed_usage(connection)

    report = await run_rollup(engine, _TARGET_DATE, thresholds=_THRESHOLDS)

    assert report.providers == 2
    assert report.attribution_rows == 0

    async with engine.connect() as connection:
        assert await _attribution_rows(connection) == []


@pytest.mark.asyncio
async def test_the_backfill_sweeps_the_actor_aggregate_for_every_history_day(
    engine: AsyncEngine,
) -> None:
    """A first run covers the whole recorded history, so no actor-day is missed.

    The same shape as the B5b schedule tests above, asserted through the surface
    this ticket adds: the per-job rows carry their own ``usage_date``, so a pass
    that only rolled the trailing day would leave the earlier one unattributed.
    """
    async with engine.begin() as connection:
        await _seed_two_days_of_usage(connection)
        await _seed_actor_spend(connection)
        await connection.execute(
            text(
                "UPDATE observability.observability_ai_job_spend "
                "SET usage_date = :day WHERE ai_job_ref = 9001"
            ),
            {"day": _TARGET_DATE - timedelta(days=1)},
        )
        await _seed_every_doctor_edge(connection)

    today = _TARGET_DATE + timedelta(days=1)
    plan = await plan_from_state(engine, today)
    assert plan.dates == (_TARGET_DATE - timedelta(days=1), _TARGET_DATE)
    for target in plan.dates:
        await run_rollup(engine, target, thresholds=_THRESHOLDS, mode=plan.mode)

    async with engine.connect() as connection:
        rows = await _attribution_rows(connection)
        # Both days landed their own rows rather than one day's figures drifting
        # into the other, and each day's patient and doctor totals reconcile.
        totals: dict[tuple[date, str], int] = {}
        for row in rows:
            key = (row["usage_date"], row["actor_kind"])
            totals[key] = totals.get(key, 0) + row["cost_paise"]
        assert totals == {
            (_TARGET_DATE - timedelta(days=1), "patient"): 4_500,
            (_TARGET_DATE - timedelta(days=1), "doctor"): 4_500,
            (_TARGET_DATE, "patient"): 10_200,
            (_TARGET_DATE, "doctor"): 10_200,
        }


@pytest.mark.asyncio
async def test_rollup_refreshes_health_snapshots_budget_and_raises_alerts(
    engine: AsyncEngine,
) -> None:
    """The acceptance criterion: one pass writes all three surfaces."""
    async with engine.begin() as connection:
        await _seed_usage(connection)
        await _seed_previous_health(connection)
        await _seed_dead_letter(connection)

    report = await run_rollup(engine, _TARGET_DATE, thresholds=_THRESHOLDS)

    assert report.providers == 2
    assert report.health_rows == 2
    assert report.metric_rows == 4
    assert report.budget_snapshots == 2

    async with engine.connect() as connection:
        openai = await _health_row(connection, "openai")
        anthropic = await _health_row(connection, "anthropic")
        budget = await _budget_row(connection)

        # openai: 3 completions at 100 ms + 1 at 400 ms, 4 of 5 calls successful.
        assert openai["sample_count"] == 4
        assert openai["success_rate"] == Decimal("0.8000")
        assert openai["p50_duration_ms"] == Decimal("100.00")
        assert openai["p95_duration_ms"] == Decimal("355.00")
        assert openai["p99_duration_ms"] == Decimal("391.00")
        assert openai["breaker_state"] == "closed"

        # anthropic: 4 completions at 250 ms, no failures.
        assert anthropic["sample_count"] == 4
        assert anthropic["success_rate"] == Decimal("1.0000")
        assert anthropic["p95_duration_ms"] == Decimal("250.00")

        # Budget: month-to-date spend snapshot over the configured period.
        assert budget["monthly_limit_paise"] == 100_000
        assert budget["alert_threshold_pct"] == 80
        assert budget["current_spend_paise"] == 115_000
        assert budget["billing_period_start"] == _PERIOD_START
        assert budget["billing_period_end"] == _PERIOD_END

        # Alerts: budget past 80%, a 20-point health drop, and the dead-letter row.
        assert await _open_alert_kinds(connection) == [
            ALERT_KIND_AI_BUDGET,
            ALERT_KIND_OUTBOX_DEAD_LETTER,
            ALERT_KIND_PROVIDER_HEALTH_DROP,
        ]

        # Generic store: one row per registered metric, provider-scoped.
        health_value = await _metric_value(connection, f"{METRIC_KEY_AI_PROVIDER_HEALTH}.openai")
        spend_value = await _metric_value(connection, f"{METRIC_KEY_AI_SPEND}.openai")
        assert health_value["success_rate"] == "0.8000"
        assert health_value["p95_duration_ms"] == "355.00"
        assert health_value["breaker_state"] == "closed"
        assert spend_value == {
            "provider": "openai",
            "calls": 5,
            "success_count": 4,
            "failure_count": 1,
            "timeout_count": 0,
            "cost_paise": 115_000,
        }


@pytest.mark.asyncio
async def test_rollup_raises_and_resolves_a_queue_age_alert_a_depth_alert_could_not_see(
    engine: AsyncEngine,
) -> None:
    """B5 (#729): one wedged job pages on its AGE, and the alert clears when it drains.

    The depth of this queue is a single row - five hundred times below the backlog
    threshold - so a pass sized on depth sees nothing here at all. The age is what
    finds it, which is the whole reason the kind exists.

    The resolve half matters as much: the queue drains, and the standing alert must
    close rather than sit in the feed until somebody clears it by hand.
    """
    stale = DEFAULT_QUEUE_AGE_ALERT_THRESHOLD_SECONDS + 600
    async with engine.begin() as connection:
        await _seed_open_queue(connection, age_seconds=stale)

    raised = await run_rollup(engine, _TARGET_DATE, thresholds=_THRESHOLDS)

    assert raised.alerts_raised == 1
    async with engine.connect() as connection:
        assert await _open_alert_kinds(connection) == [ALERT_KIND_QUEUE_AGE]
        rows = await _alert_rows(connection)
        alert = next(row for row in rows if row.kind == ALERT_KIND_QUEUE_AGE)
        # The alert NAMES the stalled queue and both figures, so an operator can
        # judge the stall rather than just see that one fired.
        assert alert.payload["queue"] == "structure"
        assert alert.payload["threshold_seconds"] == DEFAULT_QUEUE_AGE_ALERT_THRESHOLD_SECONDS
        assert alert.payload["oldest_age_seconds"] >= stale
        assert alert.severity == "critical"

    # A re-run of the same night does not stack a second copy of the same finding.
    again = await run_rollup(engine, _TARGET_DATE, thresholds=_THRESHOLDS)
    assert (again.alerts_raised, again.alerts_resolved) == (0, 0)

    # The job finishes: its queue row goes, as the completion handler deletes it.
    async with engine.begin() as connection:
        await connection.execute(
            text("DELETE FROM observability.observability_ai_queue_open WHERE ai_job_ref = 4242")
        )

    cleared = await run_rollup(engine, _TARGET_DATE, thresholds=_THRESHOLDS)

    assert cleared.alerts_resolved == 1
    async with engine.connect() as connection:
        assert await _open_alert_kinds(connection) == []
        assert [(row.kind, row.status) for row in await _alert_rows(connection)] == [
            (ALERT_KIND_QUEUE_AGE, "resolved")
        ]


@pytest.mark.asyncio
async def test_one_drained_queue_does_not_resolve_another_queues_open_alert(
    engine: AsyncEngine,
) -> None:
    """The drain rule is per queue: draining ``structure`` clears only ``structure``.

    A pass reconciles the queue-age alerts it can see plus the ones whose queue has
    gone completely empty. Two stale queues alert; one drains; the other's alert is
    untouched - otherwise clearing one incident would silently close another.
    """
    stale = DEFAULT_QUEUE_AGE_ALERT_THRESHOLD_SECONDS + 60
    async with engine.begin() as connection:
        await _seed_open_queue(connection, age_seconds=stale)
        await _seed_open_queue(connection, age_seconds=stale, queue="draft", ai_job_ref=4243)
    await run_rollup(engine, _TARGET_DATE, thresholds=_THRESHOLDS)

    async with engine.connect() as connection:
        assert sorted(await _open_alert_kinds(connection)) == [
            ALERT_KIND_QUEUE_AGE,
            ALERT_KIND_QUEUE_AGE,
        ]
        assert sorted(row.payload["queue"] for row in await _alert_rows(connection)) == [
            "draft",
            "structure",
        ]

    async with engine.begin() as connection:
        await connection.execute(
            text("DELETE FROM observability.observability_ai_queue_open WHERE queue = 'draft'")
        )

    report = await run_rollup(engine, _TARGET_DATE, thresholds=_THRESHOLDS)

    assert report.alerts_resolved == 1
    async with engine.connect() as connection:
        open_rows = await _alert_rows(connection)
        assert sorted((row.payload["queue"], row.status) for row in open_rows) == [
            ("draft", "resolved"),
            ("structure", "open"),
        ]


@pytest.mark.asyncio
async def test_rollup_resolves_a_queue_age_alert_once_the_queue_drains_completely(
    engine: AsyncEngine,
) -> None:
    """A queue whose open set is EMPTY has cleared its age condition.

    This is the one place absence resolves rather than holds (#729). The table's
    entire content IS the queue, so "no rows" is a positive statement that nothing
    is waiting - unlike a provider with no rows, which only means no traffic was
    observed. Without it, a one-job stall would leave its alert open for ever after
    the job finished.
    """
    stale = DEFAULT_QUEUE_AGE_ALERT_THRESHOLD_SECONDS + 60
    async with engine.begin() as connection:
        await _seed_open_queue(connection, age_seconds=stale)
    await run_rollup(engine, _TARGET_DATE, thresholds=_THRESHOLDS)
    assert await _open_alert_count(engine) == 1

    async with engine.begin() as connection:
        await connection.execute(text("DELETE FROM observability.observability_ai_queue_open"))

    report = await run_rollup(engine, _TARGET_DATE, thresholds=_THRESHOLDS)

    assert (report.alerts_raised, report.alerts_resolved) == (0, 1)
    assert await _open_alert_count(engine) == 0


@pytest.mark.asyncio
async def test_rollup_stays_quiet_about_a_queue_that_is_only_just_stale(
    engine: AsyncEngine,
) -> None:
    """A job inside the age threshold is not an alert, however deep the queue is."""
    async with engine.begin() as connection:
        await _seed_open_queue(
            connection, age_seconds=DEFAULT_QUEUE_AGE_ALERT_THRESHOLD_SECONDS // 2
        )

    report = await run_rollup(engine, _TARGET_DATE, thresholds=_THRESHOLDS)

    assert report.alerts_raised == 0
    async with engine.connect() as connection:
        assert await _open_alert_kinds(connection) == []
        assert [row.ai_job_ref for row in await _open_queue_rows(connection)] == [4242]


@pytest.mark.asyncio
async def test_rollup_is_idempotent_for_the_same_date(engine: AsyncEngine) -> None:
    """A retried nightly job converges: no stacked aggregates, no duplicate alerts."""
    async with engine.begin() as connection:
        await _seed_usage(connection)
        await _seed_previous_health(connection)

    first = await run_rollup(engine, _TARGET_DATE, thresholds=_THRESHOLDS)
    second = await run_rollup(engine, _TARGET_DATE, thresholds=_THRESHOLDS)

    assert first.alerts_raised == 2
    # Nothing is re-raised and nothing is closed: the budget and the health drop
    # are both still true, and a transition alert is never resolved by a pass.
    assert (second.alerts_raised, second.alerts_resolved) == (0, 0)

    async with engine.connect() as connection:
        openai = await _health_row(connection, "openai")
        assert openai["sample_count"] == 4
        assert await _open_alert_kinds(connection) == [
            ALERT_KIND_AI_BUDGET,
            ALERT_KIND_PROVIDER_HEALTH_DROP,
        ]
        assert (await _metric_value(connection, f"{METRIC_KEY_AI_SPEND}.openai"))["calls"] == 5


@pytest.mark.asyncio
async def test_rollup_resolves_a_standing_alert_once_its_threshold_clears(
    engine: AsyncEngine,
) -> None:
    """An alert that stops being true must not stay open in the operator feed."""
    async with engine.begin() as connection:
        await _seed_usage(connection)

    await run_rollup(engine, _TARGET_DATE, thresholds=_THRESHOLDS)
    assert await _open_alert_count(engine) == 1

    # The operator raises the configured cap; the next pass stops breaching it.
    generous = RollupThresholds(monthly_budget_paise=10_000_000)
    report = await run_rollup(engine, _TARGET_DATE, thresholds=generous)

    assert report.alerts_raised == 0
    assert report.alerts_resolved == 1

    async with engine.connect() as connection:
        assert await _open_alert_kinds(connection) == []
        assert [(row.kind, row.status) for row in await _alert_rows(connection)] == [
            (ALERT_KIND_AI_BUDGET, "resolved")
        ]
        # A limit already stored on a scope row is the operator's, not the pass's.
        assert (await _budget_row(connection))["monthly_limit_paise"] == 100_000
        assert (await _budget_row(connection))["current_spend_paise"] == 115_000


@pytest.mark.asyncio
async def test_rollup_on_an_idle_day_invents_no_rows_and_closes_nothing(
    engine: AsyncEngine,
) -> None:
    """An idle day is not an error: nothing is invented and no standing alert closes."""
    quiet_day = date(2026, 10, 13)
    async with engine.begin() as connection:
        await _seed_usage(connection)
    await run_rollup(engine, _TARGET_DATE, thresholds=_THRESHOLDS)

    report = await run_rollup(engine, quiet_day, thresholds=_THRESHOLDS)

    assert (report.providers, report.health_rows, report.metric_rows) == (0, 0, 0)
    assert report.budget_snapshots == 2
    assert (report.alerts_raised, report.alerts_resolved) == (0, 0)

    async with engine.connect() as connection:
        # Month-to-date spend carries forward; the idle day adds no metric row.
        assert (await _budget_row(connection))["current_spend_paise"] == 115_000
        assert await _metric_value(connection, f"{METRIC_KEY_AI_SPEND}.openai", quiet_day) is None
        # The budget is still breached, so it stays open.
        assert await _open_alert_kinds(connection) == [ALERT_KIND_AI_BUDGET]
        assert await _metric_value(connection, f"{METRIC_KEY_AI_SPEND}.openai", quiet_day) is None


# --------------------------------------------------------- B5b #705: the schedule


async def _seed_two_days_of_usage(connection: AsyncConnection) -> None:
    """Two consecutive days of usage, the shape a first-run backfill sweeps."""
    await connection.execute(
        text(
            "INSERT INTO observability.observability_ai_usage_daily "
            "(usage_date, provider, model, task_type, calls, success_count, "
            "failure_count, timeout_count, input_tokens, output_tokens, cost_paise, "
            "avg_duration_ms) VALUES "
            "(:first, 'openai', 'gpt-4o-mini', 'structure', 2, 2, 0, 0, 10, 20, 40000, "
            "  120.00), "
            "(:second, 'openai', 'gpt-4o-mini', 'structure', 3, 3, 0, 0, 10, 20, 30000, "
            "  150.00)"
        ),
        {"first": _TARGET_DATE - timedelta(days=1), "second": _TARGET_DATE},
    )


@pytest.mark.asyncio
async def test_the_first_run_backfills_every_day_of_existing_history(
    engine: AsyncEngine,
) -> None:
    """With nothing on the ledger, the planned pass covers the whole recorded history.

    ``today`` is the day after both seeded days, so "all AI-job history" is
    10-11 and 10-12 - and never today itself, which is still accumulating.
    """
    async with engine.begin() as connection:
        await _seed_two_days_of_usage(connection)

    today = _TARGET_DATE + timedelta(days=1)
    state = await load_rollup_state(engine, today)
    assert state.last_rolled_date is None
    plan = plan_rollup_dates(
        today=today,
        last_rolled=state.last_rolled_date,
        history_start=state.history_start,
        max_dates=90,
    )
    assert plan.mode == ROLLUP_MODE_BACKFILL
    assert plan.dates == (_TARGET_DATE - timedelta(days=1), _TARGET_DATE)

    for target in plan.dates:
        await run_rollup(engine, target, thresholds=_THRESHOLDS, mode=plan.mode)

    async with engine.connect() as connection:
        # Both days landed their metrics, not just the trailing one.
        for target in plan.dates:
            assert (
                await _metric_value(connection, f"{METRIC_KEY_AI_SPEND}.openai", target) is not None
            )
        # The ledger records each day, oldest first, tagged as the backfill.
        assert [(row["rollup_date"], row["mode"]) for row in await _run_rows(connection)] == [
            (_TARGET_DATE - timedelta(days=1), ROLLUP_MODE_BACKFILL),
            (_TARGET_DATE, ROLLUP_MODE_BACKFILL),
        ]


@pytest.mark.asyncio
async def test_a_later_run_rolls_only_the_previous_day(engine: AsyncEngine) -> None:
    """After the backfill the plan narrows to the trailing day, as plan §8 states.

    The backfill ran against ``today = first_day``, so it swept 10-11 and 10-12
    but not today. A pass on the NEXT day therefore has exactly one day to roll.
    """
    async with engine.begin() as connection:
        await _seed_two_days_of_usage(connection)

    first_day = _TARGET_DATE + timedelta(days=1)
    state = await load_rollup_state(engine, first_day)
    first = plan_rollup_dates(
        today=first_day,
        last_rolled=state.last_rolled_date,
        history_start=state.history_start,
        max_dates=90,
    )
    assert first.dates == (_TARGET_DATE - timedelta(days=1), _TARGET_DATE)
    for target in first.dates:
        await run_rollup(engine, target, thresholds=_THRESHOLDS, mode=first.mode)

    assert (await load_rollup_state(engine, first_day)).last_rolled_date == _TARGET_DATE

    # The next night's pass: yesterday is the one day the ledger has not covered.
    second_day = first_day + timedelta(days=1)
    state = await load_rollup_state(engine, second_day)
    second = plan_rollup_dates(
        today=second_day,
        last_rolled=state.last_rolled_date,
        history_start=state.history_start,
        max_dates=90,
    )

    assert second.mode == ROLLUP_MODE_DAILY
    assert second.dates == (first_day,)
    await run_rollup(engine, first_day, thresholds=_THRESHOLDS, mode=second.mode)

    # Re-planning right after that pass is a no-op: nothing is left to roll.
    after = await load_rollup_state(engine, second_day)
    assert after.last_rolled_date == first_day
    assert (
        plan_rollup_dates(
            today=second_day,
            last_rolled=after.last_rolled_date,
            history_start=after.history_start,
            max_dates=90,
        ).dates
        == ()
    )


@pytest.mark.asyncio
async def test_re_running_a_rolled_date_leaves_one_ledger_row(engine: AsyncEngine) -> None:
    """``rollup_date`` is UNIQUE, so a retried scheduled job refreshes rather than stacks."""
    async with engine.begin() as connection:
        await _seed_usage(connection)

    await run_rollup(engine, _TARGET_DATE, thresholds=_THRESHOLDS, mode=ROLLUP_MODE_DAILY)
    await run_rollup(engine, _TARGET_DATE, thresholds=_THRESHOLDS, mode=ROLLUP_MODE_DAILY)

    assert await _run_row_count(engine) == 1


@pytest.mark.asyncio
async def test_a_missed_night_is_caught_up_rather_than_lost(engine: AsyncEngine) -> None:
    """A skipped run is a gap the ledger records, and the next pass fills it."""
    async with engine.begin() as connection:
        await _seed_two_days_of_usage(connection)

    await run_rollup(engine, _TARGET_DATE - timedelta(days=1), thresholds=_THRESHOLDS)
    # Two nights later, having rolled nothing in between.
    today = _TARGET_DATE + timedelta(days=1)
    state = await load_rollup_state(engine, today)
    plan = plan_rollup_dates(
        today=today,
        last_rolled=state.last_rolled_date,
        history_start=state.history_start,
        max_dates=90,
    )

    assert plan.dates == (_TARGET_DATE,)

    for target in plan.dates:
        await run_rollup(engine, target, thresholds=_THRESHOLDS, mode=plan.mode)

    async with engine.connect() as connection:
        assert (
            await _metric_value(connection, f"{METRIC_KEY_AI_SPEND}.openai", _TARGET_DATE)
            is not None
        )


@pytest.mark.asyncio
async def test_the_budget_period_rolls_over_on_the_first_pass_in_the_new_month(
    engine: AsyncEngine,
) -> None:
    """A closed month's spend comes back to zero for the new period (plan §8).

    October's row holds 115,000 paise and the October billing period. The next
    month's first pass resets the figure and moves the row onto the new period,
    with no separate monthly job and no month-end trigger to forget.
    """
    async with engine.begin() as connection:
        await _seed_usage(connection)
    await run_rollup(engine, _TARGET_DATE, thresholds=_THRESHOLDS)
    async with engine.connect() as connection:
        assert (await _budget_row(connection))["current_spend_paise"] == 115_000
        assert (await _budget_row(connection))["billing_period_start"] == _PERIOD_START

    # The first of November: spend is scoped to the new month, so it is zero.
    november = date(2026, 11, 1)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO observability.observability_ai_usage_daily "
                "(usage_date, provider, model, task_type, calls, success_count, "
                "failure_count, timeout_count, input_tokens, output_tokens, cost_paise, "
                "avg_duration_ms) VALUES "
                "(:day, 'openai', 'gpt-4o-mini', 'structure', 1, 1, 0, 0, 5, 5, 1000, 90.00)"
            ),
            {"day": november},
        )
    await run_rollup(engine, november, thresholds=_THRESHOLDS)

    async with engine.connect() as connection:
        budget = await _budget_row(connection)
        assert budget["billing_period_start"] == date(2026, 11, 1)
        assert budget["billing_period_end"] == date(2026, 11, 30)
        # October's 115,000 paise is gone; only November's 1,000 remains.
        assert budget["current_spend_paise"] == 1_000
        # A scope with no November traffic keeps its row but carries no spend.
        anthropic = await connection.execute(
            text(
                "SELECT current_spend_paise, billing_period_start FROM "
                "observability.observability_ai_cost_budget "
                "WHERE provider = 'anthropic' AND model = 'claude-haiku'"
            )
        )
        row = anthropic.mappings().one()
        assert row["current_spend_paise"] == 0
        assert row["billing_period_start"] == date(2026, 11, 1)
        # The ledger says which period the last pass rolled into.
        assert [record["billing_period_start"] for record in await _run_rows(connection)][-1] == (
            date(2026, 11, 1)
        )


@pytest.mark.asyncio
async def test_the_period_reset_also_clears_a_row_that_never_had_a_period(
    engine: AsyncEngine,
) -> None:
    """``billing_period_start`` is nullable, so the reset needs an explicit NULL arm.

    A plain ``billing_period_start < period_start`` never matches NULL in SQL: the
    row would keep a closed month's spend forever, which is the exact leak the
    monthly reset exists to close.
    """
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO observability.observability_ai_cost_budget "
                "(provider, model, monthly_limit_paise, alert_threshold_pct, "
                "current_spend_paise, billing_period_start, billing_period_end) "
                "VALUES ('openai', 'gpt-4o-mini', 100000, 80, 99000, NULL, NULL)"
            )
        )
        await _seed_usage(connection)

    await run_rollup(engine, _TARGET_DATE, thresholds=_THRESHOLDS)

    async with engine.connect() as connection:
        budget = await _budget_row(connection)
        assert budget["billing_period_start"] == _PERIOD_START
        # The stale 99,000 paise is zeroed and October's 115,000 accrued on top.
        assert budget["current_spend_paise"] == 115_000


@pytest.mark.asyncio
async def test_a_manually_rolled_future_date_does_not_stall_the_schedule(
    engine: AsyncEngine,
) -> None:
    """An operator's ``--date <some future day>`` must not wedge the nightly.

    ``--date`` is an override with no opinion on the calendar, so it will happily
    write a row dated ahead of now. Taken as the schedule's high-water mark, that one
    row would make every later plan think it had nothing to roll - silently, every
    night, until someone noticed the aggregates had stopped moving.
    """
    async with engine.begin() as connection:
        await _seed_usage(connection)

    today = _TARGET_DATE + timedelta(days=1)
    await run_rollup(engine, today + timedelta(days=30), thresholds=_THRESHOLDS)

    # The future row is invisible to the planner, so the one real day still gets rolled.
    plan = await plan_from_state(engine, today)
    assert plan.dates == (_TARGET_DATE,)


@pytest.mark.asyncio
async def test_rolling_today_by_hand_does_not_strand_yesterday(engine: AsyncEngine) -> None:
    """A same-day manual roll must not be mistaken for a completed schedule.

    The planner only ever plans through yesterday, so a ledger read that counted
    today as done would report the schedule up to date and quietly drop the previous
    night - the one day of spend the manual roll could not possibly have covered.
    """
    async with engine.begin() as connection:
        await _seed_usage(connection)

    today = _TARGET_DATE + timedelta(days=1)
    await run_rollup(engine, today, thresholds=_THRESHOLDS)

    assert (await plan_from_state(engine, today)).dates == (_TARGET_DATE,)
