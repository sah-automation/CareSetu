# Brief - 270 Phase-5 fix: transport delegate rename + backoff rename (S18 and S19)

**Ticket:** #270 · **Parent:** #243 · **Refreshed:** 2026-09-01
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

Two small notify-only cleanups bundled per the ticket author:

- **S18:** `CircuitBreakerChannel.send` reads `self._breaker._integration` directly (feature envy - it reaches into the breaker's private attr). Give `CircuitBreaker` an accessor/property for its integration label and use it; the channel must not touch `_integration`.
- **S19:** `mock_backoff_delay` is a misleading name - it is used by the REAL provider retry path too, not just mocks. Rename to reflect that (e.g. `backoff_delay` / `exponential_backoff_delay`) and update all callers in `whatsapp.py`/`sms.py` (and any tests).

Acceptance criteria (from #270):

- [ ] `CircuitBreakerChannel.send` no longer reads `self._breaker._integration` (uses the new accessor).
- [ ] The backoff helper is renamed to a non-`mock` name; `whatsapp.py`/`sms.py` and their tests use the new name.
- [ ] Notify unit + integration tests pass; no behavior change.

## Read-list (in order)

1. `apps/backend/modules/notify/adapters/transport.py` - `CircuitBreaker` (73-154; does it even HAVE `_integration`? the channel reads it at 180, so either it exists here or this is a bug to fix), `CircuitBreakerChannel.send` (177-201 reads `self._breaker._integration` at 180), and `mock_backoff_delay` (278-288) (~0.8K).
2. `apps/backend/modules/notify/adapters/whatsapp.py` (96-148 `send` uses `mock_backoff_delay`) and `apps/backend/modules/notify/adapters/sms.py` (101-152 same) - the retry loops the rename touches (~1.2K).
3. Grep for all `mock_backoff_delay` and `_integration` usages across the notify module (including tests) to make the rename complete (~0.5K).
4. `tests/unit/` notify tests (grep `mock_backoff_delay` / `_integration` / `CircuitBreaker` in tests) - update the rename references (~1K).

## Do NOT read

- iam's breaker (`modules/iam/adapters/sms.py`) - notify owns its own port contract; only the notify breaker is in scope (S18 stays local to notify).
- partner/audit internals, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`

## Done-verify (acceptance criteria -> commands)

- Notify tests green (grep the notify test files and run them + full unit suite)
- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`
- `npm run typecheck`
- `npm run scan` (bandit) unaffected by the rename (no new high-severity).

## Handoff notes

- S19's rename: `mock_backoff_delay` is used by the REAL provider channel retry loops (`whatsapp.py:110`, `sms.py:110`), so "mock" is a misnomer. Pick a neutral name (`backoff_delay` or `exponential_backoff_delay`) and update both providers + tests. Keep the same signature/logic (`base_seconds`, `jitter_fraction`, 1-based attempt) to avoid behavior change.
- S18's fix: give `CircuitBreaker` a public accessor (e.g. `integration_name` property) and have `CircuitBreakerChannel.send` call it instead of `self._breaker._integration`. Note the channel constructs the message at 180/187; if the breaker has NO `_integration` attribute, that's a latent bug the accessor also surfaces - fix it consistently.
- This touches `transport.py` which #258 (S4) also edits (it centralizes the provider pipeline there). Coordinate: if #258 hasn't landed, the rename/accessor changes are small and orthogonal - but both tickets must not conflict on the same lines. Prefer landing the rename + accessor FIRST (it's tiny), then #258's dedup, OR have #258 do the rename as part of its dedup. Cross-ticket note in the commit.
