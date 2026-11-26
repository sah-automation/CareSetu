# Brief - T1 Patient tab bar five-column layout

**Ticket:** #210 · **Parent:** #209 PHASE-3 · **Refreshed:** 2026-08-24
**Reading surface:** ~4.5K tokens (budget 10K) - within budget

## Scope

The live app's mobile bottom tab bar matches the ratified design instead of the current six-column crowding that pushes Start off-center: exactly five columns - Home | Find | Start(center) | Record | More - with Inbox folded inside More. Desktop/tablet navigation unchanged. This is the PLAN.md carry-over fix landing ahead of PHASE-3's frontend so the new Record screen (T7) slots into the final layout.

Acceptance criteria: see #210 body verbatim.

## Read-list (in order)

1. `prototype/PLAN.md` carry-over fix line - the ratified five-column decision + rationale (~0.3K)
2. UI blueprint §5.1 navigation model - the bottom-tabs rule to be amended when implemented (~0.7K)
3. Nav config single source (`NAV_CONFIG` per role) + BottomTabs/AppShell render family - current six-column construction (~2K)
4. Dictionaries nav.\* keys - labels incl. any HI strings (~0.5K)
5. Existing nav unit tests - assertion pattern for config shape (~0.7K)

## Do NOT read

- Any backend code; other phases' UI sections; consent/record screens (later tickets); `docs/archive/`.

## Baseline verify (must pass before the first edit)

Recorded green on 2026-08-24: lint; typecheck; frontend units 442 passed.

For this ticket: `npm run lint`, `npm run typecheck`, `npm run test:unit:frontend`.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` (five-column shape + Inbox-inside-More suites green)
- `npm run typecheck`

## Handoff notes

- Record slot lands now but keeps its soon state until T7 un-soons it - do not remove the flag here.
- Blueprint §5.1 amendment happens when this lands: one-line change noting the ratified five-column patient tab bar.
- Desktop/tablet nav must remain untouched - scope is the mobile bar only.
