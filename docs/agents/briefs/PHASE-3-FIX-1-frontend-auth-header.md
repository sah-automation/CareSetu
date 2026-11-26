# Brief - FIX-1 Frontend auth header delivery

**Ticket:** #222 · **Parent:** #209 · **Refreshed:** 2026-08-25
**Reading surface:** ~3K tokens (budget 10K) - within budget

## Scope

All protected backend routes (`/v1/records`, `/v1/consents/*`) work from the frontend. The frontend currently sends only cookies but the backend reads JWT from the `Authorization: Bearer` header.

**Acceptance criteria:**

- `getAccessToken()` helper in `apps/frontend/src/lib/api-base.ts` reads JWT from localStorage key `caresetu.access_jwt`
- `authedFetch()` wrapper in `api-base.ts` injects `Authorization: Bearer <jwt>` header and includes `credentials: "include"`
- `apps/frontend/src/lib/record/api.ts` uses `authedFetch` instead of bare `fetch`
- `apps/frontend/src/lib/consent/api.ts` uses `authedFetch` instead of bare `fetch`
- `GET /v1/records` returns 200 instead of 401 when user is authenticated
- Consent endpoints return 200 instead of 401
- Unit tests pass: `npm run test:unit:frontend`

## Read-list (in order)

1. `apps/frontend/src/lib/api-base.ts` - current `API_BASE_URL` export, where to add helpers (~5 tokens)
2. `apps/frontend/src/lib/auth/session.ts` - `JWT_KEY` constant name for localStorage (~92 tokens)
3. `apps/frontend/src/lib/record/api.ts` - current `fetchOwnRecord` that needs `authedFetch` (~62 tokens)
4. `apps/frontend/src/lib/consent/api.ts` - current `consentFetch` wrapper that needs `authedFetch` (~199 tokens)
5. `apps/backend/app/gateway/jwt_verify.py` - how backend reads `Authorization` header (confirm contract) (~100 tokens)

**Total:** ~360 tokens of reading, well within budget.

## Do NOT read

- Backend route implementations (health/consent adapters)
- `AuthContext.tsx` (already understood - it sends Bearer correctly for `/v1/me`)
- Frontend pages/components
- Standards docs (not relevant to this fix)

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - current state: timed out in session, may need longer timeout or manual run
- `npm run lint:frontend` - should pass

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` passes
- `npm run lint:frontend` passes
- Manual: login, navigate to `/record` page, verify no 401 in network tab

## Handoff notes

- The JWT is stored in localStorage under key `caresetu.access_jwt` (see `session.ts:11`)
- `AuthContext.fetchMe()` already sends `Authorization: Bearer ${jwt}` correctly - this is the pattern to follow
- The backend's `jwt_verify` middleware reads from `Authorization` header only, not cookies (line 54)
- `credentials: "include"` must remain for cookie transport on split-origin deploys (ADR-0005)
