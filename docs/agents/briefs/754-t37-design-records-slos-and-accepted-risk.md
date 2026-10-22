# Brief - #754 Design records, service level objectives and the accepted-risk record

**Ticket:** #754 · **Parent:** #717 · **Refreshed:** 2026-10-14
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

Write the three design records this work decided, formalise the service level objectives alerting measures against, and record the AI tracing vendor's compliance gap as an accepted risk with its mitigation. Each is a decision, not an oversight.

- [ ] A design record captures the attribution model and why doctor attribution rides an event rather than a join.
- [ ] A design record captures why product analytics lives in the system of record rather than a dedicated analytics vendor.
- [ ] A design record captures the split of responsibility between the in-app console and Grafana, together with the cardinality firewall that protects the free tier.
- [ ] Service level objectives are formalised from the existing non-functional requirements, and alerting is against the user-facing symptoms rather than internal causes.
- [ ] The AI tracing vendor's free-tier gap - no healthcare compliance agreement, no healthcare data region, two users - is recorded as an accepted risk with its mitigation: PHI-free metadata, a synthetic golden dataset, and an allow-listed span metadata set.
- [ ] Each record is discoverable from the navigation guide, and no record contradicts an accepted earlier decision.

## Read-list (in order)

1. Spec #717 - the "design records to write" note; Implementation Decision 42; the "latent exposure recorded, not resolved" note; the "known ceiling" note. (~1.2K)
2. The existing architecture decision records for the observability topology, the module schema registration and OpenTelemetry adoption - the format, the tone and the boundaries they already fixed. (~1K)
3. `docs/adr/0003-module-database-isolation.md` - the decision the attribution record explains itself against. (~0.4K)
4. The non-functional requirements and the inline latency/error-rate targets the objectives are derived from. Do not invent targets; formalise what already exists. (~0.8K)
5. The risk register or accepted-risk location the PRD uses, if one exists; otherwise the navigation guide's risk table. (~0.4K)
6. The navigation guide's decision-record and document-inventory tables, which are what make a record discoverable. (~0.5K)

## Do NOT read

- Source code for this wave - you are writing records about decisions that have already been made and implemented.
- `docs/archive/`, the frontend, the intake and care modules.

## Baseline verify (must pass before the first edit)

- `npm run lint`

## Done-verify (acceptance criteria → commands)

- `npm run lint`
- A read-through check that each record is linked from the navigation guide and that no two records contradict each other.

## Handoff notes

- These are **records of decisions already taken**, not proposals. If writing one surfaces a decision that was never actually made, that is a finding worth raising on the parent spec - do not quietly resolve it inside a record.
- The attribution record must state the rule it explains: a cross-schema join would have been easier and is forbidden, so the edge rides an event. The reader should understand why the design costs more.
- SLOs are derived, not chosen. Every objective traces to an existing non-functional requirement or a target already named in the plan. A new target is a new decision and needs its own discussion.
- The accepted risk is a risk, not a resolved issue. Write the mitigation and the trigger that would reopen it (moving to a paid tier needs an amendment to the no-paid-observability constraint first).
- No record may contradict an accepted earlier decision. If one seems to, stop and raise it rather than writing a superseding record silently.
