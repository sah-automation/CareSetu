# Brief - T08 Account menu, PageHeader & system-state conventions

**Ticket:** #199 · **Parent:** #191 PHASE-2.6 · **Refreshed:** 2026-08-22
**Reading surface:** ~5.5K tokens (budget 10K) - within budget

## Scope

Chassis conventions every logged-in surface shares:

- **Account menu:** one top-right dropdown consolidating phone (from the session payload's new `phone` field), role badge, switch-role crossover, and logout across all logged-in surfaces; standalone role-switcher and logout controls fold into it. The interim choose-role page is kept unchanged as staff entry, marked for Phase 5 deletion.
- **PageHeader/breadcrumbs:** a consistent PageHeader block (H1, optional description, primary action) opening every app page; breadcrumbs appear only at depth 2+.
- **System states:** skeleton placeholders for first loads, spinner-in-button for actions, single-next-action empty states, dismissible error banners carrying a short trace id.

Acceptance criteria: see #199 body verbatim.

## Read-list (in order)

1. Prototype `shell-full.html` - account menu, PageHeader, breadcrumb, Soon-badge patterns (binding visual spec) (~2K tokens)
2. UI blueprint cross-cutting patterns section - PageHeader anatomy + system-state rules (~1.5K)
3. Existing `Topbar.tsx` (+ suite), role-switcher/logout controls, choose-role page's `ROLE_META` - what folds away vs stays (~1K)
4. Ticket 05's session client interface (`lib/auth/api.ts` `MeResponse` incl. `phone`) - the data the menu renders (~0.5K)
5. shadcn dropdown-menu primitive from ticket 04 - base component to compose (~0.3K)

## Do NOT read

- Split-auth/profile prototype views, backend modules beyond the session contract, `docs/archive/`.

## Baseline verify (must pass before the first edit)

Recorded green on 2026-08-22: lint, typecheck, frontend units 8 files / 72 tests pass.

## Done-verify (acceptance criteria → commands)

- Baseline three + new suites: account menu render/keyboard/aria, PageHeader adoption on existing app pages, error-banner trace-id test
- Manual proof: menu works in both shell densities; choose-role page still reachable unchanged

## Handoff notes

- Phone display uses T05's additive `phone` field - if it is missing at runtime (stale session), degrade gracefully to subject-id-only rather than crashing.
- Trace id in error banners: client-generated short id per banner instance; no backend dependency this phase.
- Breadcrumbs only at depth 2+ - patient Home stub counts as depth 1.
