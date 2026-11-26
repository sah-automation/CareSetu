# Brief - 538 Doctor chrome: account avatar + redesigned sidebar

**Ticket:** #538 · **Parent:** #529 · **Refreshed:** 2026-09-24
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

The doctor console shell looks and behaves professionally without breaking the shared patient shell (US-6, US-8, US-9, US-10). The shared top-bar/chrome gains an account avatar entry point for doctors; the shared sidebar is redesigned: section groups, refined active state, a collapsed icon-only state with hover label flyouts and the open-cases count on the flyout, an icon-only collapse toggle, and a Logout item in the lower group. The patient shell's sidebar behavior and the mobile bottom-tab experience stay unchanged. This ticket is chrome only - it does not yet flip the Patients/Profile nav entries or landing cards (those land with their pages).

AC:

- [ ] Doctor chrome shows an account avatar entry (phone-digit/role trigger preserved for other staff roles)
- [ ] Sidebar redesign: section groups, redesigned collapsed state with hover flyouts, refined active state, open-cases count on the collapsed flyout, icon-only collapse toggle, Logout in the lower group
- [ ] Patient shell sidebar behavior and doctor/partner/operator mobile bottom-tab experience are unchanged (existing shell + sidebar tests stay green)
- [ ] EN/HI copy for any new shared strings with parity; `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` green

## Read-list (in order)

1. The shared `Sidebar` in `components/dashboard/Sidebar.tsx` + its test - the current full-density rail, collapse toggle, and persistence to redesign (~1.5K).
2. `components/dashboard/nav-config.ts` + `nav-config.test.ts` - `NavItemDef` (labelKey/href/icon/soon/partnerTypes), `NAV_CONFIG` per role, `sidebarStorageKey` - the source the sidebar renders and where section grouping can key off (~1.2K).
3. `components/dashboard/AppShell.tsx` + its test - the light/full densities, per-role collapse storage, and `useOpenCasesCount` feed (the open-cases count for the collapsed flyout) (~1K).
4. `components/dashboard/Topbar.tsx` and `AccountMenu.tsx` (+ test) - the shared top bar's avatar/AccountMenu trigger today (phone-digit precedent, `Avatar` photoRef precedence) and where the doctor avatar entry joins; the Logout affordance already present in the menu vs. the sidebar lower group (~1.2K).
5. `docs/design/ui-blueprint.md` sidebar/nav sections - the approved navigation model for the redesigned sidebar (~0.5K).
6. The shared i18n `nav`/`doctorConsole` dictionary block + parity test, for any new shared strings (e.g. Logout, section labels) (~0.5K).

## Do NOT read

- Individual console page internals (landing/cases/case-workspace), backend code, `docs/archive/`, the mobile bottom tabs beyond confirming unchanged behavior.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - confirmed green 2026-09-24 (1288 passed, 89 files).
- `npm run lint`, `npm run typecheck` - confirmed green 2026-09-24.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend` - sidebar/AppShell/AccountMenu/nav-config tests green (patient-shell and bottom-tab assertions untouched + new doctor-avatar/collapse-flyout cases).
- `npm run typecheck` - clean.

## Handoff notes

- The `ProfileGate`/sooned Patients and Profile nav entries stay `soon: true` through this ticket; only the chrome changes (entries flip in #541/#543).
- The patient shell's sidebar behavior must stay byte-level unchanged; make all density/section changes additive to the doctor perspective without branching the light shell's behavior.
- The open-cases count already exists as the AppShell Cases pill (fed by `listOpenCases`, silent-degrade) - reuse the same feed for the collapsed flyout count.
- Mobile bottom tabs (BottomTabs config) are off-limits in this ticket; the shared chrome changes must not alter the role dashboard render asserted in `channels.test.tsx`.
- No em-dashes anywhere (lint-gated); use simple dashes.
