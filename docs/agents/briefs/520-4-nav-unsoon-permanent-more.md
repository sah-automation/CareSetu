# Brief - 524 Un-soon Profile & Settings nav entry + permanent More tab

**Ticket:** #524 · **Parent:** #520 · **Refreshed:** 2026-09-23
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

The patient nav config's Profile & Settings entry stops being "soon": it becomes a live row in the More sheet pointing at the real Profile & Settings route, stays out of the desktop top nav, and the More tab becomes guaranteed for the patient role (fixed five-column bottom bar). Other roles keep their conditional More behavior; existing shell tests that pin the entry as a disabled Soon row are updated.

Acceptance criteria:

- Patient More sheet shows a live, tappable Profile & Settings row (no Soon badge) that opens the page
- Entry does not appear in the desktop top nav
- More tab always present for the patient role; other roles' More behavior unchanged
- Shell/nav test expectations updated (disabled-SPAN assertions replaced)
- `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` green

## Read-list (in order)

1. Spec #520 - Implementation Decisions ("Mobile placement", "Nav config") + story 18 (~0.5K tokens)
2. `docs/design/ui-blueprint.md` §5.1 bottom-tab + More model (lines covering "Profile & Settings lives outside the tab bar in the More sheet") (~0.5K)
3. The typed nav config (`NAV_CONFIG: Record<Role, NavItemDef[]>` with `{key, labelKey, href, icon, soon?, center?, mobileOverflow?, count?}`) and `splitMobileTabs()` incl. its `TABBAR_MAX_DESTINATIONS` constant - the patient profile-settings entry (`soon: true`, `mobileOverflow`), the `mobileOverflow` flag, and how hasMore is derived (~1K)
4. The bottom tab bar + More sheet components - how `soon` rows render vs live rows, where a live overflow row's href is honored, testids `more-*` / `more-trigger` (~1.5K)
5. Shell and nav-config test suites - the assertions that the patient More sheet lists Inbox/Bookings/Profile & Settings as disabled SPANs with 3 soon-badges; these flip when Profile & Settings goes live (~0.8K)

## Do NOT read

- Account menu / avatar internals (Ticket 521, 526)
- Profile & Settings page form code (Ticket 522)
- Staff profile nav entries except to confirm they stay `soon`
- Backend code, `docs/archive/`

## Baseline verify (must pass before the first edit)

- `npm run typecheck`
- `npm run lint`
- `npm run test:unit:frontend` - note: 1 pre-existing failure in the doctor case pre-summary test at HEAD, unrelated to this ticket

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` with shell + nav-config suites green
- `npm run lint`, `npm run typecheck`

## Handoff notes

- The live entry must stay out of the desktop top nav: the patient top nav derives from the same `NAV_CONFIG.patient` list (first 5 non-center), so keep it out of that window (e.g. `mobileOverflow: true`).
- #522 must exist first so the un-sooned link resolves to a real page.
- Avoid em-dashes and non-ascii punctuation in copy (git hook `no-em-dash gate`).
