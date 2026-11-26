# Brief - PHASE-6-T05a Directory Browse Page (API Client + Core UI)

**Ticket:** #317 · **Parent:** #306 (split from #311) · **Refreshed:** 2026-09-05
**Reading surface:** ~6.5K tokens (budget 10K) - within budget

## Scope

Patients can browse the public directory on `/directory` without logging in: search by name, filter by partner type and specialty via chips, and see result cards showing name, partner_type, specialty (doctors), area, distance, and a truthful verified indicator. Wider-area fallback renders as a "no providers found" message plus nearest matches labeled "outside your area". Type-preset variants and homepage wiring are deliberately excluded (#318).

Acceptance criteria (from ticket):

- [ ] `/directory` page, public (not route-guarded in `src/proxy.ts`)
- [ ] Search bar front and center (per blueprint §2.1), filter chips for partner_type and specialty
- [ ] Result cards: name, partner_type, specialty (doctors), distance, verified indicator (reuse/extract the `DoctorCard` shape from `FeaturedDoctors.tsx`). DEVIATION (2026-09-05): the AC lists `area` on the card, but the `GET /v1/directory/search` projection (facade `DirectoryEntry`) carries `distance_km` only - area surfaces on the provider profile (T06). The card therefore renders locality via distance and never invents an area string; recorded in `search.ts`/`DirectoryCard.tsx` comments.
- [ ] Wider-area fallback: "no providers found" message + nearest matches labeled "outside your area" (filters preserved)
- [ ] API client in `lib/directory` fetching `GET /v1/directory/search` with a typed result shape and loading/empty/error states
- [ ] Visual spec binding: `prototype/phase-6/doctors.html` (and labs/chemists for the shared card/filter CSS)
- [ ] Tests: only activated providers rendered, verified badge truthful, filters preserved in wider-area fallback

## Read-list (in order)

1. `docs/design/ui-blueprint.md` §2.1 (public URLs), §3 (directory feel), gap G2 (public search endpoint contract: unauthenticated read, activated-only, type/specialty/free-text/location filters, wider-area fallback, anonymous telemetry). (~3K)
2. `prototype/phase-6/doctors.html` + `labs.html` + `chemists.html` and `prototype/PLAN.md` review outcomes - the binding visual spec (sticky search bar, filter chips, `.dir-card` CSS, fallback rendering). Do NOT redesign. (~1.5K)
3. `apps/frontend/src/components/public/FeaturedDoctors.tsx` - existing card component + skeleton/empty/populated states; the `DoctorCard` shape to reuse; deep-links to `/providers/${id}`. (~1K)
4. `apps/frontend/src/lib/directory/links.ts` - route constants, `ProviderType`, `directoryHref`. ~0.5K)
5. `apps/frontend/src/app/` structure + `src/proxy.ts` - Next.js App Router route groups; public routes not guarded; match existing page conventions. (~1K)
6. `apps/frontend/src/lib/request.ts` + an existing typed API client (e.g. `lib/partner/api.ts`) - the fetch/guard/error-surface pattern for the new directory client. (~0.5K)

## Do NOT read

- Backend code, consent/Redis module, IAM module, notify module, `docs/archive/`, prototype phases other than phase-6, `lib/directory/featured.ts` (that wiring is #318).

## Baseline verify (must pass before the first edit)

- `npm run typecheck` - PASSED 2026-09-05
- `npm run test:unit:frontend` - PASSED 2026-09-05 (58 files / 627 tests). Known pre-existing noise that does NOT fail the suite: jsdom "Not implemented: navigation" in ProviderRegisterWizard, axe `HTMLCanvasElement.getContext` stderr, and AuthContext ECONNREFUSED logs - ignore.

## Done-verify (acceptance criteria -> commands)

- `npm run typecheck`
- `npm run test:unit:frontend`

## Handoff notes

- The directory pages are public (no login); anonymous search telemetry (T02's `directory_search`) fires with a nullable/cohort-tagged actor.
- Do NOT perpetuate `consultType` into the new directory surface - the Phase 6 card passes only type, specialty (doctors), area, distance, verified (the PRD drops "consultation type").
- `prototype/PLAN.md` review outcomes are binding decisions; where the blueprint and prototype conflict, follow the prototype for pixel-level shape and the PRD for behavior.
- Only `[Active]` partners with valid credentials render; the verified badge on the card must match the backend tick (card is not shown when the tick is false).
- i18n landing note (2026-09-05): the `directory.*` dictionary block (EN + HI) landed with this ticket because the bilingual browse surface is load-bearing (REQ-006 parity test fails otherwise). T05b's i18n item then reduces to any preset-variant copy still missing + homepage featured wiring - check `heading.{doctor,lab,chemist}`, `distanceKm`, `resultsCount` are already present.
- Blocked by #313 (search core) - the endpoint contract is `GET /v1/directory/search` from blueprint gap G2.
