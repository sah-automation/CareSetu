# ADR-0030: Service level objectives, formalised from the existing requirements, with alerting on symptoms

**Status:** accepted
**Date:** 2026-10-21
**Decides:** That the platform's service level objectives are the six already named in `plan-phase14-observability.md` §11, each traceable to an existing non-functional requirement or module latency SLA, and that an alert fires on a user-facing symptom rather than on an internal cause.
**Traceability:** `plan-phase14-observability.md` §11; spec #717 decision 42 and user story 117; parent #717; tickets #728, #729, #733, #734, #748, #754. Related: `ADR-0024` (the hybrid free-tier topology), `ADR-0027` (the attribution model), `ADR-0029` (the console/Grafana split), `NFR-001`, `NFR-003`, `NFR-004`, `error-handling-observability.md` §5.1, §5.2, `internal-modules.md` §3.14.

## Context

The plan closed Batch 1 with the objectives named but not formalised: "Define SLOs from existing NFRs and whitebox latency SLAs: auth `validate_token` p95 < 100 ms, `verify_otp` p95 < 400 ms, directory search p95 < 250 ms, AI call p95 <= 30 s, care-loop latency (`KPI-008`), error rate < 1%." The standard restated the same six in a table so the standard is checkable on its own, and left the question of what an alert is allowed to fire on unstated.

That question is the one that decides whether an operator's alert feed is worth reading. A platform can page on `validate_token` at 100 ms and be technically right and practically useless: no user experiences a token validation, they experience the thing the token validation was standing in front of. The mirror failure is worse: an alert on an internal cause that happens to correlate with real trouble, which trains the operator to ignore it.

The objectives themselves are not a decision this record makes. Every target below already exists in the PRD, in a module's latency SLA, or in the plan. A new target would be a new decision and would need its own discussion.

## Decision

### D1 - The objective set is the six already named, and each one names its source

| #   | Objective                                  | Target                      | Source of the target                                                        | Window it is measured over                             | Figure measured from              | Alert kind                         |
| :-- | :----------------------------------------- | :-------------------------- | :-------------------------------------------------------------------------- | :----------------------------------------------------- | :-------------------------------- | :--------------------------------- |
| 1   | Auth - token validation (`validate_token`) | p95 < 100 ms                | `internal-modules.md` §3.1 (MOD-001) latency SLA                            | the dashboard window, `now-6h` by default              | request-path server span          | none, and deliberately so (D4)     |
| 2   | Auth - OTP verification (`verify_otp`)     | p95 < 400 ms                | `internal-modules.md` §3.1 (MOD-001) latency SLA                            | the dashboard window, `now-6h` by default              | request-path server span          | none, and deliberately so (D4)     |
| 3   | Directory search                           | p95 < 250 ms (cached)       | `internal-modules.md` §3.2 (MOD-002) latency SLA                            | the dashboard window, `now-6h` by default              | request-path server span          | none, and deliberately so (D4)     |
| 4   | AI call, end to end (provider included)    | p95 <= 30 s                 | `internal-modules.md` §3.5 (MOD-005) latency SLA                            | the rolled day, as the provider-health window ranks it | provider health `p95_duration_ms` | `latency_objective_breach`         |
| 5   | Care-loop latency (`KPI-008`)              | median <= 7 days (proposed) | PRD KPI-008                                                                 | a 30-day cohort window                                 | stage timestamp deltas            | none: tracked per stage, not paged |
| 6   | Error rate (5xx share of requests)         | < 1%                        | `plan-phase14-observability.md` §11, `error-handling-observability.md` §5.1 | the rolled day, silent below 100 requests              | `observability_http_minute`       | `error_rate_high`                  |

No target in this table is new. Where a target is marked "proposed" in its source, it stays proposed here.

**The window is part of the objective, and it introduces no new number.** A target with no window is not falsifiable: "< 1% error rate" says nothing about which slice of requests it speaks about. Every window above is the one the platform already measures over - the rolled day for the two alerts, the dashboard's own window for the three request-path percentiles, the product window for the care loop - so formalising the objectives names the windows the implementation already uses rather than inventing a second set. The one window that is still a free choice is the 6-hour default on rows 1 to 3, and those three rows do not page, so the choice costs nothing until someone wants them to.

### D2 - The other named targets stay where they are, and this record says so explicitly

The following are real targets and are **not** platform objectives. Listing them here is what stops a later reader from promoting one into an alert without a decision:

| Target                                                                                                                                                                                                                                | Source                                                  | Why it is not a platform objective                                                                                             |
| :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | :------------------------------------------------------ | :----------------------------------------------------------------------------------------------------------------------------- |
| Consent check (`check_consent`) p95 < 50 ms; own-record view p95 < 250 ms; consented-history read p95 < 300 ms; capture ack p95 < 2 s; handshake and approval p95 < 300 ms; operator read APIs p95 < 500 ms; audit query p95 < 500 ms | the per-module latency SLAs in `internal-modules.md` §3 | They allocate a budget to a module, not a promise to a user. The platform-level objectives above are the ones a user waits on. |
| Initial page load <= 5 s on 4G; page weight <= 1.5 MB                                                                                                                                                                                 | `NFR-003`                                               | A frontend budget, verified by the frontend suite and the bundle gate, not a server-side signal to page on.                    |
| Best-effort availability, no uptime SLA; RPO <= 24 h                                                                                                                                                                                  | `NFR-004`                                               | See D5.                                                                                                                        |
| Total monthly operating, hosting and AI spend <= ₹2,000                                                                                                                                                                               | `NFR-001`                                               | A budget, enforced by the budget meter and the cost-outlier alert rather than by a latency or error objective.                 |

### D3 - An alert fires on a symptom, and the symptom is named

The rule: **an alert fires on something a user, the business or the operator experiences, and never on an internal cause that happens to be measurable.** The alert kinds and the symptom each one measures:

Every in-app kind named here is a value the `observability_alert_events.kind` column already carries, so this table can be checked against the schema rather than trusted. The last row is the one exception and it is not an in-app kind: it is a Grafana rule, because the thing it watches is the capture path rather than a row in the feed.

| Alert kind                                                         | The symptom it names                                                                  | Measured from                                                                                  |
| :----------------------------------------------------------------- | :------------------------------------------------------------------------------------ | :--------------------------------------------------------------------------------------------- |
| `error_rate_high`                                                  | requests are failing                                                                  | the platform's own 5xx share of `observability_http_minute` against the `< 1%` objective       |
| `latency_objective_breach`                                         | the AI work is not finishing in the time a patient will wait                          | the AI call end to end, provider included, against the `p95 <= 30 s` objective                 |
| `provider_rate_limited`                                            | the upstream is refusing service                                                      | the quota refusals the degraded-provider board already counts                                  |
| `provider_health_drop`                                             | an upstream has degraded                                                              | its success rate and latency, and it never auto-resolves, so it cannot quietly leave the board |
| `queue_age`                                                        | work is piling up and not draining                                                    | the age of the oldest still-open job                                                           |
| `cost_outlier`                                                     | one actor's spend has departed from its own history                                   | one actor's day against that same actor's trailing seven-day average                           |
| `ai_budget`                                                        | spend is approaching the cap                                                          | the budget meter against `NFR-001`                                                             |
| `outbox_backlog`, `breaker_open`, `outbox_dead_letter`             | delivery is not keeping up, an upstream is being held off, work was given up on       | the module's own aggregates                                                                    |
| `audit_tamper`                                                     | the audit trail reports tampering                                                     | the `audit.tamper_detected` event                                                              |
| error capture stalled (Grafana rule `caresetu-error-capture-dead`) | the measurement itself is dead, so an empty error feed would read as a healthy system | the absence of recorded requests over the window                                               |

The feed also carries kinds that are records rather than pages - `ai_egress` says an egress happened and is there to be read, not to wake anyone.

Two details of `error_rate_high` are deliberate and belong to the symptom rule rather than to the threshold: it is measured over the **whole platform** rather than per route, because the objective is stated over all requests; and it is silent below a **floor of 100 requests**, because a quiet night carrying three requests must not read as a 33% outage. It fires strictly above 1%, because the objective reads "< 1%".

### D4 - Internal causes are measured and shown, never paged

`validate_token` at 100 ms and `check_consent` at 50 ms are the clearest examples. Both are real budgets, both are measured, both appear in the latency panel, and neither pages: no user experiences a token validation, and a page on either would be a page on a cause with no symptom behind it. The same applies to a single provider's success rate, an internal function's p95, and any counter's absolute value.

The AI call is the one internal-ish figure that does page, and the reason is that it is not internal. It is worth being precise, because the source is easy to misread: `MOD-005`'s SLA says the LLM call is **async and never in the user-critical path**, so the 30-second figure is not a request blocking on a provider. It is the time the async pipeline takes to turn an intake into a pre-summary or a draft, and it is the same 30 seconds as the pipeline's timeout. When it is breached the symptom is real and it is the work, not the request: the AI-assisted result is not produced, the pipeline degrades to forced doctor review, the patient waits longer for their summary and the doctor has no draft to work from. That is a symptom a patient and a doctor both experience. The figure compared is the same one the provider board already shows, so the alert and the board cannot disagree about the same provider.

Where a provider is merely slow, the symptom is the throttle and the user-visible error, not the success rate. A slow upstream is answered by reading the rate-limit and timeout counts on the board, not by a page on a percentage.

### D5 - The absence of an availability objective is a decision

`NFR-004` states best-effort availability with no uptime SLA, and the plan's objective list has no availability entry. There is therefore no availability objective, no availability alert, and no error-budget burn-down. Availability is covered by the external free uptime monitor probing `GET /health`, which is a different kind of signal: it says the site is down, and it does not page on a percentage of a target that was never set.

### D6 - The measurement's own liveness is alerted

The last row of the table in D3 is the exception that proves the rule: an alert fires when the **instrument** is dead. An empty error feed is ambiguous - a healthy system and a broken capture path look identical - so the capture path has its own liveness signal. Without it, "no errors" would be a false all-clear, and the symptom rule would have produced the opposite of what it was for.

### D7 - Objectives are measured where they outlive the vendor's window, and delivered where the operator is

The figures come from the Postgres `observability` schema, so an objective's history is not bounded by the free metrics tier's fourteen days. Delivery rides the free channels - Grafana Cloud alerting to email or a chat webhook, Sentry alerts - and the in-app `observability_alert_events` feed is the durable operator-visible record, with acknowledgement as an in-app write (`ADR-0029` D7). The alert-rule set is capped at a small deliberate number, so a new rule has to be argued for rather than added.

## Considered options

- **Choose new targets for the objectives.** Rejected - a new target is a new decision, and this record's job is to formalise what already exists.
- **Leave the objectives unwindowed, as the plan left them.** Rejected - a target with no window is not falsifiable. "< 1% error rate" says nothing about which requests it speaks about, and the windows named here are the ones the platform already measures over, so naming them costs no new number.
- **Page on the internal p95s.** Rejected - no user experiences them, and an alert on a cause is an alert that trains the operator to ignore the feed.
- **Treat the AI call p95 as an internal cause because the pipeline is async.** Rejected - async means the request does not block on the provider, not that nobody waits. The same breach degrades the pipeline to forced doctor review, so the work is not done and both the patient and the doctor experience it.
- **Give each route its own error-rate threshold.** Rejected - the objective is stated over all requests, so a per-route threshold would alert on a number nobody promised.
- **Add an availability objective and an uptime alert.** Rejected - `NFR-004` states best-effort availability with no uptime SLA. The external monitor already covers "the site is down".
- **Alert on the absolute cost of one actor.** Rejected - the same money is a heavy patient or a looping caller; only the actor's own history separates them (`ADR-0027` D8).
- **Fire the queue alert on depth.** Rejected - depth is the lagging figure; a queue holding one wedged job never reaches a depth threshold, so the age of the oldest still-open job is the signal (`internal-modules.md` §3.14).
- **Let a provider health drop auto-resolve with the rest of the alerts.** Rejected - a degradation is a transition with no steady state, so it never auto-resolves and a degraded provider cannot quietly leave the board.

## Consequences

- The objective set is six lines, each with a named source. A reader can check any of them against the PRD, a module's latency SLA or the plan without hunting.
- The alert set and the objective set are different sizes, on purpose. Most objectives are measured and displayed but do not page, and several alerts fire on conditions that are not objective breaches at all.
- The latency figure an alert compares and the figure the provider board shows are the same one, so an operator who sees a breach and then opens the board sees one story rather than two.
- A request floor below which the error-rate alert stays silent is part of the symptom rule, and it is a number someone chose. If it is set too high, a real small-scale outage is invisible; too low, a quiet night pages. It is a threshold to revisit, not a constant to forget.
- Objectives survive vendor churn because they are measured in Postgres. A lost vendor loses dimensional detail, never the objective's history.
