# Brief - 273 Phase-5 review fix: credential_reviewed audit transaction boundary (P4, US-21)

**Ticket:** #273 · **Parent:** #243 · **Refreshed:** 2026-09-02
**Reading surface:** ~4K tokens (budget 10K) - within budget

## Scope

`get_verification_detail()` runs the profile/credential/history read in one `engine.begin()` transaction, then writes the `partner.credential_reviewed` outbox event in a **second** `engine.begin()` transaction. If the second write fails after the read commits, a credential was viewed but no audit event is recorded - a silent audit gap that breaks the ADR-0002 atomic-outbox invariant every other mutation follows. This is the review gap P4 (US-21 "every credential view is an audit event").

Merge the read and the outbox write into a single transaction so the audit event is committed atomically with the view that produced it.

Acceptance criteria (from #273):

- [ ] `get_verification_detail()` uses a single `async with self._engine.begin()` block for both the read queries and the outbox write.
- [ ] The outbox write is committed atomically with the read - no window for a silent audit gap.
- [ ] Existing verification detail tests still pass.
- [ ] No behavioral change visible to callers.
- [ ] `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`, `npm run typecheck` pass.

## Read-list (in order)

1. `apps/backend/modules/partner/facade.py` - `get_verification_detail` (1296-1416): the two separate `async with self._engine.begin()` blocks (read ~1308, outbox write ~1354). Read the whole method and the outbox helper it calls. (~1.5K)
2. `apps/backend/bus/events.py` / `modules/partner/domain/events.py` - `credential_reviewed_envelope(...)` - the payload shape the outbox write persists. (~0.8K)
3. Existing outbox-write-in-transaction pattern - grep another mutation in `partner/facade.py` (e.g. registration, operator decision) that already writes its outbox event in the same transaction, to mirror the exact helper signature. (~0.8K)
4. `docs/adr/0002-*.md` (grep for the outbox ADR) - the atomic-outbox rule this ticket restores. (~0.8K)

## Do NOT read

- partner routes, IAM/notify/audit module internals, `docs/archive/`, frontend.

## Baseline verify (must pass before the first edit)

- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- Verification detail tests green (grep `get_verification_detail` / `verification_detail` tests)
- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`
- `npm run typecheck`
- `npm run lint`

## Handoff notes

- The fix is mechanical: collapse the two `engine.begin()` blocks into one and move the `write_outbox` call inside the same transaction as the reads. Do NOT change the returned `PartnerVerificationDetail` shape or the audit-facade queries that assemble it.
- Watch for any read that currently happens AFTER the outbox write (the assembly uses audit-facade queries described in the ticket) - those may legitimately stay outside the mutation transaction, but the outbox event for `credential_reviewed` must be in the same transaction as the credential read it describes.
- The rest of the codebase already does atomic outbox; this method is the outlier. Align to the dominant pattern.
- Parent for all Phase-5 review-fix briefs is #243. Finding drawn from the code-review P4.
