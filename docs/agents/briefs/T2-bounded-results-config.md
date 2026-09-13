# Brief - T2 Bounded, configurable directory results + documented boot config

**Ticket:** #324 · **Parent:** #319 · **Refreshed:** 2026-09-06
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

Directory search never returns an unbounded nearest-first list: `DIRECTORY_MAX_RESULTS` (default 50, loud failure on invalid input) is added to the settings object and `.env.example`, and the facade caps the result list at the top-N after distance ordering (in-scope and wider-area fallback paths). The existing-but-undocumented `REDIS_DIRECTORY_TTL_SECONDS` knob (default 300) gets its `.env.example` entry with a comment, so every Phase 6 variable is discoverable at boot. Filtering, distance ordering, and fallback semantics are unchanged; only the final list length is bounded.

Acceptance criteria (from #324):

- [ ] `DIRECTORY_MAX_RESULTS` exists in the settings object (default 50), parses from env, and raises loudly on non-positive/invalid input; its default constant is named per repo convention.
- [ ] `DIRECTORY_MAX_RESULTS` and `REDIS_DIRECTORY_TTL_SECONDS` (with a `300` comment) both appear in `.env.example`.
- [ ] Settings tests assert: default parse, env parse, loud failure on invalid input, and that each Phase 6 variable is present in `.env.example`.
- [ ] A search that yields more matches than the cap returns at most `DIRECTORY_MAX_RESULTS` entries, still nearest-first (covers the fallback path too).
- [ ] `npm run test:unit:backend`, `npm run test:integration`, `npm run typecheck`, `npm run lint` pass.

## Read-list (in order)

1. `docs/architecture/internal-modules.md` MOD-002 spec - directory search behaviour and seams (~1K)
2. The backend settings object (`app/config.py`) - the frozen dataclass `Settings`, the `DEFAULT_*` constant naming, the `_env_int` parse helper, and the existing Phase 6 knobs `redis_directory_ttl_seconds` (default 300) + `partner_credential_sweep_cron` as the validate-and-fail-loudly pattern (~1.5K)
3. `.env.example` - its non-secret-only convention, comment style, and where the Phase 6 partner config block (sweep cron) sits so the new knobs sit beside it (~0.5K)
4. The facade method `search_directory` - distance ordering, the wider-area fallback (`fell_back`), and where the limit is applied AFTER ordering (~1.5K)
5. `tests/integration/test_directory_search.py` - the seeding/fixture pattern used to build a >50-match case (and the existing nearest-first assertions to extend) (~2K)
6. The settings-test pattern in `tests/unit/` (env-parse + loud-failure style, e.g. the iam/gateway settings tests) - to mirror for the new knob and its `.env.example` doc assertion (~1K)

## Do NOT read

- Any frontend code (the homepage cap effect is accepted, not a gate), other modules' schemas, `docs/archive/`. The `check:contract` gate does not cover the directory client - ignore it.

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
- `REDIS_DIRECTORY_TTL_SECONDS` already exists as `redis_directory_ttl_seconds` (default `DEFAULT_REDIS_DIRECTORY_TTL_SECONDS = 300`) in config but is missing from `.env.example`; this ticket only documents it - no config/validation change for it.
- `DIRECTORY_MAX_RESULTS` is brand new: add a `DEFAULT_DIRECTORY_MAX_RESULTS = 50` constant, the field, the `_env_int` read with a positive-value guard raising loudly, and the `.env.example` line.
- The cap applies after distance ordering on the RETURNED items, including the `fell_back` (wider-area) result set. Do not change `_conditions()`, the peri-urban clamp, or the fallback trigger.
- The homepage featured-doctor map calls `search_directory({partnerType: "doctor"})`; the 50-cap therefore also bounds the homepage list - acceptable and intended (bounded-featured note in the ticket).
- Seed >50 partners in the integration case with the same helper the existing suite uses - do not hand-roll a second seeding path.
