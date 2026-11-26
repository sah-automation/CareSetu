# Brief - T08 Media upload + re-record facade

**Ticket:** #352 · **Parent:** #344 · **Refreshed:** 2026-09-08
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

Voice capture is durable and self-correcting: upload_intake_media stores an audio file with an upload-resilient transfer (auto-retry up to 3 times with backoff) and returns a media reference for the intake; re_record_intake attaches a fresh recording attempt, enforces the server-side 3-attempt cap (never just client-side), emits intake.retry_requested between attempts, and when attempts are exhausted forces the text path so the patient is never stuck.

Acceptance criteria:

- [ ] upload_intake_media retries the transfer up to 3 times with backoff on failure, then raises a typed error - never loses a partial capture silently
- [ ] Media reference returned on success records duration/size/attempt under the intake/ object prefix
- [ ] re_record_intake increments the attempt count and hard-stops at 3 (server-side, tested even when the client claims otherwise)
- [ ] Attempts exhausted routes the intake to forced text
- [ ] intake.retry_requested emitted on each re-record request

## Read-list (in order)

1. `apps/backend/modules/partner/adapters/artifact_store.py` - upload/store pattern for the intake/ prefix (~1.5K)
2. `docs/standards/security-phii-standards.md` (audio = PHI, encryption at rest, intake/ prefix) - hard security rules (~1.5K)
3. Issue #344 B3 fallback ladder + facade surface - the 3-attempt ladder and forced-text semantics (~1.5K)
4. `apps/backend/modules/intake/domain/state_machine.py` (T02) - re-record transitions and attempt cap semantics (~1K)
5. Intake event builders (T04) - intake.retry_requested envelope (~1K)

## Do NOT read

- `docs/archive`
- frontend sources
- AI gateway internals
- worker internals

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - 1343 passed (verified 2026-09-08)
- `npm run typecheck` - clean (verified 2026-09-08)

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`

## Handoff notes

- The 3-attempt cap is enforced server-side and tested even when the client claims more attempts - never trust the client.
- Audio is PHI: encryption at rest, stored under the intake/ object prefix; a failed transfer up to 3 retries then a typed error, never a silent partial.
