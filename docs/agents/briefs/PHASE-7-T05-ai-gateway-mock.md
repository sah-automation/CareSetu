# Brief - T05 AI gateway port + mock provider + AI config

**Ticket:** #348 · **Parent:** #344 · **Refreshed:** 2026-09-08
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

The EXT-002 seam becomes real and safe before any pipeline uses it: a provider-agnostic AI gateway port with three operations matching the egress map (`transcribe`, `structure`, `draft_rx` - the last a declared contract for Phase 8), a deterministic in-process mock provider (clean confidence ~0.8, low ~0.5, switchable for tests/CI), and fail-closed settings: provider selection is a config knob, a real provider key is refused in dev/test unless demo mode forces the mock. Concrete methods carry the tracing annotations so the pre-commit AI-tracing gate over the intake module stays green.

Acceptance criteria:

- [ ] Gateway port declares transcribe/structure/draft_rx and both mock and provider adapters implement them
- [ ] Settings select provider with a fail-closed default; a real provider key in dev/test without demo mode is refused at construction
- [ ] Egress payloads carry only intake context (transcript/text, declared language, age range, sex) - no name/phone/full record
- [ ] The pre-commit AI-tracing gate passes over the intake module (all AI-named classes traced)
- [ ] Unit tests switch clean vs low confidence via the mock knob

## Read-list (in order)

1. `CONTEXT.md` glossary - transcription/structuring confidence semantics (~0.5K)
2. `docs/standards/ai-engineering-standards.md` - tracing, cost, PHI-minimized egress (~2K)
3. `docs/standards/third-party-integration-standards.md` EXT-002 - timeout/retry/degradation discipline (~1.5K)
4. `apps/backend/scripts/check_ai_tracing.py` - the pre-commit gate this must satisfy (~0.5K)
5. `apps/backend/modules/notify/adapters/transport.py` - HttpProviderChannel timeouts/backoff + CircuitBreaker pattern (~1.5K)
6. `apps/backend/app/config.py` - settings pattern for the provider/demo-mode knobs (~1K)
7. `apps/backend/observability/langfuse_client.py` - tracing seam to annotate through (~0.5K)

## Do NOT read

- `docs/archive`
- frontend sources
- intake schema/state machines/consumer
- pipeline internals

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - 1343 passed (verified 2026-09-08)
- `npm run typecheck` - clean (verified 2026-09-08)
- `npm run lint` - pre-commit incl. the AI-tracing gate

## Done-verify (acceptance criteria → commands)

- `npm run lint` (pre-commit incl. AI-tracing gate)
- `npm run test:unit:backend`

## Handoff notes

- Egress payload minimum: transcript/text, declared language, age range, sex only - no PII (name/phone/full record). AUDIT: this is a hard security gate, mirror RecordScope-style minimal context.
- Mock knob must be switchable to produce clean (~0.8) vs low (~0.5) confidence for tests/CI.
- draft_rx is contract-only in this phase; it becomes live in Phase 8.
