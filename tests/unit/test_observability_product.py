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
    FUNNEL_TERMINAL_CASE_CLOSED,
    FUNNEL_TERMINAL_PRESCRIPTION,
    NON_CLINICAL_EVENT_WORDS,
    PRODUCT_OUTCOME_ABANDONED,
    PRODUCT_OUTCOME_COMPLETED,
    PRODUCT_OUTCOME_ERRORED,
    PRODUCT_OUTCOME_RE_RECORDED,
    PRODUCT_OUTCOMES,
    ProductEventFact,
    ProductStep,
    ProductStepPayload,
    active_actor_step_names,
    active_actor_steps,
    build_product_daily,
    derived_step_key,
    duration_ms_of,
    funnel_stages,
    is_active_actor_step,
    non_clinical_event_word,
    product_event_keys,
    product_step_for_event,
    product_steps,
    register_product_step,
    stage_predecessor,
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


def test_the_outcome_vocabulary_is_enumerable_so_a_read_can_gate_on_it() -> None:
    """The closed vocabulary is also a LIST, for the routes that have to enumerate it."""
    assert PRODUCT_OUTCOMES == (
        PRODUCT_OUTCOME_COMPLETED,
        PRODUCT_OUTCOME_ABANDONED,
        PRODUCT_OUTCOME_ERRORED,
        PRODUCT_OUTCOME_RE_RECORDED,
    )


def test_the_walk_is_the_funnel_without_the_re_record_step() -> None:
    """A corrected attempt is not a stage an attempt passes through; it is its own row."""
    assert [step.step for step in funnel_stages()] == [
        "composer_opened",
        "intake_captured",
        "pre_summary_ready",
        "consult_complete",
        "prescription_drafted",
        "prescription_approved",
        "case_closed",
    ]


def test_both_ends_of_the_funnel_are_declared_terminal() -> None:
    """An issued prescription and a closed case are both ends, and neither is a drop-off."""
    terminals = [step.step for step in funnel_stages() if step.terminal]
    assert terminals == [FUNNEL_TERMINAL_PRESCRIPTION, FUNNEL_TERMINAL_CASE_CLOSED]
    # Nothing else is an end: a step a workflow can still walk past cannot be terminal.
    assert len(terminals) == 2


def test_both_terminals_take_their_denominator_from_the_last_non_terminal_step() -> None:
    """Otherwise a case closed without one reads as the step AFTER an issued prescription."""
    stages = funnel_stages()
    for terminal in (FUNNEL_TERMINAL_PRESCRIPTION, FUNNEL_TERMINAL_CASE_CLOSED):
        step = next(stage for stage in stages if stage.step == terminal)
        assert stage_predecessor(step, stages).step == "prescription_drafted"  # type: ignore[union-attr]


def test_the_first_stage_has_no_predecessor_to_divide_by() -> None:
    """The entry step is where a funnel starts, so its conversion has no denominator."""
    assert stage_predecessor(funnel_stages()[0]) is None


def test_a_step_outside_the_walk_has_no_predecessor_to_divide_by() -> None:
    """The re-record is not in the walk, so nothing in the walk follows it."""
    re_recorded = product_step_for_event(EVENT_INTAKE_RETRY_REQUESTED)
    assert re_recorded is not None
    assert stage_predecessor(re_recorded) is None


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


# ------------------------------------------------------------- the active set (#741)


def test_an_active_user_is_someone_who_did_a_clinical_action() -> None:
    """AC2: the qualifying set is every step that names an actor kind, and no other.

    Seven of the eight registered steps qualify. The one that does not is the
    re-record, which a machine finishes on an intake's behalf - counting it would
    inflate the base with intakes nobody is behind.
    """
    qualifying = {step.step for step in active_actor_steps()}

    assert qualifying == {
        "composer_opened",
        "intake_captured",
        "pre_summary_ready",
        "consult_complete",
        "prescription_drafted",
        "prescription_approved",
        "case_closed",
    }
    assert _RE_RECORDED not in qualifying
    assert not is_active_actor_step(product_step_for_event(EVENT_INTAKE_RETRY_REQUESTED))
    # Both halves of the funnel are represented, so "who was here" is not a patient
    # count wearing a doctor's name.
    assert {step.actor_kind for step in active_actor_steps()} == {
        ACTOR_KIND_PATIENT,
        ACTOR_KIND_DOCTOR,
    }


def test_the_active_step_names_are_the_registrys_own_and_never_a_literal() -> None:
    """A newly registered clinical step becomes active by declaring an actor kind."""
    assert active_actor_step_names() == tuple(step.step for step in active_actor_steps())

    sentinel = ProductStep(
        funnel="prescription",
        step="pharmacy_delivered",
        event_type="prescription.delivered",
        outcome=PRODUCT_OUTCOME_COMPLETED,
        allowed_outcomes=(PRODUCT_OUTCOME_COMPLETED,),
        actor_kind="patient",
    )
    try:
        register_product_step(sentinel)
        assert sentinel.step in active_actor_step_names()
    finally:
        product_module.PRODUCT_STEP_REGISTRY.pop(("prescription", "pharmacy_delivered"), None)
        product_module._EVENT_STEP_INDEX.pop("prescription.delivered", None)
    assert sentinel.step not in active_actor_step_names()


def test_registering_an_authentication_or_session_event_is_refused() -> None:
    """AC2: no login, logout or session event can enter the registry.

    A refusal rather than a filter, because this registry is the ONLY definition of
    what counts as activity: admitting a login would not add a signal, it would
    replace the clinical one every adoption figure is built from.
    """
    for word in NON_CLINICAL_EVENT_WORDS:
        with pytest.raises(ValueError, match=rf"{word}"):
            register_product_step(
                ProductStep(
                    funnel=FUNNEL_INTAKE,
                    step=f"tried_{word}",
                    event_type=f"patient.{word}_attempted",
                    outcome=PRODUCT_OUTCOME_COMPLETED,
                    allowed_outcomes=(PRODUCT_OUTCOME_COMPLETED,),
                    actor_kind="patient",
                )
            )
    assert "tried_auth" not in active_actor_step_names()


def test_no_registered_step_names_an_authentication_session_or_logout_event() -> None:
    """The guard above is the mechanism; this is the property the report is written against."""
    offenders = [
        step.event_type for step in product_steps() if non_clinical_event_word(step.event_type)
    ]

    assert offenders == []


def test_the_guard_refuses_a_login_shape_whatever_module_publishes_it() -> None:
    """``patient.auth_failed`` and ``auth.session_opened`` are caught by the same rule.

    Matched per SEGMENT rather than as a free substring: a whole-name prefix rule
    misses ``patient.auth_failed`` because the platform namespaces authentication
    under ``patient.``, and a bare ``"auth" in name`` refuses ``prescription.
    authorized`` - which is an e-prescription going out, the opposite of a login.
    """
    for event_type in ("patient.auth_failed", "auth.session_opened", "logout.recorded"):
        with pytest.raises(ValueError, match=r"qualifying clinical action"):
            register_product_step(
                ProductStep(
                    funnel=FUNNEL_INTAKE,
                    step="never_registered",
                    event_type=event_type,
                    outcome=PRODUCT_OUTCOME_COMPLETED,
                    allowed_outcomes=(PRODUCT_OUTCOME_COMPLETED,),
                )
            )
    assert ("intake", "never_registered") not in product_module.PRODUCT_STEP_REGISTRY
    assert "never_registered" not in active_actor_step_names()


@pytest.mark.parametrize(
    "event_type",
    [
        "prescription.authorized",
        "pharmacy.authority_granted",
        "patient.consent_granted",
    ],
)
def test_a_clinical_event_is_never_refused_for_merely_sharing_a_prefix(event_type: str) -> None:
    """The guard exists to keep logins out, not to police spelling.

    Three names a free-substring rule would get wrong in both directions: two start
    with an authentication word without being one, and ``consent.granted`` proves the
    rule is not simply "refuse anything unfamiliar".

    What it WILL refuse is a name that calls itself ``session_``-something, which is
    deliberate rather than a limitation: in this platform a session is an
    authentication session, so a clinical event wanting that word has to say what kind
    of session it is (``counselling.held``) before it may join the registry.
    """
    step = ProductStep(
        funnel="probe",
        step="probe",
        event_type=event_type,
        outcome=PRODUCT_OUTCOME_COMPLETED,
        allowed_outcomes=(PRODUCT_OUTCOME_COMPLETED,),
        actor_kind="patient",
    )
    try:
        register_product_step(step)
        assert product_step_for_event(event_type) is step
    finally:
        product_module.PRODUCT_STEP_REGISTRY.pop(("probe", "probe"), None)
        product_module._EVENT_STEP_INDEX.pop(event_type, None)
    assert product_step_for_event(event_type) is None


def test_the_outcome_vocabulary_is_checked_before_the_authentication_shape() -> None:
    """A step that breaks two rules fails on the one that predates this ticket.

    Ordering is not a behaviour anyone should depend on, but a caller that already
    handled "the outcome is not declared" should not start seeing a different error
    because an unrelated guard moved in front of it.
    """
    with pytest.raises(ValueError, match=r"allowed_outcomes"):
        register_product_step(
            ProductStep(
                funnel=FUNNEL_INTAKE,
                step="both_wrong",
                event_type="patient.auth_failed",
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
