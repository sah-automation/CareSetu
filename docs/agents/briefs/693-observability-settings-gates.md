# Brief - 693 A5 - Observability settings gates + env docs

**Ticket:** #693 · **Parent:** #692 · **Refreshed:** 2026-10-12
**Reading surface:** ~9.5K tokens (budget 10K) - within budget

## Scope

Add every Phase-14A observability environment gate to the backend `Settings` object - all additive, disabled by default - and document each in `.env.example` and `render.yaml`. Nothing is wired to the gates yet; this ticket only makes the configuration exist so later tickets can read it. Local dev, tests, and CI behaviour is unchanged.

Gates: `LOG_FORMAT` (`console` | `json`, default `console`), `SENTRY_DSN` (empty = off), `SENTRY_TRACES_SAMPLE_RATE`, `OTEL_ENABLED` (false), `OTEL_EXPORTER_OTLP_ENDPOINT` + `OTEL_EXPORTER_OTLP_HEADERS`, `OTEL_TRACES_SAMPLER_RATIO`, `OTEL_SERVICE_VERSION`, `METRICS_ENABLED` (false), `OBSERVABILITY_ENABLED` (false). Langfuse keys already exist.

Acceptance criteria (verbatim):

- [ ] Every gate exists on `Settings` with a safe default; `get_settings()` parses them using the existing `_env_bool`/`_env_float`/`_env_csv` helpers.
- [ ] `__post_init__` fails closed where a gate implies a companion (e.g. OTel enabled requires an endpoint, Sentry sample rate only meaningful with a DSN).
- [ ] `.env.example` and `render.yaml` document each gate; no secret values committed.
- [ ] `npm run typecheck` and `npm run test:unit:backend` pass with no behaviour change.

## Read-list (in order)

1. `Settings` frozen dataclass field block, the `_env_bool`/`_env_float`/`_env_int`/`_env_csv` parsers, the `__post_init__` fail-closed companion-validation idiom (Langfuse pair, `supabase` backend requires url + key, `sms_provider='provider'` requires key + base*url), and the explicit `get_settings()` kwargs mapping in `app/config.py` - the exact pattern every new gate must mirror, top-of-file `DEFAULT*\*` constants included (~5K of a ~10K file; skip the provider-validation sprawl you are not extending).
2. `app/config.py` `Settings` fields the new ones sit beside (`langfuse_*`, `redis_*`, `dispatcher_in_process_enabled`, `demo_mode`) - naming and default conventions (~0.3K).
3. `.env.example` - the commented-gate documentation idiom and where non-secret defaults vs commented secret placeholders go (~2K).
4. `render.yaml` `envVars` block - the `value:` (non-secret default) vs `sync: false` (dashboard secret) convention (~1.5K).
5. Parent plan `docs/plans/plan-phase14-observability.md` §4 (the gate table: every gate name, tool, default) and Appendix A.2 (additive-only, feature-flagged, disabled-by-default safety pattern) (~0.8K).
6. `tests/unit/test_app_shell.py` and `tests/unit/test_worker.py` - the existing `Settings(...)` default assertions and `monkeypatch.setenv` idiom to copy for the new settings unit test (~0.7K).

## Do NOT read

- Module internals, facades, or adapters.
- Frontend.
- `docs/archive/`.
- The other observability tickets' code (A1/A2/A3/A4) - they consume these gates, they do not define them.

## Baseline verify (must pass before the first edit)

- `npm run typecheck` - PASS on the current tree.
- `npm run test:unit:backend` - PASS (2925 passed).
- (Harness context: `npm run test:unit:frontend` - all 1910 tests in 133 files pass, but vitest exits non-zero with a worker-timeout error; environment flake, not a test failure. Not needed for this ticket.)

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` - green, including a new settings unit test asserting every new gate's default and each fail-closed companion rule.
- `npm run typecheck` - green.
- Diff review: no app behaviour changed; no secret value committed to `.env.example`/`render.yaml`.

## Handoff notes

- **This is the root of the batch: A1 (#694), A2 (#695), A4 (#696), A3 (#697) all read these fields.** Keep names exactly as the plan §4 table spells them, and mirror the existing `Settings` naming convention (env var `LOG_FORMAT` -> field `log_format`, `OTEL_ENABLED` -> `otel_enabled`).
- **Copy an existing gate, do not invent one.** The closest precedents are the Langfuse pair (both-or-empty), the `supabase` media backend (backend implies its credentials), and the `sms_provider='provider'` branch (provider implies key + base_url). `__post_init__` raises `ValueError` with an actionable message - that is the fail-closed idiom, never a silent default.
- **Parsers already exist:** `_env_bool`, `_env_float`, `_env_int`, `_env_csv` in `app/config.py`. `LOG_FORMAT` is a two-value enum ("console"/"json") like `sms_provider`; validate it in `__post_init__` rather than trusting the raw string.
- **Defaults must keep dev/test/CI inert:** `LOG_FORMAT="console"`, `OTEL_ENABLED=false`, `METRICS_ENABLED=false`, `OBSERVABILITY_ENABLED=false`, `SENTRY_DSN=""`; the presence of a gate alone must never change boot or test behaviour.
- **`.env.example`/`render.yaml` are documentation only here:** no secret values, comma-separated `OTEL_EXPORTER_OTLP_HEADERS` documented as a secret placeholder. `render.yaml` values that are `sync: false` stay dashboard-managed.
- **No em-dashes anywhere** (lint-gated) - use simple dashes.
