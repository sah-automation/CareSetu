# Brief - FIX-7 Refactor HealthFacade egress log write across module boundary

**Ticket:** #227 · **Parent:** #209 · **Refreshed:** 2026-08-25
**Reading surface:** ~5K tokens (budget 10K) - within budget

**Blocked by:** #221 (consent_egress_log migration must exist)

## Scope

Health module no longer writes directly into consent schema. Egress write routed through consent facade in a documented cross-transaction pattern.

**Acceptance criteria:**

- `HealthFacade.read_consented_history` does not call `consent_facade.write_egress_log` directly
- Egress write is performed by the consent facade in its own transaction, or a documented pattern is used
- Module boundary is maintained: health module does not import consent schema models
- Integration test proves consent-gated read still writes to both ledgers
- `npm run test:unit:backend` passes
- `npm run test:integration` passes (if DB available)

## Read-list (in order)

1. `apps/backend/modules/health/facade.py:220-265` - `read_consented_history` method (~265 tokens)
2. `apps/backend/modules/consent/facade.py:649-685` - `write_egress_log` method (~821 tokens total, read 649-685)
3. `apps/backend/modules/health/adapters/routes.py:101-128` - consented-read route (~174 tokens)

**Total:** ~500 tokens of targeted reading, well within budget.

## Do NOT read

- Frontend code
- Other module facades
- Redis cache code
- Standards docs

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - verify current state
- `grep -n "write_egress_log" apps/backend/modules/health/facade.py` - confirm cross-module call exists

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` passes
- `npm run test:integration` passes (if DB available)
- `grep -n "from modules.consent" apps/backend/modules/health/facade.py` returns no schema imports (only facade import)

## Handoff notes

- The current pattern: `HealthFacade.read_consented_history` calls `self._consent_facade.write_egress_log()` inside the health module's transaction (line 254)
- This violates `coding-standards S2` (modules communicate only through facades or event bus)
- Options: (a) move egress write to a post-commit hook, (b) use the event bus, (c) document as justified exception for transactional consistency
- The key constraint: both the access history write and egress write must be in the same transaction for consistency
- Consider: accept this as a justified exception and document with an inline ADR comment, since the alternative (two-phase commit) adds significant complexity
