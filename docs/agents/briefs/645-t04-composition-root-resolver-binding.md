# Brief - 04 Composition-root binding of the counterparty-name resolver

**Ticket:** #649 · **Parent:** #645 · **Refreshed:** 2026-10-06
**Reading surface:** ~4K tokens (budget 10K) - within budget

## Scope

The composition root supplies the consent facade's counterparty-name resolver, so the consent module learns a doctor's practice name without importing any other module. The binding reuses the shape the composition root already owns for prescription attribution.

Resolution is ordered, and the order is the point:

1. The AI intake pseudo-counterparty id resolves to a branded service label. It is recorded under the doctor counterparty type by the AI egress path, so this id check must run **before** any type parse - otherwise a machine disclosure renders as a clinician's.
2. A doctor counterparty whose id parses as a partner id resolves through the partner facade's public provider-profile seam and returns the practice name.
3. Lab and chemist counterparties resolve to null for now - those partner phases have not landed. The seam is shaped so adding them later is a resolver change, not a model change.

A partner-profile miss or any resolver exception degrades to null with a warning that names the counterparty type only.

## Acceptance criteria

- [ ] The composition root binds a resolver into the consent facade, built on the same pattern as the existing prescription-attribution name resolver.
- [ ] The AI intake pseudo-counterparty resolves to a branded service label, and the id check runs before the doctor-type parse.
- [ ] A doctor counterparty whose id parses resolves to the practice name from the partner facade's provider-profile seam.
- [ ] Lab and chemist counterparties resolve to null.
- [ ] A partner-profile miss and any resolver exception both degrade to null and log a warning naming the counterparty type only - no counterparty id, no PHI.
- [ ] The consent log still loads end to end when a partner profile cannot be read, so the one surface that proves what was shared never goes blank.
- [ ] An integration test against real PostgreSQL covers the consent read carrying a resolved display name end to end, and the existing counterparty-type isolation still holds.

## Read-list (in order)

1. The `#645` spec's "Consent counterparty display names (MOD-004 + composition root)" block - the four resolution rules in their stated order, and the sentence explaining why the id check precedes the type parse. (~800 tokens)
2. The composition root (`app/main.py`) - the facade wiring block in construction order, the existing attributed-doctor-name resolver closure, and the prescription facade construction that consumes it. That closure is your template: same shape, same two-except degrade, same warning discipline. (~1.8K)
3. `PartnerFacade.get_provider_profile` - signature, the view it returns, and the not-found exception to catch. Read the signature and the exception only. (~300 tokens)
4. The intake module's egress adapter, for the exact AI counterparty id string and where it is written. The constant is the module's; you import it here, at the composition root, which is the only place that may. (~300 tokens)
5. The consent facade constructor from #648's diff - the parameter name you are binding. (~100 tokens)
6. The consent integration tests - the fixtures and the counterparty-type-isolation test that must keep passing. (~1.2K)

## Do NOT read

- `docs/archive/`.
- The partner module's verification, registration, and directory internals. One seam, one exception, one field on the returned view.
- The consent schema and SQL - you are not writing to it.
- The care module, including the prescription facade whose resolver you are mirroring. You read the closure in `main.py`, not the consumer that owns it.
- The frontend app.
- The doctor console module.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - **currently green: 2867 passed.**
- `npm run test:integration` - skips if no local PostgreSQL is reachable; see `tests/integration/README.md`. Record which way it went.
- `npm run typecheck` - **currently green.**

The frontend unit suite has one **pre-existing** failure unrelated to this work: `record/page.test.tsx > RecordPage access history > shows an empty history state` cannot find "No access yet.". It fails on the untouched tree; ignore it.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`
- `npm run test:integration` - the new end-to-end display-name case green, the counterparty-type isolation case still green.
- `npm run typecheck`
- `npm run lint`

## Handoff notes

- **The ordering is the whole ticket.** The AI intake pseudo-counterparty is recorded under the _doctor_ counterparty type. If the doctor-type parse runs first, `intake-ai` either fails to parse and falls through, or - worse - a lenient parse resolves it as a partner. Write the id check first and add a test that fails if you ever move it.
- **The branded label is a service name, not a person's name.** It must read as a machine having read the intake. It ships to the frontend as the resolved display name, which is why #653's frontend fallback also has to recognise this counterparty - the two are deliberately consistent about what that row says.
- **Lab and chemist resolve to null, not to an error.** Those partner phases have not landed. Null is the honest answer and the frontend's type-derived step turns it into "Lab" / "Pharmacy" in words. Adding them later must be a resolver change, not a model change - which is the acceptance criterion that keeps this seam's shape honest.
- **Degrade to null, never raise.** The consent log is the one surface that proves what was shared. A partner outage must not blank it. Every failure path in the closure returns `None`.
- **Warning lines name the type only.** The existing attribution closure logs a partner id; do not copy that part. For this resolver the id is the thing you must not log.
- **The construction order already works.** The consent facade is built before the partner facade is bound into anything else, but your closure only _reads_ `app.state.partner_facade` when called, not when defined. Confirm that ordering holds rather than assuming it.
