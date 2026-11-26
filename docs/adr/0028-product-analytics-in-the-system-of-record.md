# ADR-0028: Product analytics lives in the system of record, not in a dedicated analytics vendor

**Status:** accepted
**Date:** 2026-10-21
**Decides:** That product analytics is a consumer of the platform's own event stream inside the Postgres `observability` schema - a product event ledger, a step registry, a daily rollup and read-time cohort derivation - and that no dedicated product-analytics vendor is introduced.
**Traceability:** `plan-phase14-observability.md` §11; spec #717 decisions 22, 23, 24, 25, 26 and the "no product-analytics vendor" exclusion; parent #717; tickets #721, #739, #740, #741, #742, #743. Related: `ADR-0024` (the Postgres `observability` schema is the system of record), `ADR-0025` (`MOD-013`), `ADR-0026` (OpenTelemetry), `ADR-0031` (the accepted vendor compliance risk), `NFR-001`, `NFR-SEC-006`, `internal-modules.md` §3.14, §4.2.

## Context

The product lens has to answer three questions an operator actually asks: how many people used the product (daily, weekly and monthly, with stickiness), how much traffic is the platform carrying, and where do workflows die. The last one is a funnel from the moment a patient opens the composer through to an issued e-prescription or a closed case, with per-step completion, abandonment and the thinking time between steps, plus seven- and thirty-day retention cohorts.

The industry-default answer is a product-analytics vendor: PostHog, Amplitude or Mixpanel, each with a generous free tier and a funnel builder. That answer is wrong here, for four reasons that compound.

1. **The free metrics tier's window is shorter than the metric.** Grafana Cloud keeps fourteen days. A monthly active-user count is a thirty-day question, so it is not a slow query in the vendor, it is a question the vendor's window cannot answer at all. The number the business is judged on would have to be computed somewhere else anyway, and computing it somewhere else means keeping the events somewhere else.
2. **A second event pipeline is a second copy of the truth.** The funnel's steps are events the platform already publishes: `intake.composer_opened`, `intake.captured`, `pre_summary.ready`, `case.consult_complete`, `prescription.draft_created`, `prescription.approved`, `case.closed` and `intake.retry_requested`. A vendor would need those events delivered to it as well, which means instrumenting the same producers a second time, with a second SDK, a second delivery path, a second failure mode, and a second set of payload shapes that will drift from the first.
3. **A vendor's data posture is not ours.** The "no PHI in telemetry" rule is enforced by our own machinery - the structlog redaction, the Sentry `before_send` scrub, the OTel attribute allow-list, the Langfuse span-metadata allow-list (`ADR-0024` D6). Those controls are ours to test. Handing clinical-adjacent events to a vendor that has no healthcare compliance agreement and no healthcare data region (the accepted risk in `ADR-0031`) would put the one thing our own tooling guarantees outside the guarantees our tooling covers.
4. **The cost floor forbids the paid tier that would fix the limits.** `NFR-001` caps total monthly spend at ₹2,000 and forbids paid proprietary frameworks at launch. A vendor's paid tier is where the long window, the funnel builder and the cohort analysis live.

The system of record already exists (`ADR-0024` D2), it already holds the cost and quality aggregates, and it already holds the events' consumers. The product lens is the same machinery pointed at a different question.

## Decision

### D1 - Product analytics is a consumer of the platform's own event stream

`MOD-013` subscribes to the eight events above and writes one row per delivery into `observability.observability_product_events`: timestamp, pseudonymous actor key, session key, trace id, funnel name, step, outcome and duration. No domain module is instrumented for analytics, no analytics SDK is embedded anywhere, and there is no second egress path. The producers publish what they already publish; the product lens is a second consumer of the same outbox.

### D2 - The funnel is a registry, not a schema

Funnel steps are registry entries in `modules/observability/domain/product.py`, matching the metric-registry pattern the observability module already uses. Adding a step is a `register_product_step` call and no table change. The registry drives the ledger, the consumer's handler seat and the nightly daily rollup from one list, so a step cannot be counted in one place and forgotten in another.

### D3 - The outcome vocabulary is closed, and two outcomes exist to stop a broken path reading as a normal one

Each step declares the outcomes it may hold, drawn from `completed | abandoned | errored | re_recorded`. A workflow terminated by a degraded fallback scores `errored`, never a quiet abandonment, so a broken path is not scored as a normal drop-off. A re-record is its own outcome, so a corrected attempt is not scored as a failure of the original.

### D4 - The ledger is not the read path

The nightly rollup derives two daily grains from one read of the ledger: `observability_product_daily` (per step: entered, completed, abandoned, errored, re-recorded) and `observability_product_actor_daily` (per actor per day). Long windows and cohorts read the aggregate, so a thirty-day question never scans the raw ledger, which is read once a night by the rollup and by nothing else. The two grains are recomputed from the same read, so the funnel's step counts and its active-actor counts can never describe different journeys.

### D5 - Retention cohorts are derived at read time, and the reason is arithmetic

A cohort is the set of actors whose first recorded qualifying clinical action falls on a given date. The share that came back at seven and thirty days is derived from the per-actor daily aggregate when the read is served; it is not stored. A stored rate would be a second source of truth that disagrees after any recompute.

The step-grain aggregate cannot answer it, and the reason is worth recording because it is the kind of thing that is rediscovered painfully: its `actor_count` is a **distinct** count, and distinctness does not survive being stored. The only way back to a cohort is to sum, and summing double-counts exactly the people who got furthest. A cohort too young to have reached a horizon reports `null` rather than zero, because a horizon nobody has lived through is not a horizon nobody came back to.

### D6 - Active users are computed in Postgres, deliberately

Daily, weekly and monthly active users and the stickiness ratio between them are computed in the `observability` schema, because the free metrics tier's fourteen-day retention makes a monthly count structurally impossible in the vendor. The three counts are distinct actor **sets** over their own rolling windows ending today, not multiples of the daily figure. Throughput and error rate come from the per-minute HTTP counter in the same schema, not from the vendor's metrics.

### D7 - The active-actor set counts a qualifying clinical action, not a login

There is no login, session or logout event in the registry, and adding one is out of scope for this work. The step registry refuses an authentication, session or logout step outright, so no login can ever be counted, even by accident. The active set is therefore the set of actors who did something clinical, which is the question the product manager is actually asking.

### D8 - The funnel's entry step is a real event, and its two caveats are part of the design

`intake.composer_opened` fires when the patient opens the composer, before any capture, because the previous entry step fired in the same transaction as intake capture and could not see a patient who opened the recorder and left. It carries the patient, a session key and a trace id, and no intake reference: no intake row exists yet. It also carries no audio, transcript or typed text.

Two consequences are designed around, not discovered later:

- **The session key is not yet a session.** It is the platform's trace-context session scope, which today is the request, so it equals the trace id and is unique per row. It cannot group two steps of one journey on its own, so a step-to-step gap is measured from the ledger's own `occurred_at` timestamps. When a stable client session key arrives it is a drop-in replacement in the same column, and the read side does not change.
- **A repeat mount is a legitimate second event.** The browser fires on every composer mount, so a reload, a back-navigation or a switch between voice and text each produce a row. No payload field can collapse them, so a conversion rate is folded over the actor plus a time window rather than counted raw.

### D9 - Every funnel number is traceable back to a real journey

The trace id is NOT NULL on every ledger row, so any funnel figure can be walked back to the real user journey. Where the producing event carries no trace id, `MOD-013` records a key derived deterministically from the delivered `event_id`: stable on every replay, joinable to that delivery, and deliberately **not** a tracing-backend identifier. When a producer starts publishing a trace, the published value replaces it with no schema change and no read-side branch.

### D10 - The ledger is PHI-free

Actor keys are pseudonymous, and no clinical content rides the ledger. This is the same posture the rest of the observability schema holds (`ADR-0025` D7), and it is what makes the ledger safe to keep for a month while a vendor-free analytics layer is the only layer that touches it.

## Considered options

- **PostHog, Amplitude or Mixpanel.** Rejected - a second event pipeline for events the platform already publishes, a data posture we do not control, a free tier that cannot answer the monthly question, and a paid tier that `NFR-001` forbids.
- **A second, analytics-specific event pipeline with its own SDK.** Rejected - two payload shapes for the same event drift apart, and the second one bypasses the redaction, the allow-list and the tests that make the first one safe.
- **Grafana as the product analytics store.** Rejected - the vendor's fourteen-day window makes monthly active users and thirty-day cohorts structurally impossible there, and Grafana is a metrics and trace surface, not an event ledger.
- **Add a login event and count active users as logged-in users.** Rejected - out of scope for this work, and it would answer the wrong question: a login is not use. The registry refuses such a step instead.
- **Store the computed cohort rates.** Rejected - a second source of truth that disagrees after any recompute, and distinct counts do not survive being stored.
- **Query the raw ledger for a thirty-day cohort.** Rejected - the ledger is read once a night by the rollup and by nothing else; a cohort question that scans it would turn a dashboard scroll into a full-table scan.
- **Let the funnel's first step be the existing `intake.started`.** Rejected - it fires in the same transaction as intake capture, so a patient who opens the recorder and abandons is invisible and the funnel cannot show the drop-off it exists to show.

## Consequences

- Product analytics adds no new producer instrumentation, no new egress, no vendor and no new recurring spend. It rides the outbox the platform already has.
- The product lens is subject to the same event-completeness rule as the rest of observability: a field a product read needs but no event carries has to be added to a payload or registered as a narrow read-only exception on `ADR-0025`, not read across a schema.
- The product event ledger grows with real usage, in the one database the platform already operates. It is PHI-free, but it is patient-shaped data, so it stays inside the `observability` schema and behind the operator-only reads.
- The retention cohort figures are only as good as the per-actor daily aggregate's completeness. A missing event silently lowers a cohort, which is why the step registry is the single list every effect is driven from.
- The vendor comparison stays honest: if CareSetu ever needs a funnel builder, session replay or experimentation, that is a new decision with a new cost line, and it would have to amend `NFR-001` and the no-paid-observability constraint first - exactly like `ADR-0031`.
