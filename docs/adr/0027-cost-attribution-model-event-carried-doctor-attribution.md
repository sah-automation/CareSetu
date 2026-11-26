# ADR-0027: The cost attribution model - doctor attribution rides an event, not a join

**Status:** accepted
**Date:** 2026-10-21
**Decides:** The Batch 3 cost attribution model - a granular per-job spend ledger in the `observability` schema is the source, a daily per-actor aggregate is derived from it by recomputation, actor keys are pseudonymous, doctor attribution is carried by the `intake.doctor_assigned` event rather than a cross-schema join, and every unit metric is derived at read time rather than stored.
**Traceability:** `plan-phase14-observability.md` §11; spec #717 decisions 3, 5, 6, 7, 8, 9, 10, 11; parent #717; tickets #719, #720, #723, #724, #725, #731, #732, #733. Related: `ADR-0003` (module isolation), `ADR-0002` (transactional outbox), `ADR-0025` (`MOD-013` and the `observability` schema), `NFR-001`, `NFR-SEC-006`, `internal-modules.md` §3.14, §4.2.

## Context

The operator console shows a rupee figure against a cap and nothing that explains it. There is no cost per patient, no cost per doctor, and no way to see the one patient burning the budget before the budget is gone. The arithmetic was not merely missing from the console: it was impossible. The AI job events carried an intake reference and a job reference and nothing else, so no figure could be attributed to a person.

The obvious way to attribute an intake's spend to the doctor who will read it is to join. The care and partner tables know the pairing, and a join would have been one line of SQL. That is exactly what `ADR-0003` forbids: one PostgreSQL instance, one private schema per module, no cross-schema SQL, no cross-schema foreign keys, enforced in CI by a boundary checker and a migration gate. A module that joins across a schema does not become a telemetry module; it becomes a second writer of another module's data, and the isolation the architecture was re-cuttable for is gone.

The second obvious way is to let the domain module publish a "spend" event. That is worse, not better: it makes a domain module a telemetry writer, splits the cost ledger across producers, and puts the money in the same table as the behaviour it describes.

So the pairing has to travel as an event. That is more expensive than a join, and this record exists to say what the extra cost buys and why it is worth paying.

## Decision

### D1 - The granular per-job spend table is the source

`observability.observability_ai_job_spend` holds one row per AI job: usage date, job reference, intake reference, a pseudonymous patient key, a nullable pseudonymous doctor key, provider, model, task type, input and output tokens, cost in paise, status, trace id and a sanitised failure reason. It is a ledger, not a cache. Every figure the business lens reports is computed from these rows, and a per-day aggregate is derived from them by the nightly rollup.

### D2 - The daily aggregate is recomputed, not accumulated

`observability.observability_attribution_daily` is upserted in full for each `(date, actor kind, actor key, provider, model, task type)` scope. It is never incremented. This is the property the late-arriving attribution depends on: an edge that lands after the AI job it explains cannot be added to a counter that has already counted the job, so the next pass re-derives the day and the doctor key is simply there. An accumulating rollup would have to either double-count the day or carry a compensating adjustment, and both are wrong in a way that is invisible until a month's figures are audited.

### D3 - Doctor attribution rides an event, not a join

`MOD-005` publishes `intake.doctor_assigned` in the same transaction as the doctor assignment, carrying the intake, the patient and the doctor. `MOD-013` consumes it and records one row per pick in `observability.observability_care_attribution_edges` (one row per intake, keyed unique on the intake reference). The rollup then resolves the doctor for an intake from that edge, inside its own schema.

The edge holds the intake's **current** truth: a re-pick overwrites it rather than adding a second row, because two rows for one intake would make attribution ambiguous. The overwrite is monotonic in the pick's own timestamp, so a late delivery of a stale pick cannot roll the edge backwards to a doctor the patient has moved on from.

The rule this record fixes: **a consumer learns the intake-to-doctor pairing only because the event said so.** A join to the care or partner schema is not an optimisation to be considered and rejected at the call site; it is a violation of `ADR-0003` and of the module isolation rule, and the boundary checker and the cross-schema foreign key scan both stand between the design and the violation.

Two details of the resolution are deliberate:

- **The edge wins over the job's own key.** A re-pick moves the edge; a drafting job that ran before the re-pick carries the doctor the patient has moved on from. Letting the row's own key win would split one intake's spend across two doctors on the same day and stop the per-patient and per-doctor figures reconciling. The job's own key is the fallback, which covers a pick the edge table has not recorded yet.
- **An unattributed job produces no doctor row at all.** `None` is not written as a placeholder key, so an operator sees the gap instead of reading unattributed spend as attributed.

`ai_job.queued` deliberately carries no doctor at all: at enqueue time no leg knows the doctor, because the drafting doctor lives in the `care` schema, which `MOD-005` cannot read. A nullable field that is null at every producer and read by nobody is a field that lies about its own usefulness.

### D4 - Actor keys are pseudonymous

The patient and doctor keys stored in the observability schema are one-way hashes of the identity reference, not the reference itself. The observability aggregates carry no PHI (`NFR-SEC-006`; `ADR-0025` D7). The key is stable across days, so an operator can follow one actor's spend over a month, and it discloses nothing on its own.

### D5 - One rupee is recorded against two actors, and that is not double counting

Each job contributes to two rows in the daily aggregate: its patient, and the doctor whose case it served. The figures on the two rows are identical. This is one rupee of cost recorded against the two actors the business reads need it against, and it is what lets the per-patient and the per-doctor figures reconcile. Any reader who sums the two columns and calls the result "total spend" is misreading the model, and the business read is where that distinction is stated to the reader.

### D6 - Every unit metric is derived at read time

Cost per thousand input and output tokens, cost per request, cost per completed task, cost per patient, cost per doctor and cost-of-pass (spend divided by successful outcomes) are computed from the daily aggregate when the read is served. None of them is stored. Storing them would create two sources of truth for the same number, and the stored copy would be the one that drifts after any recompute.

### D7 - Revenue and tier are nullable dimensions, and margin says why it is absent

The daily aggregate carries a nullable revenue column and a nullable tier key, both empty today, because no monetization model exists and the PRD defers it. A margin figure returns null with an explicit reason - `revenue_not_captured` when the dimension holds nothing, `revenue_zero` when revenue is captured and is zero - so nobody mistakes a zero for a real margin. Turning monetization on is a data write, not a re-instrumentation.

### D8 - The cost outlier is relative to the actor's own history

The rollup compares one actor's most recent day of spend against that same actor's own trailing seven-day average and raises a cost-outlier alert when the deviation crosses a configured multiple. An absolute rupee cap is deliberately not used here: a legitimately heavy patient and a caller looping one request cost the same money, and only the actor's own history separates them. The absolute cap's job is the budget meter against `NFR-001`, which is a different question. The alert carries both figures and names the actor by its pseudonymous key, so the operator can judge abuse against a one-off.

### D9 - The business read is period-parameterised

One read serves today, week-to-date and month-to-date, selected by a closed period parameter, over the same aggregation. Three separate reads would have triplicated the same query and invited the three to disagree.

## Considered options

- **Join the care or partner schema at read time.** Rejected - a direct violation of `ADR-0003`; the boundary checker and the cross-schema foreign key scan exist to stop exactly this, and a re-cut into services would inherit the coupling. This is the option the whole record is about.
- **Have `MOD-006` publish a doctor-spend event.** Rejected - the doctor does not own the AI spend: the cost is incurred by the pipeline, and the doctor is the reader. It also makes a domain module a telemetry writer, which is the split `MOD-011` and `MOD-013` are careful to keep.
- **Let `MOD-005` write the per-actor spend row itself.** Rejected - two writers of the same table means the ledger can disagree with itself, and the producer cannot see the whole day it is writing into.
- **Store the unit metrics alongside the daily aggregate.** Rejected - two sources of truth for one number, and the stored copy is the one that goes stale.
- **Attribute the whole intake's spend to the doctor at pick time, and reattribute later.** Rejected - the re-attribution is a mutation of a number that has already been reported; recomputing the day from the source rows is the version of that which cannot double-count.
- **Use an absolute spend cap to catch a runaway actor.** Rejected - the absolute cap cannot tell a heavy patient from an abusive one. It is the budget meter's job, not the outlier detector's.

## Consequences

- The design costs more than the join it replaces: a new event, an edge table, a recompute-not-accumulate rollup, and a doctor resolution rule with a precedence. That is the price of keeping the module boundary, and it is the reason the boundary is worth keeping.
- The `care` schema stays unreachable to telemetry, and `MOD-013` remains a terminal consumer that publishes no events of its own (`ADR-0025` D3).
- The per-doctor figures depend on the pick having happened. A patient's spend before a doctor is picked is genuinely unattributed, and it is shown as unattributed rather than spread across doctors.
- A re-pick moves an intake's spend between doctors, because the edge holds the current pairing and the day is re-derived from it. A historical day can therefore move when a patient changes doctor. This is accepted: the alternative, a doctor that never changes, is less true than a number that moves when the truth moves.
- The observability schema grows by two tables and one nullable pair of dimensions. Both migrations are additive on the single-head chain (`npm run migration-check`).
