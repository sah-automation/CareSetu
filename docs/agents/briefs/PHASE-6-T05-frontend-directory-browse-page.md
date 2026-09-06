> **SUPERSEDED 2026-09-05** · #311 was split for session-size. This brief documents the union scope only. Implement via the sub-tickets:\n> - `PHASE-6-T05a-directory-browse-page.md` (#317) - /directory route, API client, browse component\n> - `PHASE-6-T05b-directory-type-variants-wiring.md` (#318) - type variants, featured.ts wiring, i18n\n

# Brief - PHASE-6-T05 Frontend Directory Browse Page

**Ticket:** #311 · **Parent:** #306 · **Refreshed:** 2026-09-05 · **SUPERSEDED (see banner above)**
**Reading surface:** ~9K tokens (budget 10K) - within budget

## Scope

Patients can browse the public directory, search by name, filter by partner type and specialty, see result cards with distance and verified indicator, and get a wider-area fallback when nothing matches nearby. Works without logging in. FeaturedDoctors on the homepage wires to the real search API.

Acceptance criteria (from ticket):

- `/directory` page (plus `/doctors`, `/labs`, `/chemists` type-filtered variants per blueprint §2.1)
- Search bar front and center, filter chips for partner_type and specialty
- Result cards: name, partner_type, specialty (doctors), area, distance, verified indicator
- Wider-area fallback: "no providers found" + nearest matches labeled "outside your area"
- Wire `lib/directory/featured.ts` stub to the real search API
- Visual spec: `prototype/phase-6/` views (doctors.html, labs.html, chemists.html) binding
- Tests: only activated providers rendered, verified badge truthful, filters preserved in fallback

## Read-list (in order)

1. `docs/design/ui-blueprint.md` §2.1 (public URLs: `/doctors`, `/labs`, `/chemists`, `/providers/:id`) + §3 directory feel + gap G2 (public directory search endpoint contract: unauthenticated read, activated only, type/specialty/free-text/location filters, wider-area fallback, anonymous telemetry). (~3K)
2. `prototype/phase-6/doctors.html` (search + filters + cards), `labs.html`, `chemists.html`, and `prototype/PLAN.md` review outcomes (binding: header drawer, sticky search bar, filter chips w/ SVG pin + dismissible chip, `.dir-card` card CSS). These are the visual spec - do NOT redesign. (~2K)
3. `apps/frontend/src/components/public/FeaturedDoctors.tsx` - existing card component + skeleton/empty/populated states; the `DoctorCard` shape to reuse for result cards; deep-links to `/providers/${id}`. (~1.5K)
4. `apps/frontend/src/lib/directory/featured.ts` (integration point, stub - replace body, keep signature/shape), `apps/frontend/src/lib/directory/links.ts` (route constants, `ProviderType`, `directoryHref`). (~1K)
5. `apps/frontend/src/app/` structure + `src/proxy.ts` - Next.js App Router route groups; public routes (`/directory`, `/doctors`, ...) are NOT in the guard matcher. Match existing page conventions. (~1.5K)
6. `apps/frontend/src/components/public/` neighboring components (HeroSearch, SpecialtyChips, CategoryTiles, PublicHeader/Footer) - reuse patterns instead of new primitives. (~1.5K)

## Do NOT read

- Backend code, consent/Redis module, IAM module, ADR files, `docs/archive/`, prototype phases other than phase-6.

## Baseline verify (must pass before the first edit)

- `npm run typecheck` - PASSED 2026-09-05
- `npm run test:unit:frontend` - run before edits (not yet verified this session; assume green, verify by running)

## Done-verify (acceptance criteria → commands)

- `npm run typecheck`
- `npm run test:unit:frontend`

## Handoff notes

- The directory pages are public (no login); anonymous search telemetry (T02's `directory_search`) is fired with nullable/cohort-tagged actor.
- The `FeaturedDoctor` type today carries a `consultType` field that the PRD drops ("consultation type" is not a field) - the Phase 6 card passes only type, specialty (doctors), area, distance, verified. Do not perpetuate `consultType` into the new directory surface.
- `prototype/PLAN.md` review outcomes are binding decisions; where the blueprint and prototype conflict, follow the prototype for pixel-level shape and the PRD for behavior.
- Only `[Active]` partners with valid credentials render; the verified badge on the card must match the backend tick (card is not shown when tick is false).
