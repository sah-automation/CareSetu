# Brief - T11 AI pipeline degradation paths

**Ticket:** #355 · **Parent:** #344 · **Refreshed:** 2026-09-08
**Reading surface:** ~9K tokens (budget 10K) - within budget

## Scope

Care never stalls on the AI: a per-call timeout of <=30s with up to 3 retries (exponential backoff) and malformed provider output both mark the job failed (ai_job.failed) and degrade the intake to doctor-reviews-raw-transcript, leaving the capture durable. Budget exhaustion stops new calls. Before any LLM egress, consent is checked (fail-closed - a missing grant or revocation means no egress and raw review; egress carries only intake context, never name/phone/full record) and every successful egress is written to the audit trail. A low-confidence structuring outcome publishes pre_summary.low_confidence and the pre-summary is forced into doctor review.

Acceptance criteria:

- [ ] Timeout-after-3-retries and malformed output paths mark ai_job.failed, leave the intake durable, and publish ai_job.failed
- [ ] Budget exhaustion hard-stops new AI calls and degrades the intake to raw review
- [ ] A missing or revoked consent blocks egress (fail-closed, tested) and degrades without sending PHI
- [ ] Successful egress is PHI-minimized (only intake context) and audited via record_egress_disclosure
- [ ] Low-confidence structuring sets the flag and publishes pre_summary.low_confidence; the pre-summary then requires doctor review

## Read-list (in order)

1. `docs/standards/third-party-integration-standards.md` EXT-002 - timeout/retry/degradation rules (~2K)
2. `docs/standards/security-phii-standards.md` + `ai-engineering-standards.md` - consent fail-closed, PHI-minimized egress, audit (~2K)
3. `apps/backend/modules/consent/facade.py` - check_consent + record_egress_disclosure signatures (~1.5K)
4. `apps/backend/modules/consent/domain/events.py` - RecordScope for the egress audit context (~1K)
5. Budget meter from T06 + pipeline happy path from T10 - hard-stop gate and ai_job.failed emission points (~1.5K)
6. `apps/backend/modules/intake/domain/state_machine.py` (T02) - low_confidence derivation and forced doctor review (~0.5K)

## Do NOT read

- `docs/archive`
- frontend sources
- partner/iAM internals
- worker internals

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - 1343 passed (verified 2026-09-08)
- `npm run typecheck` - clean (verified 2026-09-08)

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`

## Handoff notes

- Consent is fail-closed: missing or revoked grant means no LLM egress and raw doctor review, with no PHI sent. Egress carries only intake context (text/transcript, language, age range, sex).
- Degradation is durable: capture survives, ai_job.failed published, intake goes to doctor-reviews-raw-transcript.
- low_confidence -> pre_summary.low_confidence published and structurally forced into doctor review (per ADR-0001).
