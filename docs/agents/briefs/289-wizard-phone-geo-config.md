# Brief - 289 Move wizard phone + practice-geo constants to config

**Ticket:** #289 · **Parent:** phase5-frontend-review-fixes.md Fix 1 · **Refreshed:** 2026-09-03
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

Stop hardcoding the `+91` country code in `normalizePhone` - read from `NEXT_PUBLIC_DEFAULT_COUNTRY_CODE` env var with a safe default. Stop sending silent `practice_latitude: 0, practice_longitude: 0` in wizard submit - collect or derive real coordinates from the user. Document both in `.env.example`.

- [ ] `normalizePhone` reads country code from `NEXT_PUBLIC_DEFAULT_COUNTRY_CODE` env var (with dev/CI-safe default)
- [ ] Wizard submit sends real geolocation values (not silent 0,0)
- [ ] `.env.example` documents `NEXT_PUBLIC_DEFAULT_COUNTRY_CODE` and any new geolocation config
- [ ] Tests: normalizePhone works with config, wizard submit uses real coords

## Read-list (in order)

1. `apps/frontend/src/components/auth/staff/ProviderRegisterWizard.tsx` - Lines 121-127: `normalizePhone()` hardcodes `+91`. Lines 873-947: `handleSubmitPartner` sends `practice_latitude: 0, practice_longitude: 0`. (~950 lines, ~10K tokens - read selectively: focus on normalizePhone function and submit handler)
2. `apps/frontend/src/components/auth/staff/ProviderRegisterWizard.test.tsx` - existing tests asserting hardcoded `91` prefix / `0,0` coords. (~300 lines, ~5K tokens - grep for normalizePhone and latitude/longitude assertions)
3. `.env.example` - document new env vars.
4. Backend constraint (reference only, no changes): `partner/schema/models.py` lines 69-70: both lat/lng columns are `nullable=False`. `partner/adapters/routes.py` lines 82-83: `Field(ge=-90,le=90)` / `(ge=-180,le=180)`.

## Do NOT read

- partner API client, operator modules, audit modules
- i18n dictionaries (unless adding error copy for geolocation)
- Backend modules beyond the schema/route reference

## Baseline verify (must pass before the first edit)

- `npm run test -w @caresetu/frontend`
- `npm run typecheck -w @caresetu/frontend` (ignore `.next/dev/types/` errors)
- `npm run lint`

## Done-verify (acceptance criteria -> commands)

- `npm run test -w @caresetu/frontend` - wizard tests pass with config-driven phone and real coords
- `npm run typecheck -w @caresetu/frontend` - no new type errors in source
- `npm run lint` - clean

## Handoff notes

- The backend makes `practice_latitude`/`practice_longitude` **mandatory** (`nullable=False`, `Field(ge=-90,le=90)`). You cannot simply drop them. The fix must collect real values.
- Options for geolocation: (a) use the browser Geolocation API to derive coordinates, (b) let the user enter them manually, (c) derive from the selected service area. The plan suggests an explicit geolocation step.
- For `normalizePhone`: the country code is a display/formatting concern. The backend normalizes to E.164 server-side and is authoritative. The frontend should strip non-digits and prepend the configured country code.
- The `NEXT_PUBLIC_` prefix is required for Next.js client-side env vars.
