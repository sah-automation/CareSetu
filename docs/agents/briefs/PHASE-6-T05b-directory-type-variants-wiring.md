# Brief - PHASE-6-T05b Directory Type Variants & Homepage Wiring

**Ticket:** #318 · **Parent:** #306 (split from #311) · **Refreshed:** 2026-09-05
**Reading surface:** ~3.5K tokens (budget 10K) - comfortably within budget

## Scope

The three type-filtered directory variants `/doctors`, `/labs`, `/chemists` (blueprint §2.1) render the #317 browse component pre-filtered by partner type. Homepage FeaturedDoctors wires to the real search API (replacing the stub), and EN + Hindi i18n strings cover the whole directory surface.

Acceptance criteria (from ticket):

- [ ] `/doctors`, `/labs`, `/chemists` routes render the #317 browse component pre-filtered by partner type
- [ ] `lib/directory/featured.ts` stub wired to the real search API (keep signature/shape; drop `consultType`)
- [ ] Homepage FeaturedDoctors shows live activated providers with a truthful verified indicator
- [ ] EN + Hindi i18n strings for the directory surface (search placeholder, filter labels, "outside your area", verified badge)
- [ ] Tests: type-preset filtering, featured wiring, i18n completeness

## Read-list (in order)

1. `apps/frontend/src/lib/directory/featured.ts` - the marked integration point (stub returning `[]`); replace the body, keep the signature/shape. (~0.5K)
2. `apps/frontend/src/app/` structure + `src/proxy.ts` - route groups; public `/doctors`, `/labs`, `/chemists` not guarded; match the #317 `/directory` page convention for the variant pages. (~1K)
3. `apps/frontend/src/lib/directory/links.ts` - `ProviderType`, `directoryHref(type, query)` - reuse for the presets instead of new query-building. (~0.5K)
4. `apps/frontend/src/components/public/FeaturedDoctors.tsx` - the wiring target for the real search API. (~1K)
5. `apps/frontend/src/lib/i18n/dictionaries.ts` + `dictionaries.test.ts` - EN + Hindi string pattern + the parity test that asserts completeness. (~0.5K)

## Do NOT read

- Backend code, consent/Redis module, IAM module, notify module, prototype files except as pixel-style reference, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run typecheck` - PASSED 2026-09-05
- `npm run test:unit:frontend` - PASSED 2026-09-05 (58 files / 627 tests). Known pre-existing noise that does NOT fail the suite (jsdom navigation/canvas stderr, AuthContext ECONNREFUSED logs) - ignore.

## Done-verify (acceptance criteria -> commands)

- `npm run typecheck`
- `npm run test:unit:frontend`

## Handoff notes

- The type-preset routes are thin wrappers over the #317 page/component - no new search logic here.
- `FeaturedDoctor` today carries a `consultType` field the PRD drops - do not perpetuate it into the new surface.
- i18n parity: every EN string needs its Hindi pair, or `dictionaries.test.ts` fails.
- Blocked by #317 - starts once the browse page + `/directory` route land.
