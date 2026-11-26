# Brief - PHASE-6-T06 Frontend Provider Profile Page

**Ticket:** #312 · **Parent:** #306 · **Refreshed:** 2026-09-05
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

Patients can tap a directory card and open a provider profile page showing verified credentials (type + status labels), a "verified" indicator, and public-safe fields only. Raw credential documents, emails, phones, and PHI are never displayed.

Acceptance criteria (from ticket):

- `/providers/[id]` page (Next.js App Router)
- Verified badge displayed (true only when partner is `[Active]` AND all credentials unexpired/unrevoked)
- Credential display: type and status labels, expiry date (not raw documents)
- Profile hero layout per `prototype/phase-6/doctor-profile.html`
- Hidden fields: raw credential documents, emails, phones, PHI - only verified-safe fields appear
- 404 or clear error state when provider not found or not active
- Tests: verified indicator matches backend derivation, public payload contains only safe fields

## Read-list (in order)

1. `docs/design/ui-blueprint.md` §2.1 (public URLs, `/providers/:id`) + §3 profile feel. (~2K)
2. `prototype/phase-6/doctor-profile.html` (verified seal, council registration number, credentials + expiry display) and `partner-profile.html` (lab/chemist license numbers visible) + `prototype/PLAN.md` review outcomes (`.profile-hero` mobile left-aligned, binding). Visual spec - do NOT redesign. (~2K)
3. `apps/frontend/src/app/` structure - Next.js App Router routing for the `[id]` dynamic segment; match existing page conventions (client component, fetch pattern). (~1.5K)
4. `apps/frontend/src/components/public/` - PublicHeader/PublicFooter chrome; the provider route is public (not in proxy guard). (~1K)
5. `apps/frontend/src/lib/directory/links.ts` - route constants; the profile route name `providers` is the legal home of the display word. (~0.5K)

## Do NOT read

- Backend code, consent/Redis module, IAM module, ADR files, `docs/archive/`, prototype phases other than phase-6.

## Baseline verify (must pass before the first edit)

- `npm run typecheck` - PASSED 2026-09-05
- `npm run test:unit:frontend` - run before edits (not yet verified this session; assume green, verify by running)

## Done-verify (acceptance criteria → commands)

- `npm run typecheck`
- `npm run test:unit:frontend`

## Handoff notes

- Requires T06's prerequisite T03 (profile API) to be live; fetch the `/v1/directory/providers/{id}` payload and render only the fields it returns. The API owns the verified-safe-field gate; the frontend must not fetch or display anything else.
- The verified badge derives from the API's `verified` field (which the backend computes from `[Active]` + credential dates). The page must never invent its own verification.
- When the API 404s (not-active/no-index), render the not-found/clear-error state per blueprint.
- `provider` is the display word legal in this route's copy; `partner` remains the domain word everywhere in data. Keep UI copy consistent with the public, patient-facing voice.
