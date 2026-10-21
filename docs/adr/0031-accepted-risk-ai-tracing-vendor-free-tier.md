# ADR-0031: Accepted risk - the AI tracing vendor's free tier has no healthcare compliance agreement

**Status:** accepted (risk accepted, 2026-10-21)
**Date:** 2026-10-21
**Decides:** That the AI tracing vendor's free tier - no healthcare compliance agreement, no healthcare data region, two users - is an **accepted risk** with a named mitigation, and that the mitigation is what keeps the exposure at the level it is. A decision to move to a paid tier, a different vendor, or real content in the evaluation pipeline reopens it.
**Traceability:** `plan-phase14-observability.md` §6, §10, §15; spec #717 "latent exposure recorded, not resolved" and the "no paid observability upgrade" exclusion; parent #717; tickets #700, #750, #751, #752. Related: `ADR-0024` (the hybrid free-tier topology, D5, D6), `ADR-0025` (the `observability` schema), `ADR-0029` (the console/Grafana split), `NFR-001`, `NFR-SEC-006`, `error-handling-observability.md` §5 (the redaction and scrub posture), `internal-modules.md` §3.14.

## Context

The platform's AI pipeline runs through a third-party model provider, and its traces go to a second third party, the AI tracing vendor. The vendor's free tier is what `NFR-001` forces us onto, and it has three properties that matter for a healthcare product:

- **No healthcare compliance agreement.** There is no healthcare-specific agreement, and no data-processing terms written for a healthcare controller and processor relationship.
- **No healthcare data region.** The vendor's regions are not scoped to healthcare data, and no contractual promise binds how the data is handled in the region it lands in.
- **Two users.** The free tier seats two people, which is smaller than the trusted operator group.

Against a general vendor, that is a normal free tier. Against a vendor that receives anything about a clinical product's AI pipeline, it is a compliance gap, and it is a gap that the platform chose to walk into knowingly. The question this record answers is not "is the gap bad" but "given the gap, what keeps the exposure at its current level, and what would reopen it".

Two vendor-side deadlines sit alongside the gap and are recorded here so they are not rediscovered under pressure: the vendor's metrics endpoint allows about a hundred requests a day, and its trace-level evaluations are deprecated with a cloud cutover in November 2026, so anything built on them must use observation-level evaluators from the outset.

## Decision

### D1 - The risk is accepted, not resolved

The vendor's free tier stays. This is a decision with a mitigation attached, not an oversight and not a closed question. Nothing in this record asserts that the vendor is compliant, that the gap is theoretical, or that the exposure is zero. It asserts that the platform keeps the exposure small enough to carry while the product is at launch scale, and that the things which would make it larger are individually gated.

### D2 - The mitigation is three named controls, and they are enforced rather than promised

**PHI-free metadata.** Nothing clinical reaches the vendor. The redaction at the structlog processor, the Sentry `before_send` scrub and the OpenTelemetry attribute allow-list keep phone numbers, one-time codes, tokens, free text and raw provider payloads out of every vendor (`ADR-0024` D6, `NFR-SEC-006`).

**An allow-listed span metadata set.** The AI tracing vendor's span metadata is a hard gate, not a convention: the allowed set is exactly `task_type`, `provider`, `model`, `input_tokens`, `output_tokens`, `duration_ms`, `cost_paise`, `confidence`, `status`, the pseudonymous `intake_id` and `ai_job_id`, `trace_id` and `prompt_version`. A key that is not on the list is rejected rather than silently attached, so no transcript text, no patient identity and no raw provider payload can reach a span from an adapter. The gate is what makes the first control testable.

**A synthetic golden dataset.** Every reference transcript, hypothesis and structured field in the evaluation dataset was written by hand for the codebase, so no real clinical content reaches an evaluation pipeline. The dataset is versioned and its version travels with it into the observation metadata, so a score always says which revision of the set it was taken against. It deliberately includes a degraded transcription and two imperfect structuring cases, because evaluators that only ever see perfect examples cannot detect their own regression.

### D3 - Two further controls hold the same line

**Evaluation is deterministic code, not a model.** The evaluators compute scores in code over the synthetic dataset, so evaluation costs no inference money and sends nothing to a second model provider. The richer programme - LLM-as-a-judge, judge-to-human agreement - is deliberately deferred.

**The human signal stays home.** The annotation queue is fed by doctor review outcomes, written as rows in the `observability` schema with the outcome classification and the delivery's trace id, and never with the producer's free-text reason. Human judgement becomes evaluation data without clinical content moving to the vendor.

### D4 - The vendor's metrics reach the system of record by batch, never by live query

The daily batch pull makes at most one metrics request per run and writes into the `observability` schema, so the numbers survive the vendor's retention window and the decision data is ours (`ADR-0024` D2). A hundred-request-a-day allowance cannot be spent by a dashboard refresh, and losing the vendor loses dimensional detail rather than the ledger.

### D5 - The constraint the risk rides, and the rule that reopens it

The free tier is not the mitigation; it is the cause of the gap. It is what `NFR-001` and `ADR-0024` D5 force, and those are the constraint that has to be amended first.

**A move to a paid tier is not a mitigation, and it does not close this risk by itself.** It is a new decision with a new cost line, and it requires an amendment to the no-paid-observability constraint before it is even discussable. Only then is the risk re-evaluated against the vendor's actual healthcare terms, region and user count, which may or may not close it.

The risk reopens, and this record has to be re-decided, on any of:

- a decision to move to a paid tier of the AI tracing vendor, or of any observability vendor;
- a change of AI tracing vendor;
- any change to the span metadata allow-list, in particular any widening of it;
- any proposal to run an evaluation on real clinical content, or to send a real transcript to the vendor for any reason;
- a change in the vendor's terms, its data region, or its compliance posture;
- the vendor's deprecation of trace-level evaluations, which forces a cutover to observation-level evaluators and therefore a re-check of what an observation carries.

### D6 - The two-user limit is a consequence, and it shapes the surfaces rather than the data

Two seats is fewer than the trusted operator group, so the vendor's UI cannot be the working surface for observability. That is already the case: the in-app console is the surface operators work in, and the vendor is a deep-link destination for AI traces (`ADR-0029` D1). The limit therefore shapes who can look at what, not what data may go there. It is recorded here because the temptation to solve it by sharing one seat across the operator group is exactly the kind of shortcut that turns a recorded risk into a fresh one.

### D7 - What this record does not do

It does not approve sending PHI to the vendor. It does not claim the vendor is compliant, or that the gap is theoretical. It does not authorise a paid tier. It does not permit an evaluation over real clinical content, and it does not treat the annotation queue as a route for clinical free text. It does not close the question.

## Considered options

- **Self-host the AI tracing vendor.** Rejected - hosting is not free, it exceeds what a single free Render instance can carry, and it puts a clinical-adjacent dataset on infrastructure the platform would then have to secure, patch and back up itself. The exposure does not disappear when the vendor is yours; it changes hands.
- **Move to a paid tier of the same vendor.** Rejected for now, and deferred rather than dismissed: it needs an amendment to `NFR-001` and the no-paid-observability constraint first, and its healthcare terms have not been evaluated.
- **Replace the vendor with one that has a healthcare agreement.** Rejected for now - it is a real option and it is not free, so it is a decision with a cost line and a re-instrumentation, not a switch. It stays on the table behind D5.
- **Send only aggregates to the vendor and nothing else.** Rejected as a mitigation on its own - it does not reduce the exposure of the data already flowing, and it would remove the trace-level detail the AI leg needs to be debuggable. The allow-list achieves the same effect on a per-field basis, which is stronger because it is enforced.
- **Turn the AI tracing vendor off entirely.** Rejected - the AI leg is the part of the pipeline where the cost, the latency and the quality live, and the platform would lose the ability to explain a pre-summary that went wrong. The decision data would survive in Postgres, but the diagnosis would not.

## Consequences

- The exposure is bounded by the allow-list rather than by trust: a key outside the set cannot reach a span, so the worst case is a metadata set that describes cost and latency, not a transcript.
- The platform can keep using a vendor with no healthcare agreement **as long as** the content is metadata and the evaluations are synthetic. The moment either changes, the vendor is out of posture and the risk has reopened.
- The two-user limit keeps the vendor's UI out of the operator workflow. The console stays the surface, which is where the decision data lives anyway.
- A paid-tier decision becomes a documented prerequisite for closing this risk, and a vendor change becomes a re-instrumentation. Both are expensive, which is the correct price of a recorded decision rather than a silent default.
- The November 2026 cutover to observation-level evaluators is a dated obligation on this record, not a surprise.
