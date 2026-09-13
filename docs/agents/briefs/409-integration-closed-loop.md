# Brief - 409 T12 Integration closed-loop: real metering + egress audit

**Ticket:** #409 · **Parent:** #397 · **Refreshed:** 2026-09-13
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

The integration closed loop proves the whole remediation end to end. The in-test HTTP stub serves the OpenAI-compatible wire boundary (migrated off the legacy seam by #404), and the closed loop asserts: one transcribe + one structure job per voice intake, completed rows carry real provider/model/tokens/cost, an egress audit row for both legs, and (post observe-and-warn) an exhausted meter still lets the pipeline complete to `ready_for_review`. Acceptances: the stub serves the OpenAI-compatible wire boundary; the loop asserts both job rows and real-cost reads; an egress audit row is asserted for both legs and the exhausted meter still completes.

## Read-list (in order)

1. `tests/integration/test_intake_closed_loop.py` - the existing stub + assertions; the legacy-provider references already migrated by #404; extend to assert job rows/egress/meter behavior (~4K)
2. `modules/intake/adapters/ai_provider_openai_compatible.py` - the wire shape the stub must serve (JSON structure + multipart transcribe, `usage` block incl. `x_groq.usage`) (~1K skim)
3. `tests/integration/README.md` - local native PostgreSQL requirement; the suite skips when unreachable (~0.3K)

## Do NOT read

- The rest of the unit suites, frontend sources, `docs/archive/`, unrelated integration specs

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - 1732 passed (verified 2026-09-13)
- Integration suite respects `tests/integration/README.md` (needs local PostgreSQL; skips if unreachable)

## Done-verify (acceptance criteria -> commands)

- `npm run test:integration` (closed loop) with local PostgreSQL up: asserts transcribe + structure job rows, real cost reads, egress audit row on both legs, exhausted meter still completes ready_for_review

## Handoff notes

- Blocked by #399 (real cost), #401 (transcribe job + egress audit), #404 (stub migrated off legacy), #408 (exhausted meter completes)
- The closed-loop stub move off `Ext002AiProvider` was started in #404's test migration - this ticket finishes asserting the NEW behavior on top of that migrated harness
- If PostgreSQL is unreachable locally, the suite skips; do not weaken the assertions to force a local-only pass
