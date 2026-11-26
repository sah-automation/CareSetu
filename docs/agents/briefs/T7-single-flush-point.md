# Brief - T7 Single directory-visibility flush point

**Ticket:** #321 · **Parent:** #319 · **Refreshed:** 2026-09-06
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

Every mutation that alters directory visibility funnels through one "visibility changed" flush helper instead of five scattered `invalidate_directory_cache()` call sites in the partner facade - so a visibility change can never be forgotten at one spot. Purely mechanical: the helper wraps the existing best-effort namespace flush, and each call site delegates to it. No behaviour change; the existing directory-cache unit and integration suites stay green.

Acceptance criteria (from #321):

- [ ] A single "visibility changed" flush helper exists in the partner module and is the only flush point used by the five directory-visibility mutations.
- [ ] Directory-cache unit tests (key coverage, namespace-only flush, silent-failure fallback) and integration tests (activation flush, invalidated flush, purge flush) pass unchanged.
- [ ] `npm run test:unit:backend`, `npm run test:integration`, `npm run typecheck`, `npm run lint` pass.

## Read-list (in order)

1. `docs/architecture/internal-modules.md` MOD-002 spec - facade + directory-cache responsibilities (~0.5K)
2. `docs/standards/coding-standards.md` - module layout, isolation, and test conventions the refactor must obey (~2K)
3. `apps/backend/modules/partner/directory_cache.py` - `invalidate_directory_cache` (best-effort SCAN/DELETE of the `directory:*` namespace) the helper wraps (~0.5K)
4. The partner facade - the FIVE flush call sites to funnel through the helper: activation, re-verification-failure invalidation, immediate revocation, sweep close-out pass, permanent-rejection purge (~1.5K)
5. `tests/unit/test_directory_cache.py` + `tests/integration/test_directory_search_cache.py` - the suites that pin the flush behaviour (~2K)

## Do NOT read

- Any frontend code, other modules, `docs/archive/`. The helper lives in MOD-002; do not touch the cache namespace/key layout.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:integration` (skips when Postgres unreachable)

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run typecheck`
- `npm run lint`

## Handoff notes

- Baseline truth (2026-09-06, before any edit): backend unit 1243 pass; integration 198 pass / **2 pre-existing failures unrelated to MOD-002** (`test_bootstrap_schemas.py`, `test_consent_check_gate.py::test_p95_latency_under_50ms`) - do not chase them.
- Pure mechanical refactor inside the partner facade; if a convenience helper is added to `directory_cache.py`, it must live there, not in another module.
- No behaviour change is allowed - the suites (especially namespace-only flush + silent-failure fallback) are the proof. Do not "improve" the flush semantics.
- The sweep flush is once-per-pass already (not per-credential); keep that cadence.
