# Brief - 08 Counterparty label gets its three-step fallback

**Ticket:** #653 · **Parent:** #645 · **Refreshed:** 2026-10-06
**Reading surface:** ~2K tokens (budget 10K) - well within budget

## Scope

The helper that labels a consent counterparty stops handing a patient a database key. It resolves in three steps: the display name the backend resolved, then a type-derived label (Doctor / Lab / Pharmacy), and only if both are absent the raw id. The type-derived step is what guarantees no opaque identifier is ever the only thing a patient is shown.

The AI intake pseudo-counterparty is the trap. It is recorded under the doctor counterparty type by the AI egress path, so a naive type-derived step would render a machine disclosure as a clinician's. The helper must recognise that counterparty and read it as a branded service, so a patient understands a machine read their intake rather than believing a doctor did. The existing initials helper stays unchanged and derives from whatever the chain produced.

## Acceptance criteria

- [ ] The label helper resolves in three steps: resolved display name, then type-derived label, then the raw id only when both are absent.
- [ ] The step-two label covers doctor, lab, and chemist in words.
- [ ] The AI intake pseudo-counterparty reads as a branded service label and never as a doctor, regardless of the counterparty type it was recorded under.
- [ ] The initials helper derives from whatever the three-step chain produced, and is unchanged in behaviour.
- [ ] A direct unit test covers all three steps, each counterparty type, the AI pseudo-counterparty specifically, and the initials derived from each.
- [ ] Every new label ships in English and Hindi.

## Read-list (in order)

1. The `#645` spec's "Consent counterparty display names" block, specifically the paragraph beginning "The frontend keeps a three-step fallback" and the following line about the AI pseudo-counterparty never rendering as a doctor. (~400 tokens)
2. The consent view helper module **in full** - it is 25 lines. The current `counterpartyLabel` returns the id verbatim and its docstring is the comment admitting the ids are opaque and that name resolution "lands in a later phase". That comment is what this ticket makes true; replace it. (~300 tokens)
3. The consent API client's read models - the consent read and the egress-log entry, for the display-name field's exact name and its nullability. From #648's diff plus the client's existing type declarations. (~400 tokens)
4. The dictionary file's consent-log namespace in **both** locales - where the doctor / lab / pharmacy and AI-service strings belong, and whether a suitable namespace already exists or a new one is needed. (~600 tokens)
5. The AI intake egress counterparty id constant on the backend, for the exact string. Read the constant, not the module. (~100 tokens)

## Do NOT read

- `docs/archive/`.
- The consent-log page, the patient profile consent panel, and the action-required card - all three consume this helper, but #654 rewires the first and leaves the others alone. You are changing the helper; you are not changing its call sites this ticket.
- The backend consent facade's resolution rules (#649). You are a **consumer** of the resolved field.
- The backend beyond the one id constant.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - expect **1 failed | 2024 passed**, the single pre-existing failure being `record/page.test.tsx > RecordPage access history > shows an empty state when there is no access history`. It fails on the untouched tree.
- `npm run typecheck` - **currently green.**

#648 must have landed (the display-name field is on the wire). If it has not, stop: the helper would have nothing to read as its first step.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` - the new helper unit tests green. Note there is **no** existing suite for this helper module, so this ticket creates the first one.
- `npm run typecheck` - `tsc --noEmit` is the bilingual gate.
- `npm run lint`

## Handoff notes

- **The helper has no test file today.** Its behaviour is only covered transitively through the consent-log page suite. The gap the spec names is exactly this: a helper whose step ordering can silently regress. Create the suite.
- **The trap, restated so it cannot be misread.** `intake-ai` is recorded under the `doctor` counterparty type by the AI egress path. A type-derived step that maps `doctor` → "Doctor" and is reached _before_ an id check will label a machine as a clinician. The AI check must precede the type branch in this helper, for the same reason #649 puts it first in the backend resolver. The two must agree on what that row says.
- **The raw id is the last resort, not the default.** Keeping the id as step three is deliberate: an empty label would render a blank avatar and a blank name. But it must be _unreachable in practice_ for every counterparty type the product currently records - doctor, lab, chemist, and the AI pseudo-counterparty. Add a test that asserts no current type falls through to it.
- **The initials helper stays as it is.** It already takes whatever label string it is handed. Do not fork it and do not give it a second source of truth - the spec's point is that the chain produces one label and everything downstream reads that.
- **Two more consumers exist and are deliberately untouched.** The patient profile consent panel and the action-required card both call these helpers. They will benefit from the chain for free - that is a consequence, not a change to make in this ticket.
- **Bilingual parity is enforced, not requested.** The dictionary is typed as a record over both languages, so adding a key to English and forgetting Hindi is a compile error. The runtime parity test is the belt to that braces.
