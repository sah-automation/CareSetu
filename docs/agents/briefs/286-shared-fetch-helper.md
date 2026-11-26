# Brief - 286 Extract shared request<T> fetch helper + type guard utility

**Ticket:** #286 · **Parent:** phase5-frontend-review-fixes.md Fix 0 · **Refreshed:** 2026-09-03
**Reading surface:** ~12K tokens (budget 10K) - slightly over, mechanical refactor

## Scope

Extract a shared `request<T>` fetch helper and `guardShape<T>` utility to replace the duplicated NETWORK_ERROR-catch + parseEnvelope + shape-guard pattern across all API clients. Move `isPartnerView` to one canonical location.

- [ ] `request<T>` wraps `authedFetch`, catches network failure -> `ApiError NETWORK_ERROR`, parses non-ok error envelope, returns parsed JSON payload
- [ ] `guardShape<T>` throws `ApiError UNEXPECTED_ERROR` when the type guard fails
- [ ] `partner/api.ts`, `operator/api.ts`, `audit/api.ts`, `consent/api.ts` refactored to use `request<T>` and `guardShape<T>`
- [ ] `isPartnerView` exists in one canonical location (not duplicated)
- [ ] New tests for `request<T>` covering network-error, error-envelope, and shape-guard paths
- [ ] All existing contract tests stay green

## Read-list (in order)

1. `apps/frontend/src/lib/api-base.ts` - the shared base: `API_BASE_URL`, `getAccessToken()`, `authedFetch()`. The new `request<T>` wraps `authedFetch`. (~30 lines, ~600 tokens)
2. `apps/frontend/src/lib/api-errors.ts` - `ApiError` class, `parseErrorEnvelope()`, `extractTraceId()`. The new helper uses these. (~52 lines, ~1K tokens)
3. `apps/frontend/src/lib/partner/api.ts` - `partnerFetch<T>()` at lines 158-179 is the pattern to extract. 6 exported functions each call `partnerFetch<unknown>` then run `is*` guards. `isPartnerView` is defined here (line ~140). (~271 lines, ~5K tokens)
4. `apps/frontend/src/lib/operator/api.ts` - `operatorFetch<T>()` at lines 163-184, identical pattern. Has its own `isPartnerView` duplicate. (~286 lines, ~5K tokens)
5. `apps/frontend/src/lib/audit/api.ts` - `fetchAccessHistory()` inlines try/catch (no module-level wrapper). (~75 lines, ~1.5K tokens)
6. `apps/frontend/src/lib/consent/api.ts` - `consentFetch<T>()` at lines 104-125, same pattern. (~196 lines, ~3K tokens)
7. Test files: `partner/api.test.ts`, `operator/api.test.ts`, `audit/api.test.ts`

## Do NOT read

- `apps/frontend/src/lib/auth/api.ts` (uses its own `AuthApiError` class, different pattern, out of scope)
- `apps/frontend/src/lib/record/api.ts` (no shape guard, out of scope)
- Backend modules, archive docs, i18n dictionaries

## Baseline verify (must pass before the first edit)

- `npm run test -w @caresetu/frontend` (may be slow on Windows, allow 3+ min)
- `npm run typecheck -w @caresetu/frontend` (pre-existing errors in `.next/dev/types/` are generated files, ignore them - source-level typecheck passes)
- `npm run lint` (may be slow on Windows)

## Done-verify (acceptance criteria -> commands)

- `npm run test -w @caresetu/frontend` - all existing contract tests green + new request<T> tests pass
- `npm run typecheck -w @caresetu/frontend` - no new type errors in source files
- `npm run lint` - clean

## Handoff notes

- The four API clients (`partner`, `operator`, `audit`, `consent`) all follow the same pattern: try `authedFetch`, catch network error -> throw `ApiError NETWORK_ERROR`, on non-ok call `parseErrorEnvelope()`, cast `response.json()` as `T`. The `audit` client inlines this instead of using a module-level wrapper.
- `isPartnerView` is defined in both `partner/api.ts` and `operator/api.ts` - pick one canonical location and re-export.
- The new module can live in `apps/frontend/src/lib/request.ts` (new file) or extend `api-base.ts`. Check which feels cleaner.
- `auth/api.ts` uses its own `AuthApiError` and raw `fetch()` - do NOT refactor it in this ticket.
