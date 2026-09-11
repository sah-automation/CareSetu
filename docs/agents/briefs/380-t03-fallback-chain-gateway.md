# Brief - 380 AI Gateway T03: Fallback chain gateway

**Ticket:** #380 · **Parent:** #377 · **Refreshed:** 2026-09-11
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

Add `FallbackAiGateway`, composing one primary and one secondary provider, each already wrapped in its own circuit breaker. Fallback engages only on genuine outage failures (exhausted retries or open primary breaker); a non-retryable contract rejection propagates immediately and never invokes the secondary. Exposes the effective provider + model after a successful call. Low structuring confidence is never a fallback trigger (ADR-0001 - it remains the forced-doctor-review signal).

Acceptance criteria (from #380):

- [ ] `FallbackAiGateway` composes primary + secondary `AiGateway` instances, each already wrapped in its own circuit breaker
- [ ] `structure` tries primary; on outage-type failure (`Ext002CallError(retries_exhausted=True)`) or open primary breaker, engages secondary
- [ ] Contract rejection (`retries_exhausted=False`) propagates immediately - secondary never invoked for the same request bug
- [ ] Low structuring confidence is never a fallback trigger
- [ ] Exposes effective provider + model after a successful call (for pipeline bookkeeping)
- [ ] First successful provider wins
- [ ] When both primary and secondary fail on outage, the chain raises the outage error and returns no partial or fabricated result
- [ ] Recovery is automatic - both breakers re-open and recovery-probe after their cooldowns
- [ ] `@observe` on `structure` (AI-tracing pre-commit gate stays green)
- [ ] Unit tests via `httpx.MockTransport` with injectable sleep: primary success, primary outage -> secondary success, primary contract rejection (no fallback), open primary breaker routed to secondary, secondary recorded as effective after fallback-engaged success, both outaged -> outage error

## Read-list (in order)

1. `CircuitBreakerAiGateway` + `Ext002CallError` + `build_ai_gateway` in `apps/backend/modules/intake/adapters/ai_provider_ext.py` - how a breaker only counts `retries_exhausted=True`, and how the builder composes wrappers (~2.5K tokens)
2. `AiGateway` port in `apps/backend/modules/intake/adapters/ai_gateway.py` - the protocol contract the fallback wrapper conforms to (~1.5K tokens)
3. `OpenAiCompatibleAdapter` (from #379) - the adapter type the fallback wraps (skim; it lands in the same package)
4. Fallback composition pattern in `tests/unit/test_notify_fallback.py` + `apps/backend/modules/notify/facade.py` (`send_with_fallback`) - the repo's existing WhatsApp-first/SMS-fallback routing semantics to mirror (~2K tokens)
5. `docs/standards/third-party-integration-standards.md` + `docs/standards/ai-engineering-standards.md` A6 (multi-provider fallback chains) (~0.5K tokens)

## Do NOT read

- `pipeline.py` - the pipeline-side degrade-to-raw-review is already pinned by the existing closed-loop integration test; the chain itself just raises the outage error
- `config.py` - T01/T04 own the settings fields and wiring
- Frontend, integration/e2e harnesses

## Baseline verify (must pass before the first edit)

- `pytest tests/unit/test_ai_gateway_mock.py -q` passes (AI-gateway subset; full `npm run test:unit:backend` has pre-existing environment failures unrelated to this work)
- `npm run typecheck` - currently blocked by ENOSPC (no space on C:); free C: space or redirect npm cache/temp to D: first. The fallback must be mypy --strict clean

## Done-verify (acceptance criteria -> commands)

- `pytest tests/unit/test_ai_gateway_mock.py -q` passes (existing + new fallback tests)
- New tests: primary success (secondary untouched); primary outage -> secondary success (effective provider/model = secondary); primary contract rejection (secondary NEVER called); open primary breaker -> secondary routed; both outaged -> `Ext002CallError(retries_exhausted=True)` with no partial result; effective provider/model accessible after success
- `npm run check:ai-tracing` (pre-commit `check_ai_tracing` script) green over the new file
- `npm run typecheck` clean (once disk space resolved)

## Handoff notes

- Each provider in the chain is ALREADY wrapped in its own breaker by the builder (T04's composition) - `FallbackAiGateway` itself assumes two `AiGateway` instances and routes between them; it does not own breaker state
- The effective provider/model surface: the simplest shape is a small typed result (e.g. `CalledProvider`/`EffectiveCall` namedtuple or a method on the gateway) carrying `provider` + `model`; T04's pipeline bookkeeping must be able to read it after a successful `structure` call - keep it cheap and typed
- Routing decision is on the `retries_exhausted` flag ONLY: `True` -> try secondary, `False` -> re-raise immediately. Never fall back on low `StructureResult.confidence` (ADR-0001)
- Both-outage: re-raise the primary outage error (or the secondary's if primary was contract-rejected - which can't happen since contract rejection propagates). Do not fabricate a fallback mock result - the mock is NEVER a chain terminator in a real-provider config
- `@observe` is mandatory on the fallback's public routing method (`check_ai_tracing.py` scans `modules/intake/`)
- Recovery is inherent to the wrapped breakers (cooldown + recovery probe); the chain needs no extra recovery logic
