# Brief - #755 Docs reconciliation: event registry, plan status, traceability

**Ticket:** #755 · **Parent:** #717 · **Refreshed:** 2026-10-14
**Reading surface:** ~4K tokens (budget 10K) - within budget

## Scope

Reconcile the documentation with what shipped: register every event this work added in the event registry, record Batch 3 as delivered in the phase plan, and carry the new features in the traceability matrices. An unregistered event name is an invented event name.

- [ ] The event registry records every event this work added - the care-attributed event, the composer-opened entry step, the AI-job-queued event - with their payload fields and subscribers.
- [ ] The event registry's footnotes record the widened AI job payloads, including the patient, the nullable doctor and the trace identifier.
- [ ] The phase plan records Batch 3 as delivered and what it superseded.
- [ ] The traceability matrices carry the new features and phase entries.
- [ ] Every registered event name matches a name actually published; no invented name or module link remains.

## Read-list (in order)

1. The event registry section of `docs/architecture/internal-modules.md` - the table format, the subscriber column convention, and the prose footnotes beneath it that pin payload fields. (~1K)
2. The four events as actually published: the care-attributed event (#720), the composer entry step (#721), the AI-job-queued event (#729), and the widened AI job payloads (#719). Read them from the producers; do not reconstruct them from memory or from the tickets. (~0.8K)
3. The phase plan's batch sections, to see how Batch 1 recorded itself as delivered and what shape a Batch 3 entry takes. (~0.6K)
4. The traceability matrices - the cross-reference sections of the module architecture doc and the roadmap, and which rows the new features need. (~0.8K)
5. The navigation guide's document inventory, in case a new document needs listing. (~0.4K)

## Do NOT read

- `docs/archive/`.
- Source code for this wave beyond the four event producers named above.
- The frontend, the vendor assets, the design records (#754) beyond the traceability rows they need.

## Baseline verify (must pass before the first edit)

- `npm run lint`

## Done-verify (acceptance criteria → commands)

- `npm run lint`
- A name-by-name check that each event in the registry resolves to a published event type, and each published event type appears in the registry.

## Handoff notes

- Three of the four events were registered in their own tickets (#720, #721, #729). This ticket reconciles rather than adds - check before writing, or you will create a duplicate registry row.
- The registry is the source of truth and it is read by other people to learn what events exist. An entry that names a payload field that was never published is worse than a missing entry.
- Batch 3 "supersedes" the deferred Batch 2 scope; say precisely which parts of Batch 2 remain deferred, so the next reader does not think the settings surface or operator tiers landed.
- Keep it short. This is a documentation ticket and the whole value is in being accurate, not exhaustive.
