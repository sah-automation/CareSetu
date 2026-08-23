# Brief - T06 Typed nav-config & AppShell two-density family

**Ticket:** #197 · **Parent:** #191 PHASE-2.6 · **Refreshed:** 2026-08-22
**Reading surface:** ~8.5K tokens (budget 10K) - within budget

## Scope

The navigation backbone: one typed nav-config schema per role - label, href, icon, soon flag, count slot, partner_type filter reserved - as the sole source driving sidebar, desktop top-nav, and mobile tab variants. Role union gains `doctor`. All four role configs ship; doctor/partner/operator entries are mostly Soon except their home.

One AppShell parameterized by role produces two densities:

- **Light** (patient): topbar + bottom tab bar on mobile / slim top-nav on desktop - never a sidebar. Tabs carry max 5 destinations (Home | Find Care | Start Visit | My Record | Inbox), Start Visit as center accent; overflow in a More sheet; unbuilt entries dimmed, non-interactive, Soon badge.
- **Full** (doctor/partner/operator): collapsible sidebar + topbar on desktop, bottom tab bar below breakpoint. Sidebar responsiveness is CSS-driven - matchMedia auto-collapse and the icon-rail strip are retired; collapse preference persists per role.

This ticket lands the shell family wired into the existing generic dashboard group; route-group split + guards are ticket 07.

Acceptance criteria: see #197 body verbatim (nav-config single source; patient shell never-sidebar; staff collapse persisted per role; icon-rail retired; bilingual labels; variant suites green).

## Read-list (in order)

1. UI blueprint §4 shell/navigation sections for patient + staff surfaces - density rules, tab sets, More sheet behavior (~3K tokens)
2. Prototype `shell-light.html` + `shell-full.html` + shared `app.js` nav mechanics - binding visual/interaction spec (~3K)
3. Existing `Sidebar.tsx` (+ its NAV_CONFIG + suite), `Topbar.tsx` (+ suite), `(dashboard)/layout.tsx` (matchMedia effect) - what gets replaced (~2K)
4. Ticket 03's dictionary/LangContext API - how nav labels consume translations (~0.5K)

## Do NOT read

- Homepage/split-auth/profile prototype views, backend modules, `docs/archive/`, e2e specs (ticket 07 owns them).

## Baseline verify (must pass before the first edit)

Recorded green on 2026-08-22: lint, typecheck, frontend units 8 files / 72 tests pass. Note: `channels.test.tsx` asserts "Welcome, Patient/Partner/Operator" headings literally; keep stub pages rendering those headings until their own tickets re-home them.

## Done-verify (acceptance criteria → commands)

- Baseline three + new nav-config/AppShell suites (variants per viewport/role, persistence, More sheet, Soon badges)
- Manual viewport sweep: phone width shows bottom tabs (light) / tabs (full); desktop shows slim top-nav (light) / collapsible persisted sidebar (full)

## Handoff notes

- The current sidebar is NOT an intentional icon rail - it is a full sidebar collapsing to a 64px strip via `matchMedia("(max-width: 1023px)")`, and manual expand still works over phone viewports. Retire all of it; responsiveness must be pure CSS.
- Collapse preference persists per role (localStorage key namespaced by role) - spec decision 6.
- Bottom-tab count cap = 5 including Start Visit accent center slot.
