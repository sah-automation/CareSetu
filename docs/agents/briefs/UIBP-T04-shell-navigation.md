# Brief - T04 Shell & navigation model

**Ticket:** #182 · **Parent:** #178 Wayfinder map: Top-level UI Blueprint · **Refreshed:** 2026-08-21
**Reading surface:** ~4K tokens (budget 10K) - within budget

## Scope

Decision question (verbatim): The app-shell and navigation conventions shared by all four logged-in surfaces: public nav vs app shell boundary, sidebar/topbar patterns per role, mobile/responsive navigation patterns, breadcrumbs/page-header conventions. Audit the existing Phase 2.5 shell (Sidebar/Topbar, choose-role page) for what survives given the split-auth decision.

Resolution must produce: the shell pattern per logged-in surface (which keep sidebar, which use lighter chrome), mobile navigation behavior, public-vs-app boundary rules (URL groups, guards), page-header/breadcrumb conventions, and a keep/kill/migrate verdict on each existing shell component. This ticket BLOCKS the four per-role IA tickets - its output is their shared vocabulary.

## Read-list (in order)

1. Map #178 body (Notes) - split-auth preference changes what the shell must guard (~0.5K)
2. `src/components/dashboard/Sidebar.tsx`, `Topbar.tsx`, `types.ts` - current nav-item-per-role shape, role switcher, logout (~2K)
3. `src/app/(dashboard)/layout.tsx` + `choose-role/page.tsx` - route-group layout and the role-selection screen split auth may retire (~0.7K)
4. `docs/adr/0005-cookie-localstorage-dual-jwt.md` - how session transport shapes guard placement (~1K)

## Do NOT read

- PatientAuthWizard internals, backend code, PRD epics, roadmap, archive docs.

## Baseline verify (must pass before the first edit)

- None - read-only decision session; do not edit code.

## Done-verify (acceptance criteria → commands)

- Resolution comment on #182 with the shell/navigation model; ticket closed
- Map #178 Decisions-so-far gains one line linking #182
- Closing comment explicitly states conventions the four IA tickets must reuse

## Handoff notes

- Existing sidebar collapses to icon-only < 1024px; persona is smartphone-first - judge whether that breakpoint story actually serves mobile or needs rework.
- Sidebar nav items currently carry "Soon" badges for unbuilt features - decide if that convention survives into the blueprint.
- Role switcher dropdown exists for multi-role users; split auth may make roles separate logins instead - resolve deliberately.
