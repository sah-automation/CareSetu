"""B4e #739: the product event ledger's registry, key derivation and daily rollup (no DB).

Covers the three pure seams #739 adds:

* the funnel-step REGISTRY and its guards - adding a step is one registration, and a
  duplicate scope, a duplicate event type or an undeclared outcome is refused;
* the ledger row's keys - the published trace wins, the derived one is stable per
  ``event_id``, and the actor projection is a one-way hash of the reference;
* the daily rollup's pure core at both grains - per-step scope counts and per-actor
  days - including the rerun-is-identical property the adapter's upsert depends on.

The handler seats and the SQL they write are asserted in
``test_observability_product_consumer.py`` and in the integration round trip.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from uuid import UUID, uuid4

import pytest

import modules.observability.domain.product as product_module
from bus.events import (
    EVENT_CASE_CLOSED,
    EVENT_CASE_CONSULT_COMPLETE,
    EVENT_INTAKE_CAPTURED,
    EVENT_INTAKE_COMPOSER_OPENED,
    EVENT_INTAKE_RETRY_REQUESTED,
    EVENT_PRE_SUMMARY_READY,
    EVENT_PRESCRIPTION_APPROVED,
    EVENT_PRESCRIPTION_DRAFT_CREATED,
)
from modules.observability.domain.consumer import (
    PRODUCT_EVENT_MIRRORS,
    IntakeComposerOpenedTelemetryPayload,
)
from modules.observability.domain.product import (
    FUNNEL_INTAKE,
    PRODUCT_OUTCOME_ABANDONED,
    PRODUCT_OUTCOME_COMPLETED,
    PRODUCT_OUTCOME_ERRORED,
    PRODUCT_OUTCOME_RE_RECORDED,
    ProductEventFact,
    ProductStep,
    ProductStepPayload,
    build_product_daily,
    derived_step_key,
    duration_ms_of,
    product_event_keys,
    product_step_for_event,
    product_steps,
    register_product_step,
)
from modules.observability.domain.pseudonym import (
    ACTOR_KIND_DOCTOR,
    ACTOR_KIND_PATIENT,
)

_DAY = date(2026, 10, 13)
#: The re-record step, which is a machine outcome with no actor behind it.
_RE_RECORDED = "re_recorded"
_EVENT_ID = UUID("11111111-2222-3333-4444-555555555555")


# ------------------------------------------------------------------ the registry


def test_the_intake_funnel_is_declared_head_to_tail_in_patient_order() -> None:
    """Registration order IS the funnel order, and the entry step is the head."""
    steps = product_steps()
    assert [step.step for step in steps] == [
        "composer_opened",
        "intake_captured",
        "pre_summary_ready",
        "consult_complete",
        "prescription_drafted",
        "prescription_approved",
        "case_closed",
        "re_recorded",
    ]
    assert {step.funnel for step in steps} == {FUNNEL_INTAKE}


def test_every_step_declares_a_closed_outcome_vocabulary() -> None:
    """No step's recorded outcome falls outside the vocabulary it declares."""
    vocabulary = {
        PRODUCT_OUTCOME_COMPLETED,
        PRODUCT_OUTCOME_ABANDONED,
        PRODUCT_OUTCOME_ERRORED,
        PRODUCT_OUTCOME_RE_RECORDED,
    }
    for step in product_steps():
        assert step.allowed_outcomes, step.step
        assert set(step.allowed_outcomes) <= vocabulary, step.step
        assert step.outcome in step.allowed_outcomes, step.step


def test_the_entry_step_separates_a_walkaway_from_a_broken_capture() -> None:
    """The funnel's head can be abandoned AND errored - never quietly one of them."""
    head = product_step_for_event(EVENT_INTAKE_COMPOSER_OPENED)
    assert head is not None
    assert set(head.allowed_outcomes) == {
        PRODUCT_OUTCOME_COMPLETED,
        PRODUCT_OUTCOME_ABANDONED,
        PRODUCT_OUTCOME_ERRORED,
    }


def test_a_re_record_is_its_own_outcome_and_never_a_failure_of_the_original() -> None:
    """Decision 25: the retry step's vocabulary is exactly ``re_recorded``."""
    step = product_step_for_event(EVENT_INTAKE_RETRY_REQUESTED)
    assert step is not None
    assert step.outcome == PRODUCT_OUTCOME_RE_RECORDED
    assert step.allowed_outcomes == (PRODUCT_OUTCOME_RE_RECORDED,)


def test_the_mirror_registry_covers_exactly_the_registered_steps() -> None:
    """A step with no mirror has nowhere to read its actor; a mirror with no step
    is a payload nobody consumes."""
    assert set(PRODUCT_EVENT_MIRRORS) == {step.event_type for step in product_steps()}


def test_every_step_declares_an_actor_kind_its_mirror_can_actually_carry() -> None:
    """An active-actor count is built from this column, so it must be meaningful.

    The reference the declared kind names has to be a REQUIRED field on the mirror.
    It is inherited from ``ProductStepPayload`` as optional on every mirror, so a step
    that names an actor kind without re-declaring it would validate fine and then
    write a row with no actor - a silently empty column in the one place that counts
    people.
    """
    for step in product_steps():
        fields = PRODUCT_EVENT_MIRRORS[step.event_type].model_fields
        required = {name for name in ("patient_id", "doctor_id") if fields[name].is_required()}
        if step.actor_kind is None:
            # A machine step names no actor, and its mirror must not smuggle one in.
            assert not required, step.step
            continue
        expected = "patient_id" if step.actor_kind == ACTOR_KIND_PATIENT else "doctor_id"
        # The care mirrors legitimately carry both references - the producer
        # publishes both - so the assertion is that the step's OWN kind is available,
        # not that it is the only one.
        assert expected in required, step.step


def test_registering_a_step_extends_the_registry_with_no_schema_change() -> None:
    """AC3: adding a step is a registry line, not a migration or an adapter edit."""
    sentinel = ProductStep(
        funnel="prescription",
        step="pharmacy_delivered",
        event_type="prescription.delivered",
        outcome=PRODUCT_OUTCOME_COMPLETED,
        allowed_outcomes=(PRODUCT_OUTCOME_COMPLETED, PRODUCT_OUTCOME_ERRORED),
        actor_kind="patient",
    )
    try:
        register_product_step(sentinel)
        assert product_step_for_event("prescription.delivered") is sentinel
        assert sentinel in product_steps()
    finally:
        product_module.PRODUCT_STEP_REGISTRY.pop(("prescription", "pharmacy_delivered"), None)
        product_module._EVENT_STEP_INDEX.pop("prescription.delivered", None)
    assert product_step_for_event("prescription.delivered") is None


def test_registering_a_duplicate_step_scope_is_refused() -> None:
    """Two entries for one scope would write two rows for one step and double it."""
    with pytest.raises(ValueError, match=r"intake\.composer_opened"):
        register_product_step(
            ProductStep(
                funnel=FUNNEL_INTAKE,
                step="composer_opened",
                event_type="intake.composer_reopened",
                outcome=PRODUCT_OUTCOME_COMPLETED,
                allowed_outcomes=(PRODUCT_OUTCOME_COMPLETED,),
            )
        )


def test_registering_an_event_type_twice_is_refused() -> None:
    """One delivery is one moment of one journey, never two steps of one funnel."""
    with pytest.raises(ValueError, match=r"intake\.composer_opened"):
        register_product_step(
            ProductStep(
                funnel=FUNNEL_INTAKE,
                step="composer_reopened",
                event_type=EVENT_INTAKE_COMPOSER_OPENED,
                outcome=PRODUCT_OUTCOME_COMPLETED,
                allowed_outcomes=(PRODUCT_OUTCOME_COMPLETED,),
            )
        )


def test_a_step_may_not_record_an_outcome_it_does_not_declare() -> None:
    """A step whose vocabulary and recorded outcome disagree counts another question."""
    with pytest.raises(ValueError, match=r"allowed_outcomes"):
        register_product_step(
            ProductStep(
                funnel="prescription",
                step="issued",
                event_type="prescription.issued",
                outcome=PRODUCT_OUTCOME_ERRORED,
                allowed_outcomes=(PRODUCT_OUTCOME_COMPLETED,),
            )
        )


# ------------------------------------------------------------------- the keys


def test_a_published_trace_wins_over_the_derived_one() -> None:
    """The join key is the real tracing id whenever the producer published one."""
    payload = IntakeComposerOpenedTelemetryPayload(
        patient_id=3,
        session_key="a" * 32,
        trace_id="b" * 32,
    )
    trace_id, session_key = product_event_keys(payload, event_id=_EVENT_ID)
    assert trace_id == "b" * 32
    assert session_key == "a" * 32


def test_a_step_with_no_published_trace_records_a_stable_derived_key() -> None:
    """Deterministic per ``event_id``, so a replay recomputes the same row."""
    payload = ProductStepPayload()
    trace_id, session_key = product_event_keys(payload, event_id=_EVENT_ID)
    assert trace_id == derived_step_key(_EVENT_ID)
    assert session_key == trace_id
    assert product_event_keys(payload, event_id=_EVENT_ID) == (trace_id, session_key)
    assert trace_id != derived_step_key(uuid4())
    assert len(trace_id) == 64


def test_a_blank_trace_is_treated_as_no_trace() -> None:
    """An empty column is not a trace, and the derived key is the honest value."""
    payload = ProductStepPayload(trace_id="   ", session_key="")
    trace_id, session_key = product_event_keys(payload, event_id=_EVENT_ID)
    assert trace_id == derived_step_key(_EVENT_ID)
    assert session_key == trace_id


def test_duration_is_converted_to_milliseconds_and_null_stays_null() -> None:
    """An unmeasured step records NULL, never a zero that reads as instantaneous."""
    assert duration_ms_of(ProductStepPayload()) is None
    assert duration_ms_of(ProductStepPayload(duration_s=12.5)) == 12500
    assert duration_ms_of(ProductStepPayload(duration_s=0.0)) == 0
    assert duration_ms_of(ProductStepPayload(duration_s=-1.0)) == 0


# ------------------------------------------------------------ the daily rollup


def _fact(
    *,
    funnel: str = FUNNEL_INTAKE,
    step: str = "composer_opened",
    outcome: str = PRODUCT_OUTCOME_COMPLETED,
    actor_kind: str | None = ACTOR_KIND_PATIENT,
    actor_key_value: str | None = "k" * 64,
    duration_ms: int | None = None,
    day: date = _DAY,
) -> ProductEventFact:
    return ProductEventFact(
        occurred_at=datetime.combine(day, time(hour=9), tzinfo=UTC),
        funnel=funnel,
        step=step,
        outcome=outcome,  # type: ignore[arg-type]
        actor_kind=actor_kind,  # type: ignore[arg-type]
        actor_key=actor_key_value,
        duration_ms=duration_ms,
    )


def test_the_step_aggregate_counts_events_and_distinct_actors_separately() -> None:
    """One actor at three steps is three events and ONE active actor."""
    events = [
        _fact(step="composer_opened", actor_key_value="a" * 64),
        _fact(step="intake_captured", actor_key_value="a" * 64),
        _fact(step="intake_captured", actor_key_value="b" * 64),
    ]
    rows = build_product_daily(events=events, target_date=_DAY)

    assert [(row.funnel, row.step, row.events, row.actor_count) for row in rows] == [
        (FUNNEL_INTAKE, "composer_opened", 1, 1),
        (FUNNEL_INTAKE, "intake_captured", 2, 2),
    ]


def test_the_step_aggregate_totals_durations_only_where_a_span_was_measured() -> None:
    """A NULL duration is not a zero-length step and is excluded from the total."""
    events = [
        _fact(step="intake_captured", duration_ms=4000),
        _fact(step="intake_captured", duration_ms=6000),
        _fact(step="intake_captured", duration_ms=None),
    ]
    (row,) = build_product_daily(events=events, target_date=_DAY)
    assert row.events == 3
    assert row.total_duration_ms == 10000
    assert row.duration_samples == 2


def test_a_machine_step_counts_events_but_never_an_actor() -> None:
    """A re-record has no identity behind it, so it must not inflate the actor count."""
    events = [
        _fact(step=_RE_RECORDED, outcome=PRODUCT_OUTCOME_RE_RECORDED, actor_kind=None),
        _fact(step=_RE_RECORDED, outcome=PRODUCT_OUTCOME_RE_RECORDED, actor_kind=None),
    ]
    (row,) = build_product_daily(events=events, target_date=_DAY)
    assert row.events == 2
    assert row.actor_count == 0


def test_a_key_with_no_kind_behind_it_never_counts_as_an_actor() -> None:
    """The ledger's CHECK says the pair is set together; the core honours it anyway."""
    (row,) = build_product_daily(
        events=[_fact(actor_kind=None, actor_key_value="k" * 64)], target_date=_DAY
    )
    assert row.events == 1
    assert row.actor_count == 0


def test_a_step_and_an_actor_at_the_same_step_land_on_separate_scopes() -> None:
    """The outcome is part of the grain, so a filtered-out error is not folded in."""
    events = [
        _fact(outcome=PRODUCT_OUTCOME_COMPLETED),
        _fact(outcome=PRODUCT_OUTCOME_ERRORED),
    ]
    rows = build_product_daily(events=events, target_date=_DAY)
    assert {row.outcome for row in rows} == {
        PRODUCT_OUTCOME_COMPLETED,
        PRODUCT_OUTCOME_ERRORED,
    }


def test_a_row_filed_on_another_day_is_not_counted_into_this_pass() -> None:
    """The day is the aggregate's key, so a misfiled row cannot drift between passes."""
    events = [_fact(), _fact(day=date(2026, 10, 14))]
    (row,) = build_product_daily(events=events, target_date=_DAY)
    assert row.events == 1


def test_rerunning_the_aggregate_produces_the_identical_rows() -> None:
    """Full recompute, never accumulate - the property the adapter's upsert needs."""
    events = [
        _fact(step="intake_captured", duration_ms=4000),
        _fact(step="intake_captured", actor_key_value="b" * 64),
        _fact(step="consult_complete", actor_kind=ACTOR_KIND_DOCTOR),
    ]
    assert build_product_daily(events=events, target_date=_DAY) == build_product_daily(
        events=events, target_date=_DAY
    )


def test_a_late_arriving_step_is_picked_up_by_the_next_pass() -> None:
    """What an incrementing rollup could never do: the day's figure is re-derived."""
    first = [_fact(step="composer_opened")]
    later = [*first, _fact(step="intake_captured", actor_key_value="b" * 64)]

    before = {row.step: row.events for row in build_product_daily(events=first, target_date=_DAY)}
    after = {row.step: row.events for row in build_product_daily(events=later, target_date=_DAY)}
    assert before == {"composer_opened": 1}
    assert after == {"composer_opened": 1, "intake_captured": 1}


def test_an_empty_day_produces_no_rows_rather_than_zeroed_ones() -> None:
    """An absent row is evidence; a row of zeroes would be a second way of saying it."""
    assert build_product_daily(events=[], target_date=_DAY) == ()


def test_every_consumed_event_type_is_a_registered_funnel_step() -> None:
    """The registry and the consumed set are the same list, read off one place."""
    assert {step.event_type for step in product_steps()} == {
        EVENT_INTAKE_COMPOSER_OPENED,
        EVENT_INTAKE_CAPTURED,
        EVENT_PRE_SUMMARY_READY,
        EVENT_CASE_CONSULT_COMPLETE,
        EVENT_CASE_CLOSED,
        EVENT_PRESCRIPTION_DRAFT_CREATED,
        EVENT_PRESCRIPTION_APPROVED,
        EVENT_INTAKE_RETRY_REQUESTED,
    }
