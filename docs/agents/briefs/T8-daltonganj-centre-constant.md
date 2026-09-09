# Brief - T8 Test-visible Daltonganj centre constant

**Ticket:** #322 · **Parent:** #319 · **Refreshed:** 2026-09-06
**Reading surface:** ~3K tokens (budget 10K) - within budget

## Scope

The Daltonganj centre coordinates live in exactly one test-visible source shared by the partner facade and the directory test suites, replacing the duplicated coordinate literals in the integration/unit tests and the facade comment flagging the duplication. `.env.example` `NEXT_PUBLIC_DEFAULT_LATITUDE/LONGITUDE` values are frontend build-time defaults and are out of scope. Pure refactor: existing tests keep their numbers by importing the shared constant, nothing user-visible changes.

Acceptance criteria (from #322):

- [ ] A single test-visible constant (or constant pair) for the Daltonganj centre exists and is imported by the partner facade's geo default.
- [ ] The duplicated centre-coordinate literals in the directory integration/unit tests are replaced by imports of that constant; the intentional-duplication comment is removed.
- [ ] `npm run test:unit:backend`, `npm run test:integration`, `npm run typecheck`, `npm run lint` pass.

## Read-list (in order)

1. `docs/architecture/internal-modules.md` MOD-002 spec - the geo-default (`REQ-008` Daltonganj launch geography) the constant backs (~0.3K)
2. The partner facade - the existing `DALTONGANJ_LATITUDE` / `DALTONGANJ_LONGITUDE` constants + their use in the `search_directory` missing-geo default (~0.3K)
3. The directory tests that inline the coordinate literals: `tests/integration/test_directory_search.py`, `tests/integration/test_directory_search_cache.py`, and any unit fakes in `tests/unit` directory tests (~1.5K)
4. `docs/standards/coding-standards.md` - test-visibility/import conventions the shared constant must follow (~1K)

## Do NOT read

- Any frontend code and `.env.example`'s `NEXT_PUBLIC_*` vars (frontend build-time defaults - deliberately untouched), other modules, `docs/archive/`.

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
- The facade constants already exist (`24.04` / `84.07`); the change is making them the single importable source and removing the duplicated test literals + the "intentional duplication" comment.
- Do not touch the `.env.example` `NEXT_PUBLIC_DEFAULT_LATITUDE/LONGITUDE` values - those are the frontend's build-time defaults, not part of this ticket.
