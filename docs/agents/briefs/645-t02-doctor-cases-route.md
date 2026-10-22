# Brief - 02 `GET /v1/doctor/cases` route

**Ticket:** #647 · **Parent:** #645 · **Refreshed:** 2026-10-06
**Reading surface:** ~4K tokens (budget 10K) - within budget

## Scope

The partner-authenticated route that serves the doctor's open-cases read, so the doctor console has an HTTP surface for its new cases projection. It resolves the calling doctor through the same route-level helper the patients routes use, sits behind the same gateway stack, and answers in the same error envelope. The route is transport only: it owns no composition, no composition-order decision, and no shape of its own.

## Acceptance criteria

- [ ] A GET route under the doctor namespace serves the cases-list read, resolving the doctor through the existing route-level helper the patients routes use.
- [ ] A successful read answers 200 with the list view, and the row shape is exactly what the facade returns.
- [ ] A non-partner caller is refused with 403 and an unauthenticated caller with 401, in the repo's standard error envelope.
- [ ] A partner who is not a doctor, or who is not active, is refused with 403.
- [ ] The route takes no new query parameters.
- [ ] Route tests drive the real app with a real principal, stubbing only the console facade and the partner facade, following the existing doctor patients route test pattern.

## Read-list (in order)

1. The `#645` spec's "Doctor console cases projection (MOD-012)" block - specifically the two sentences naming the route path, the partner authentication, and the route-level helper. (~300 tokens)
2. The doctor console adapters routes module: the router declaration and its prefix, `_resolve_subject_id`, `_require_doctor`, the patients list / detail / photo route handlers, `register_error_handlers`, and the module constants (`_DEFAULT_PER_PAGE`, `_MAX_PER_PAGE`, `_MAX_SEARCH_LENGTH`, `_CODE_ACCESS_DENIED`, `_LOG_TAG`). (~1.5K)
3. The new cases-list view type in `doctor_models.py` - read from #646's diff, not from the module at large. (~300 tokens)
4. The doctor patients route test in full - the token minter, the bearer helper, the stubbed console and partner facades, and the `_client(...)` builder that swaps `app.state` on a real `create_app`. Copy this harness. (~2K)
5. `DoctorConsoleFacade` - only the new cases method's signature. Do not read its body; the composition order is #646's business. (~150 tokens)

## Do NOT read

- `docs/archive/`.
- The console facade's internals beyond the one method signature. The composition order, the degrade rule, and the ledger discipline are all decided and implemented in #646.
- The care module's routes and schemas - this is an additive read at the doctor namespace and touches no care consumer.
- The frontend app. The client for this endpoint is #652.
- Other modules' routes.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - must be green, and must include #646's new facade cases before you start. If #646 has not landed, this ticket is still blocked: do not start.
- `npm run typecheck` - must be green.

The frontend unit suite has one **pre-existing** failure unrelated to this work: `record/page.test.tsx > RecordPage access history > shows an empty state when there is no access history` cannot find "No access yet.". It fails on the untouched tree; ignore it.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` - the new route cases green, every existing doctor route test still green.
- `npm run typecheck`.
- `npm run lint`.

## Handoff notes

- **The edge guard is a convenience; the facade is the boundary.** `_require_doctor` in the routes module already refuses a non-doctor or inactive partner with `InsufficientScopeError`. That is why the route needs no role logic of its own - and why #646 puts its own active-doctor re-check inside the facade. Do not duplicate the check into the handler.
- **No `run_idempotent` here.** That wrapper is the pattern for the profile _write_ routes. A GET read does not take it.
- **The doctor identity, not the subject id, is what the facade wants.** `_require_doctor` returns `partner.partner_id`, which is what the consent reverse lookup and the attribution ledger both key on. The JWT subject id is a different number and passing it would silently produce an empty list rather than an error.
- **The response model pins the contract.** Declaring `response_model` on the route is what makes the served OpenAPI schema include the new DTOs - which is exactly what #650 exports. Get the decorator right or the slice export fails loudly.
- **Rate limiting.** The gateway stack applies automatically; the profile-photo path allowlist is the only per-path rate-limit entry in this module and this path is not on it. Nothing to add.
