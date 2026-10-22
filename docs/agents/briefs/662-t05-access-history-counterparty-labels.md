# Brief - 05 Access-history rows render the shared three-step counterparty label

**Ticket:** #670 · **Parent:** #662 · **Refreshed:** 2026-10-08
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

"Who accessed my record" rows render through the shared three-step counterparty label fallback exactly as the consent log does: resolved display name, then role word, then raw id. The role word appears as a separate muted line only when it differs from the label, the raw `actor_type` as the identity line is gone, denied rows never show a named individual, and rows keep timestamp, scope prefix, denied badge, and denial reason. The wire guard carries the new `actor_display_name` field; the empty state is unchanged; tests that pinned raw role words are updated.

Acceptance criteria:

- [ ] The wire guard/client type carries the nullable `actor_display_name` field from ticket #668
- [ ] Access-history rows use the shared three-step counterparty label (resolved name -> role word -> raw id), with the AI intake pseudo-counterparty branding rule traveling with the shared helper unchanged
- [ ] The role word renders as a muted line only when it differs from the label; the raw actor type is no longer the identity line
- [ ] A denied row shows no named individual; timestamp, scope prefix, denied badge, and denial reason are unchanged
- [ ] Empty access history still renders the existing empty state
- [ ] Tests that asserted raw role words are updated; `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` pass

## Blocked by

#668 (Access-history API resolves and exposes counterparty display names) - the field must exist on the wire first.

## Read-list (in order)

1. Spec #662 §Solution "Access history: no self rows, real names" - the frontend-rendering Implementation Decisions bullets; user stories 16-24 (~2K)
2. The shared three-step counterparty label helper - `counterpartyLabel` / `counterpartyRole` in the consent view lib (apps/frontend/src/lib/consent/consentView.ts) - the function to call and its rule order; the consent log's usage as the reference call site (~1.2K)
3. The audit API client: `AccessHistoryEntry` type, `isAccessHistoryEntry` guard, `fetchAccessHistory` (apps/frontend/src/lib/audit/api.ts) - add the nullable `actor_display_name` field and guard clause (~0.6K)
4. The record page access-section rendering - the identity line (currently raw `actor_type` with id fallback), row anatomy (timestamp, scope prefix, denied badge, reason), zones, empty/loading states - in `renderAccessSection` of the patient record page (~2K)
5. Record page access-history tests - the fixture builder and the raw role-word assertions (`"doctor"`, `"lab"`) that pin the broken behavior and must be updated (~1.5K)
6. Audit API client tests - wire-contract assertions to extend with the new field (~0.8K)

## Do NOT read

- Backend resolver internals (ticket #668 owns them; only the wire field matters here)
- The accordion extraction (ticket #669) - if #669 lands first, apply this change inside the extracted component instead; if this lands first, #669 moves the fixed code
- Homepage (ticket #671), timeline rendering (ticket #667), dictionaries beyond the `accessHistory` block if new copy is needed
- `docs/archive/`

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - 2148 passed (2026-10-08)
- `npm run lint`, `npm run typecheck` - passed

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` - access tests green under the three-step label, API guard tests green, consent-log tests still green (shared helper untouched in behavior)
- `npm run lint`, `npm run typecheck`

## Handoff notes

- The consent log already renders via `counterpartyLabel` - do not fork a second fallback chain; one labeling voice across consent log, record accordion, and (later) homepage rail is the spec's point.
- Denied rows: `actor_display_name` will be null for patient-type actors by backend design - the label then falls to role word, which for a patient-type actor is itself the identity-type word; never surface a resolved name there.
- Story 24: zero non-self rows must render the existing empty state - do not invent a new empty state.
- Frontend tests currently asserting raw role words are updated as part of the change, not deleted.
