# Brief - T01 Prefactor: hoist AuthProvider to root layout

**Ticket:** #192 · **Parent:** #191 PHASE-2.6 · **Refreshed:** 2026-08-22
**Reading surface:** ~3K tokens (budget 10K) - within budget

## Scope

One session source app-wide. The `AuthProvider` context currently mounts only inside the dashboard group layout, so public pages fall back to ad-hoc `readSession()` localStorage checks. Hoist the provider to the root layout so any surface reads session state through shared context, and migrate the two public pages that bypass it onto context. No behaviour or visual change beyond equivalent rendering. This unblocks the homepage header (Login vs Dashboard) and shell work without two tickets colliding on the root layout.

Acceptance criteria (verbatim):

- [ ] Public pages render their auth entry truthfully from shared context (signed-out shows Login, signed-in shows Dashboard-equivalent state)
- [ ] Patient login and choose-role pages no longer read session storage directly; grep finds no ad-hoc session reads outside the provider
- [ ] Existing dashboard/auth unit suites pass unchanged; no route or copy changes
- [ ] `npm run lint`, `npm run typecheck`, `npm run test:unit:frontend` green

## Read-list (in order)

1. `AuthProvider` component + its vitest suite (`AuthContext.test.tsx`) - what the context exposes (`isAuthenticated`, `isLoading`, roles), how it validates against `/v1/me` (~1K tokens)
2. Root `app/layout.tsx` and `(dashboard)/layout.tsx` - where the provider mounts today, what moves where (~0.5K)
3. Patient login page (`app/login/page.tsx`) and choose-role page (`app/choose-role/page.tsx`) - the two ad-hoc readers: login redirects to `/patient` when a session exists; choose-role re-fetches `/v1/me` inline (~1K)
4. UI blueprint §3 (session chrome rows only) - naming expectations for the session-aware entry button later tickets build (~0.5K)

## Do NOT read

- `docs/archive/`, `prototype/`, backend modules, dashboard components other than the layouts above, PRD/roadmap.

## Baseline verify (must pass before the first edit)

Recorded green on 2026-08-22:

- `npm run lint` - all hooks pass
- `npm run typecheck` - clean
- `npm run test:unit:frontend` - 8 files / 72 tests pass

## Done-verify (acceptance criteria → commands)

- Same three baseline commands plus extended `AuthContext.test.tsx`
- Grep check: no `readSession()` calls remain inside `app/login/page.tsx` or `app/choose-role/page.tsx`

## Handoff notes

- Keep behaviour identical: login page's signed-in redirect target stays `/patient` for now; ticket 07 (route groups) owns any redirect changes.
- Choose-role page's inline `/v1/me` fetch should become `useAuth()` consumption; keep its rendered output byte-stable so its existing suite passes untouched.
- Public pages render before hydration completes on first paint - preserve whatever SSR-safe default the provider exposes (`isLoading`) so there is no auth-state flash regression.
