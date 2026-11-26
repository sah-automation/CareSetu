# Brief - T01 Component library & UI foundation under the page-weight budget

**Ticket:** #179 · **Parent:** #178 Wayfinder map: Top-level UI Blueprint · **Refreshed:** 2026-08-21
**Reading surface:** ~2K tokens (budget 10K) - within budget

## Scope

Research question (verbatim): Which component-library/design-system approach should the CareSetu frontend standardize on - shadcn/ui, another headless option (Radix primitives, Headless UI, React Aria Components), or hand-rolled Tailwind components - given Next.js App Router + Tailwind, the NFR-003 1.5 MB page budget, bilingual EN/Hindi UI, accessibility needs, and a small team?

Resolution must produce: comparison table with primary-source evidence links, one clear recommendation, migration notes referencing the existing Phase 2.5 shell components by name.

## Read-list (in order)

1. `apps/frontend/package.json` - pinned stack: Next ^16.3 (App Router), React ^19, Tailwind ^3.4 (NOT v4), vitest/jsdom tests (~0.3K)
2. `docs/prd/project-prd.md` §6 NFR specs - grep `NFR-003`, read only that row/slice for exact page-weight wording (~0.5K)
3. Component inventory (names only, no full reads): `src/components/dashboard/Sidebar.tsx`, `Topbar.tsx`, `types.ts`; `src/components/auth/PatientAuthWizard.tsx`, `icons.tsx` - these are what migration notes must reference (~0.5K)
4. Research skill conventions: `C:\Users\Sonu Gupta\.config\opencode\skills\research\SKILL.md` (~1K)

## Do NOT read

- Backend code, other PRD sections, roadmap, archive docs, full component implementations (signatures suffice).

## Baseline verify (must pass before the first edit)

- `git status` - note pre-existing changes; leave them untouched.

## Done-verify (acceptance criteria → commands)

- Findings committed as `docs/research/ui-component-library.md` on branch `research/component-library`, pushed to origin
- Resolution comment on #179 (recommendation gist + file path + branch), ticket closed
- Map #178 Decisions-so-far gains one line linking #179

## Handoff notes

- Product context: patient web app for Tier-3/4 India users on 4G smartphones - client-JS weight and low-bandwidth behavior are first-order concerns, not nice-to-haves.
- A fresh brand identity (palette/typography) is decided separately on this map (ticket "Brand & visual identity") - theming/design-token flexibility matters more than any bundled look.
- Small team, strict cost floor (`NFR-001`) - maintenance burden counts against complexity.
