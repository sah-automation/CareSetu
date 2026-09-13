# Brief - 376 fix(frontend): resolve TypeScript errors in Phase 7 intake pre-summary and test fixtures

**Ticket:** #376 · **Parent:** Phase 7 verification · **Refreshed:** 2026-09-10
**Reading surface:** ~1.5K tokens (budget 10K) - within budget

## Scope

Fix 4 TypeScript compilation errors in the frontend caused by the `StructuredFields` interface lacking an index signature, and document missing AI/intake env vars in `.env.example`. No runtime behavior changes.

- **Fixes 1+2:** Cast `summary.structured_fields` to `Record<string, unknown>` at two call sites in the pre-summary page component (line 245: `orderedFieldKeys` argument; line 254: string-index access in `displayValueFor`). Casts are safe - downstream only uses `Object.keys()` and `key in`.
- **Fixes 3+4:** Complete `structured_fields` test fixtures to satisfy the `StructuredFields` interface. Pre-summary test: `{}` becomes `{ chief_complaints: [], symptoms: [], duration: null }`. Status test factory: add `symptoms: [], duration: null` alongside existing `chief_complaints`.
- **Fix 5:** Add `AI_PROVIDER`, `AI_API_KEY`, `AI_BASE_URL`, `AI_TIMEOUT_SECONDS`, `AI_MAX_RETRIES`, `AI_CIRCUIT_BREAKER_THRESHOLD`, `AI_CIRCUIT_BREAKER_COOLDOWN_SECONDS`, `AI_MONTHLY_BUDGET_PAISE`, `INTAKE_MEDIA_ROOT`, `INTAKE_MEDIA_KEY` to `.env.example` after the Langfuse block (line 50) and before the Frontend block (line 52).

## Read-list (in order)

1. `StructuredFields` interface definition in `intake/api.ts` (line 69) - the type contract all fixtures must satisfy (~30 tokens)
2. `orderedFieldKeys` helper in `pre-summary/page.tsx` (line 65) - accepts `Record<string, unknown>`, only calls `Object.keys()` and `key in` (~50 tokens)
3. `pre-summary/page.tsx` lines 243-258 - the two call sites needing casts (`orderedFieldKeys` arg at 245, `displayValueFor` string-index at 254) (~100 tokens)
4. `pre-summary/page.test.tsx` line 364 - bare `{}` fixture that must become full `StructuredFields` shape (~20 tokens)
5. `status/page.test.tsx` lines 96-112 - `preSummary()` factory missing `symptoms`/`duration` (~60 tokens)
6. `.env.example` lines 44-52 - insertion gap between Langfuse and Frontend blocks (~50 tokens)
7. `config.py` lines 194-201, 166, 455-456, 475-488 - source of truth for env var names and defaults (~150 tokens)

## Do NOT read

- Backend modules (mypy is already clean)
- Prototype files (Fix 6 removed from scope)
- `docs/archive/` or any planning docs beyond this brief
- Other frontend pages unrelated to intake pre-summary

## Baseline verify (must pass before the first edit)

- `cd apps/frontend; npx tsc --noEmit` - currently fails with 4 errors (the errors this ticket fixes)
- `cd apps/frontend; npx vitest run --reporter=verbose` - should pass (type errors don't block vitest runtime but may mask issues)

## Done-verify (acceptance criteria -> commands)

- `cd apps/frontend; npx tsc --noEmit` exits 0 (all 4 errors resolved)
- `cd apps/frontend; npx vitest run --reporter=verbose` passes all Phase 7 test suites (pre-summary, status)
- `npm run lint` passes (no new lint issues from the casts)

## Handoff notes

- The `StructuredFields` interface must remain strict (no index signature added). Casts are the correct approach - they preserve type safety everywhere else while allowing dynamic access at the two specific sites.
- The `orderedFieldKeys` helper is only used in `pre-summary/page.tsx` - the cast has no ripple effects.
- Empty arrays + null duration in test fixtures preserve the original test intent (empty-state coverage) without changing assertion outcomes.
- The 3 backend test failures are pre-existing Phase 2 issues, not related to this fix.
