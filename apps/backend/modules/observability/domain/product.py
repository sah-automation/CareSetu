"""MOD-013: the product event ledger's funnel-step registry and its daily rollup (B4e #739).

Spec #717 decisions 22-26 and 41. Two things live here, and neither of them is a
table:

* **The funnel-step registry.** A step is a :class:`ProductStep` entry naming the
  event it is recorded from, the outcome that event means, the outcomes the step
  MAY hold, and the actor kind it is attributed to. Registering one is how a LATER
  phase adds a step - a single :func:`register_product_step` call, no migration, no
  adapter edit, no consumer handler written by hand. The ledger and the daily
  rollup are generic over the registry, which is what makes that true rather than
  aspirational: nothing anywhere enumerates the steps.

* **The daily rollup's pure core.** :func:`build_product_daily` recomputes one day's
  aggregates from that day's ledger rows, in full, so the adapter can upsert rather
  than increment.

**Why the rollup exists at all.** The free Grafana tier keeps fourteen days, so a
monthly active-user figure or a thirty-day retention cohort is not a query a vendor
can answer - the data is gone before the question is asked. Those numbers have to
live in the system of record, and they cannot live in the raw ledger either: a
thirty-day window over a per-event table scans thirty days of events. So the ledger
is the append-only record and the daily aggregate is what a long window reads. The
grain is per ``(funnel, step, outcome)`` because that is the shape both long windows
need: it answers "which step loses people", and because ``#726`` gave the row an
``actor_count`` of the distinct pseudonymous actors behind it, it also answers "is
adoption sticking" without a second table and without touching the ledger (decisions
22, 24-26).

**The outcome vocabulary is closed.** ``completed``, ``abandoned``, ``errored`` and
``re_recorded``, spelled as a ``Literal`` so a fourth state is a type error at the
registration site rather than a CHECK-constraint violation raised from the database
halfway through a consumer transaction. Two of those four are RULES rather than
labels:

* a degraded fallback is **errored**, never a quiet abandonment, so a broken path can
  never be read as a normal drop-off (decision 24);
* a re-record is **its own outcome**, so a corrected attempt is not scored as a
  failure of the original (decision 25).

**Active actors are derived from this ledger, never from a login.** There is no
authentication, session or logout event in the registry and adding one is out of
scope (decision 26, spec Out of Scope). Every actor key on a row comes from an
identity reference the producer already publishes on a real clinical action, hashed
through :func:`~modules.observability.domain.pseudonym.actor_key`, so "who was
active" means "who did something clinical" by construction rather than by a filter
some future read has to remember to apply.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

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
from modules.observability.domain.pseudonym import ActorKind

#: The outcome vocabulary, as constants for callers that compare or map. Annotated
#: as the type rather than left as ``str`` so passing one of them to a step cannot
#: fail the ``Literal`` check - the same trick ``domain.pseudonym`` uses for
#: ``ACTOR_KIND_PATIENT``.
PRODUCT_OUTCOME_COMPLETED: ProductOutcome = "completed"
PRODUCT_OUTCOME_ABANDONED: ProductOutcome = "abandoned"
PRODUCT_OUTCOME_ERRORED: ProductOutcome = "errored"
PRODUCT_OUTCOME_RE_RECORDED: ProductOutcome = "re_recorded"

#: The same vocabulary as a TYPE, so a step cannot declare or record a fifth state.
#: Spelled as literals rather than built from the constants above, matching how
#: ``domain.consumer`` types ``AiJobSpendStatus`` and how ``domain.pseudonym`` types
#: ``ActorKind``: one list, written out, that a reader can check against the
#: migration's CHECK constraint by eye.
ProductOutcome = Literal["completed", "abandoned", "errored", "re_recorded"]

#: The same vocabulary as an ORDERED TUPLE, for the places that have to enumerate it
#: rather than type it: the ``/product/funnel`` route's ``Literal`` cannot be built
#: from the ``Literal`` above, and a test asserts the two agree so a fifth state
#: cannot reach the wire without reaching this list first. The migration's CHECK
#: constraint is the third copy and this one is the one a reader can check by eye
#: against :data:`PRODUCT_OUTCOME_*`.
PRODUCT_OUTCOMES: tuple[ProductOutcome, ...] = (
    PRODUCT_OUTCOME_COMPLETED,
    PRODUCT_OUTCOME_ABANDONED,
    PRODUCT_OUTCOME_ERRORED,
    PRODUCT_OUTCOME_RE_RECORDED,
)

#: The funnel the registry describes today: a patient opening the composer through
#: to a prescription approved or the case closed. Declared as data rather than
#: threaded through every entry so a second funnel is a second constant, not a
#: second rewrite.
FUNNEL_INTAKE = "intake"

#: The two steps that legitimately END a workflow, named rather than matched on
#: position. A funnel that ran to an issued e-prescription and a funnel that ended
#: with the case closed are BOTH successes, and a reader has to be able to tell them
#: apart rather than see one folded into the other's number (#717 decision 23). They
#: are named because the two outcomes are a business fact - an issued prescription and
#: a closed case are different things a practice counts - and not a position in a
#: list, so a step inserted before them must not silently relabel them.
FUNNEL_TERMINAL_PRESCRIPTION = "prescription_approved"
FUNNEL_TERMINAL_CASE_CLOSED = "case_closed"


class ProductStepPayload(BaseModel):
    """The base every funnel-step mirror inherits: the fields the ledger writes.

    A superset, and deliberately so. ``run_handler`` re-validates the dispatched
    producer payload into the mirror before the effect runs, so a mirror that
    declared the producer's exact required fields would raise on any producer that
    omits one - and an event this module must consume must never be the reason a
    consumer transaction dies. Widening to ``None`` is the ADR-0003 pattern already
    used by ``AiJobQueuedTelemetryPayload.task_type``.

    What a missing field costs is bounded and honest: no ``trace_id`` means the row
    carries a derived key instead (see :func:`product_event_keys`), and no
    ``patient_id`` on a machine-driven step means the row records no actor at all -
    which is what ``observability_product_events``' nullable actor pair is for.
    """

    #: Published by the producer when the request was traced. ``None`` for a
    #: producer that does not publish one today; a producer that starts publishing
    #: it needs no consumer change.
    trace_id: str | None = None
    #: The journey/session scope the producer published, when it has one.
    session_key: str | None = None
    #: The identity references a funnel step is attributed to. Hashed before they
    #: are written, never stored raw.
    patient_id: int | None = None
    doctor_id: int | None = None
    #: How long the step's own action took, in SECONDS, when the producer measured
    #: it. Converted to integer milliseconds at the storage seam.
    duration_s: float | None = None


@dataclass(frozen=True)
class ProductStep:
    """A registry entry: one funnel step, the event it is recorded from, and its shape.

    This is the whole of what a step IS. Everything else - which event types get a
    consumer handler, what a ledger row carries, what a daily row aggregates - is
    driven from here, which is what makes adding a step a registry line rather than
    a schema change.

    ``allowed_outcomes`` is the step's DECLARED vocabulary: the outcomes a reader may
    filter this step by. ``outcome`` is what this subscription records for the one
    event it is driven by, and it must be one of the declared outcomes - the guard
    in :func:`register_product_step` is what makes a step that declares a vocabulary
    it never uses impossible.
    """

    funnel: str
    step: str
    event_type: str
    outcome: ProductOutcome
    allowed_outcomes: tuple[ProductOutcome, ...]
    #: Which actor this step is attributed to, or ``None`` for a step a machine
    #: finished with no human behind it. A step that names a kind MUST have the
    #: matching reference on its mirror, so an active-actor count can never be built
    #: from a row that cannot say who it was.
    actor_kind: ActorKind | None = None
    #: Whether this step ENDS a workflow rather than leading to another one. Declared
    #: per step because the intake funnel has TWO legitimate ends - the prescription
    #: approved and the case closed - and a reader walking the funnel needs to know
    #: that they branch from the last step before them rather than sit in a line
    #: behind each other. Without it, ``case_closed`` would be scored as a conversion
    #: of ``prescription_approved``, and a case closed without one would read as the
    #: step after an issued prescription (#717 decision 23).
    terminal: bool = False


#: The live registry, in FUNNEL order - registration order IS the order a patient
#: walks the steps. ``(funnel, step) -> step``, which is the ledger's own grain
#: minus the outcome and the date.
PRODUCT_STEP_REGISTRY: dict[tuple[str, str], ProductStep] = {}

#: ``event_type -> step``. One entry per event type, enforced by
#: :func:`register_product_step`, so one delivery can never be recorded as two
#: steps of the same funnel.
_EVENT_STEP_INDEX: dict[str, ProductStep] = {}


def register_product_step(step: ProductStep) -> ProductStep:
    """Add ``step`` to the registry and return it.

    Two claims are refused rather than silently allowed, because each one quietly
    corrupts a funnel number:

    * a duplicate ``(funnel, step)`` - two entries would write two rows for one
      step and double its count, exactly the failure the rollup's full-row recompute
      cannot repair once it has landed;
    * a second entry for an event type already claimed - one delivery is one moment
      of one journey, so recording it as two steps inflates both conversion and
      abandonment. A product that genuinely needs one event in two funnels gets two
      registries, which is a decision to make on purpose rather than by accident.

    A declared ``outcome`` outside ``allowed_outcomes`` is refused too: a step whose
    vocabulary and recorded outcome disagree describes itself one way and is counted
    another, which is how "which step loses people" quietly answers a different
    question from the one asked.
    """
    scope = (step.funnel, step.step)
    if scope in PRODUCT_STEP_REGISTRY:
        raise ValueError(f"product step {step.funnel}.{step.step} is already registered")
    if step.event_type in _EVENT_STEP_INDEX:
        existing = _EVENT_STEP_INDEX[step.event_type]
        raise ValueError(
            f"event type {step.event_type!r} is already registered as product step "
            f"{existing.funnel}.{existing.step}"
        )
    if step.outcome not in step.allowed_outcomes:
        raise ValueError(
            f"product step {step.funnel}.{step.step} records outcome {step.outcome!r}, "
            "which it does not declare in allowed_outcomes"
        )
    PRODUCT_STEP_REGISTRY[scope] = step
    _EVENT_STEP_INDEX[step.event_type] = step
    return step


def product_steps() -> tuple[ProductStep, ...]:
    """Every registered step, in funnel order (registration order)."""
    return tuple(PRODUCT_STEP_REGISTRY.values())


def product_step_for_event(event_type: str) -> ProductStep | None:
    """The step ``event_type`` is recorded as, or ``None`` when it is not consumed."""
    return _EVENT_STEP_INDEX.get(event_type)


#: Separates the derived key from every other digest in the codebase, so a step key
#: can never collide with an actor key or an AI-job spend digest.
_STEP_KEY_DOMAIN = "caresetu.observability.product.step.v1"


def derived_step_key(event_id: UUID) -> str:
    """The stable trace/session key for a step whose producer published no trace.

    Only ``intake.composer_opened`` publishes a ``trace_id`` today (#721); the
    intake and care producers do not carry one on the events this module consumes,
    and widening their payload contracts is theirs to make, not this ticket's to
    invent. The ledger's ``trace_id``/``session_key`` are NOT NULL precisely because
    an untraceable row is not useful - so a step with no published trace gets a
    derived key rather than an empty column.

    What it IS: a deterministic function of the delivered ``event_id``, so it is the
    same on every replay and joins this row to its own delivery. What it is NOT: a
    tracing-backend identifier, and nothing offers a deeplink built from one. When a
    producer starts publishing a trace the published value replaces it on the next
    delivery, with no schema change and no read-side branch.
    """
    return hashlib.sha256(f"{_STEP_KEY_DOMAIN}:{event_id}".encode()).hexdigest()


def product_event_keys(payload: ProductStepPayload, *, event_id: UUID) -> tuple[str, str]:
    """The ``(trace_id, session_key)`` pair one delivery's ledger row carries.

    The published trace wins, so the join key the operator jumps to the tracing
    backend with is the real one whenever the producer published it. The session key
    falls back to the trace, which is the platform's own current session scope
    (#721): ``session_key`` and ``trace_id`` coincide for a traced step, and stay
    separate columns because they answer separate questions - which request to jump
    to versus which steps belong to one session.

    A step-to-step gap is therefore measured from the ledger's own timestamps, never
    assumed from this key: it groups one request, not one journey.
    """
    derived = derived_step_key(event_id)
    trace_id = (payload.trace_id or "").strip() or derived
    session_key = (payload.session_key or "").strip() or trace_id
    return trace_id, session_key


def duration_ms_of(payload: ProductStepPayload) -> int | None:
    """The step's own duration in whole milliseconds, or ``None`` when unmeasured.

    Not every step marks a span, and a NULL says so; a zero would read as a step
    that took no time at all. Negative durations cannot happen and are clamped
    rather than rejected, because the column's own CHECK would reject them and the
    whole transaction with them.
    """
    if payload.duration_s is None:
        return None
    return max(0, round(payload.duration_s * 1000))


@dataclass(frozen=True)
class ProductEventFact:
    """One ``observability_product_events`` row, as the daily rollup reads it.

    The ledger row reduced to what the aggregate needs: enough to count an event,
    count the actor behind it, and total its duration, and nothing else.
    """

    occurred_at: datetime
    funnel: str
    step: str
    outcome: ProductOutcome
    actor_kind: ActorKind | None
    actor_key: str | None
    duration_ms: int | None


@dataclass(frozen=True)
class ProductDaily:
    """One recomputed ``(funnel, step, outcome)`` day row of ``observability_product_daily``.

    The table's UNIQUE key is ``(event_date, funnel, step, outcome)``;
    ``event_date`` is supplied by the adapter, so this value carries the other three
    plus the four counters.

    **Counters only.** Abandonment rate, step-to-step conversion and success rate
    are read-time divisions over exactly these columns (#740), so none of them is a
    column here: a stored rate would be a second source of truth that goes stale the
    moment the day is recomputed.

    ``actor_count`` counts DISTINCT actor keys, which is not the same as the event
    count - one patient who opened the composer and submitted is two events and one
    active actor - so it is derived here rather than being summed from a column that
    does not exist.
    """

    funnel: str
    step: str
    outcome: ProductOutcome
    events: int
    actor_count: int
    total_duration_ms: int
    duration_samples: int


@dataclass
class _ScopeTotals:
    """The running counters for one ``(funnel, step, outcome)`` scope."""

    events: int = 0
    actors: set[str] = field(default_factory=set)
    total_duration_ms: int = 0
    duration_samples: int = 0

    def add(self, fact: ProductEventFact) -> None:
        self.events += 1
        if fact.actor_kind is not None and fact.actor_key is not None:
            # Both or neither, mirroring the ledger's own CHECK: a key with no kind
            # behind it would inflate the distinct-actor count with something that is
            # not an actor.
            self.actors.add(fact.actor_key)
        if fact.duration_ms is not None:
            self.total_duration_ms += fact.duration_ms
            self.duration_samples += 1


def _facts_on(events: Sequence[ProductEventFact], target_date: date) -> Sequence[ProductEventFact]:
    """The facts that happened ON ``target_date``, in UTC.

    The adapter selects one day already, so this is a guard rather than a filter: a
    row filed under the wrong day would otherwise be counted into whichever day the
    pass happened to be rolling, and two passes would then disagree about it.
    """
    return tuple(fact for fact in events if fact.occurred_at.date() == target_date)


def build_product_daily(
    *, events: Sequence[ProductEventFact], target_date: date
) -> tuple[ProductDaily, ...]:
    """Recompute one day's per-step product aggregate from that day's ledger rows.

    Every returned row is the WHOLE figure for its scope, derived from the day's
    source rows and nothing else: the adapter upserts it on the table's UNIQUE key,
    so a second pass over the same data lands on the identical row rather than adding
    to it. That is the property a late-arriving funnel step depends on - an
    incrementing rollup could never add a step that was written after the first pass
    ran.

    The output is sorted by ``(funnel, step, outcome)`` so two passes over the same
    rows produce the same rows in the same order - order must not depend on arrival
    for a recompute to be verifiable.
    """
    totals: dict[tuple[str, str, ProductOutcome], _ScopeTotals] = {}
    for fact in _facts_on(events, target_date):
        scope = (fact.funnel, fact.step, fact.outcome)
        totals.setdefault(scope, _ScopeTotals()).add(fact)
    return tuple(
        ProductDaily(
            funnel=scope[0],
            step=scope[1],
            outcome=scope[2],
            events=total.events,
            actor_count=len(total.actors),
            total_duration_ms=total.total_duration_ms,
            duration_samples=total.duration_samples,
        )
        for scope, total in sorted(totals.items())
    )


# --------------------------------------------------------------------- the registry

#: The intake funnel, declared in the order a patient walks it. Every entry below is
#: one registry line; adding a ninth step is one more.

register_product_step(
    ProductStep(
        funnel=FUNNEL_INTAKE,
        step="composer_opened",
        event_type=EVENT_INTAKE_COMPOSER_OPENED,
        outcome=PRODUCT_OUTCOME_COMPLETED,
        # All three, because this is the funnel's HEAD: a patient who opens the
        # composer and walks away is an ABANDONMENT of the entry step, and a capture
        # that fails under them is an ERROR - the two must never share a number.
        allowed_outcomes=(
            PRODUCT_OUTCOME_COMPLETED,
            PRODUCT_OUTCOME_ABANDONED,
            PRODUCT_OUTCOME_ERRORED,
        ),
        actor_kind="patient",
    )
)

register_product_step(
    ProductStep(
        funnel=FUNNEL_INTAKE,
        step="intake_captured",
        event_type=EVENT_INTAKE_CAPTURED,
        outcome=PRODUCT_OUTCOME_COMPLETED,
        allowed_outcomes=(PRODUCT_OUTCOME_COMPLETED, PRODUCT_OUTCOME_ERRORED),
        actor_kind="patient",
    )
)

register_product_step(
    ProductStep(
        funnel=FUNNEL_INTAKE,
        step="pre_summary_ready",
        event_type=EVENT_PRE_SUMMARY_READY,
        outcome=PRODUCT_OUTCOME_COMPLETED,
        allowed_outcomes=(PRODUCT_OUTCOME_COMPLETED, PRODUCT_OUTCOME_ERRORED),
        actor_kind="patient",
    )
)

register_product_step(
    ProductStep(
        funnel=FUNNEL_INTAKE,
        step="consult_complete",
        event_type=EVENT_CASE_CONSULT_COMPLETE,
        outcome=PRODUCT_OUTCOME_COMPLETED,
        allowed_outcomes=(
            PRODUCT_OUTCOME_COMPLETED,
            PRODUCT_OUTCOME_ABANDONED,
            PRODUCT_OUTCOME_ERRORED,
        ),
        # The DOCTOR, not the patient: this is the clinical action that makes an
        # active-actor count a people-shaped one rather than a login count in
        # disguise, and a doctor's day has to be countable for that to be true.
        actor_kind="doctor",
    )
)

register_product_step(
    ProductStep(
        funnel=FUNNEL_INTAKE,
        step="prescription_drafted",
        event_type=EVENT_PRESCRIPTION_DRAFT_CREATED,
        outcome=PRODUCT_OUTCOME_COMPLETED,
        allowed_outcomes=(PRODUCT_OUTCOME_COMPLETED, PRODUCT_OUTCOME_ERRORED),
        actor_kind="doctor",
    )
)

register_product_step(
    ProductStep(
        funnel=FUNNEL_INTAKE,
        step="prescription_approved",
        event_type=EVENT_PRESCRIPTION_APPROVED,
        outcome=PRODUCT_OUTCOME_COMPLETED,
        allowed_outcomes=(PRODUCT_OUTCOME_COMPLETED,),
        actor_kind="doctor",
        # One of the funnel's two legitimate ENDS: the prescription was issued. A step
        # that declares only ``completed`` cannot end any other way, which is what
        # makes it a clean success terminal rather than a branch.
        terminal=True,
    )
)

register_product_step(
    ProductStep(
        funnel=FUNNEL_INTAKE,
        step="case_closed",
        event_type=EVENT_CASE_CLOSED,
        outcome=PRODUCT_OUTCOME_COMPLETED,
        allowed_outcomes=(
            PRODUCT_OUTCOME_COMPLETED,
            PRODUCT_OUTCOME_ABANDONED,
            PRODUCT_OUTCOME_ERRORED,
        ),
        actor_kind="doctor",
        # The OTHER legitimate end, and a case closed without an e-prescription is a
        # completed consultation rather than a drop-off. It is terminal for the same
        # reason ``prescription_approved`` is: nothing follows it in the walk.
        terminal=True,
    )
)

register_product_step(
    ProductStep(
        funnel=FUNNEL_INTAKE,
        step="re_recorded",
        event_type=EVENT_INTAKE_RETRY_REQUESTED,
        outcome=PRODUCT_OUTCOME_RE_RECORDED,
        # Exactly one, by decision 25. The re-record is never scored against the
        # original attempt, so a step whose whole vocabulary were ``completed``
        # and ``errored`` would be counting a correction as a failure.
        allowed_outcomes=(PRODUCT_OUTCOME_RE_RECORDED,),
        # No actor kind: ``intake.retry_requested`` carries no identity reference -
        # it names an intake, a round and a reason. The ledger's nullable actor pair
        # exists for exactly this, and inventing a patient key would be inventing an
        # identity the producer never asserted.
        actor_kind=None,
    )
)


# ------------------------------------------------------------- the funnel's shape


def registered_steps(funnel: str = FUNNEL_INTAKE) -> tuple[ProductStep, ...]:
    """Every step registered for ``funnel``, in registration order.

    The whole registry as one question asks it: :func:`funnel_stages` answers "which
    steps does a reader walk" and this answers "which steps exist", and a reader that
    needs the second - to count every row the ledger holds for the funnel, including
    the ones no journey walks through - must not re-derive it by filtering the registry
    itself.
    """
    return tuple(step for (scope, _), step in PRODUCT_STEP_REGISTRY.items() if scope == funnel)


def funnel_stages(funnel: str = FUNNEL_INTAKE) -> tuple[ProductStep, ...]:
    """The steps a reader WALKS, in the order they are walked.

    Not the same list as :func:`product_steps`, for two reasons, and both of them are
    what keeps a funnel from scoring something twice:

    * a step that records the ``re_recorded`` outcome is not a stage. The re-record is
      a correction of an attempt, not a stage the attempt passes through, so counting
      it as one would either add a stage after every terminal or push the walk's end
      past the ends of the journey. It stays registered - its rows are still written
      and still counted - and a read reports it on its own;
    * the terminal steps stay IN the walk, because a funnel whose reader cannot see
      the step a workflow ended on cannot tell a completed consultation from an
      abandoned one. They are flagged ``terminal`` rather than removed, so
      :func:`stage_predecessor` knows they branch rather than queue.

    Registration order is walk order, the same claim :func:`product_steps` makes and
    for the same reason: the registry IS the funnel, so a step inserted in the wrong
    place is a one-line mistake rather than a set of queries that quietly disagree.
    """
    return tuple(
        step for step in registered_steps(funnel) if step.outcome != PRODUCT_OUTCOME_RE_RECORDED
    )


def stage_predecessor(
    step: ProductStep, stages: Sequence[ProductStep] | None = None
) -> ProductStep | None:
    """The step whose count is this one's conversion denominator, or ``None``.

    **This is the denominator convention of the funnel read, stated in one place
    rather than chosen per query.** A step's denominator is the nearest step BEFORE it
    in the walk that is not itself terminal - so the first stage has none, and both
    terminals share the last non-terminal stage as theirs.

    Terminal steps are skipped rather than used because they end a branch: with
    ``prescription_approved`` as the denominator of ``case_closed``, every case closed
    without an issued prescription would read as a step after one, and the funnel
    would score a legitimate end as a drop-off. That is the conflation decision 23
    exists to prevent, and it is why ``terminal`` is declared on the step rather than
    inferred from position.

    The convention does NOT require a step to have passed its predecessor. The ledger
    records what happened, not a promise about order, and a step reached without the
    previous one produces a conversion above ``1`` rather than being clamped - a
    number above one is a fact about the window, and silently capping it is how a
    funnel starts lying.
    """
    walk = tuple(stages) if stages is not None else funnel_stages(step.funnel)
    names = [stage.step for stage in walk]
    try:
        index = names.index(step.step)
    except ValueError:
        return None
    for candidate in reversed(walk[:index]):
        if not candidate.terminal:
            return candidate
    return None
