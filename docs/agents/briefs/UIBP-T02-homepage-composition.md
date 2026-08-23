# Brief - T02 Public site & homepage composition

**Ticket:** #180 · **Parent:** #178 Wayfinder map: Top-level UI Blueprint · **Refreshed:** 2026-08-21
**Reading surface:** ~5.5K tokens (budget 10K) - within budget

## Scope

Decision question (verbatim): Section-by-section homepage composition (hero, directory search with filters, disease/specialty categories, doctor cards, trust/marketing content), role entry points (Dashboard button behavior for anonymous vs logged-in, Register as Doctor/Lab/Chemist CTAs, operator entry), header/footer, language toggle placement. Practo-like directory feel per the map Notes.

Resolution must produce: an ordered homepage section spec (purpose + content + key interactions per section), the role-entry model (what each CTA does for anonymous vs authenticated visitors), header/footer contents, and where the EN/Hindi toggle lives. Note any new backend needs (e.g., public directory search endpoints) as implications, not designs.

## Read-list (in order)

1. Map #178 body (Notes section) - standing preferences: Practo-like feel, split auth, doctor CTA presets type=doctor (~0.5K)
2. `docs/prd/project-prd.md` §2 personas - who the homepage speaks to (~0.5K)
3. `docs/prd/project-prd.md` §4.2.1 `FEAT-004` Provider Directory & Search - what search/filters the directory actually supports so marketing sections don't promise unbuilt capability (~2K)
4. `docs/prd/project-prd.md` §4.2.2 `FEAT-005` Profiles & Credential Display - what a doctor card may truthfully show (~1.5K)
5. `apps/frontend/src/app/page.tsx` - current homepage stub being replaced (~0.3K)

## Do NOT read

- Roadmap, archive docs, backend modules, intake/care-flow epics outside §4.2.

## Baseline verify (must pass before the first edit)

- None - read-only decision session; do not edit code.

## Done-verify (acceptance criteria → commands)

- Resolution comment on #180 with the section-by-section spec; ticket closed
- Map #178 Decisions-so-far gains one line linking #180

## Handoff notes

- Doctors register via `FEAT-014` open registration / gated activation - the "Are you a doctor?" CTA enters that flow with type preset; it does not create an activated, searchable profile.
- Disease/specialty categories: PRD has provider-type search, not disease browsing - decide whether categories are a marketing navigation aid over specialties or flagged as a future feature gap.
- Bilingual EN/Hindi is a PRD requirement (`REQ-006`) for the patient UI; decide homepage toggle placement here, mechanics land in "Cross-cutting UX patterns".
