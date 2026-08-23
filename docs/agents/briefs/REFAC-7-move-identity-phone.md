# Brief - 176 Move \_identity_phone to domain/shared.py, break circular dependency

**Ticket:** #176 · **Refreshed:** 2026-08-20
**Reading surface:** ~4K tokens (budget 10K) - within budget

## Scope

`session_facade.py` line 220 does a deferred `from modules.iam.facade import _identity_phone` - a sub-facade reaching up to its coordinator for a shared utility. Move `_identity_phone` from `facade.py` into `domain/shared.py` where the other shared helpers live. Both sub-facades and the coordinator import it from `shared.py`.

Acceptance criteria:

- `_identity_phone` is defined in `modules/iam/domain/shared.py`
- `modules/iam/facade.py` no longer defines `_identity_phone` - imports from `domain.shared`
- `modules/iam/session_facade.py` imports from `modules.iam.domain.shared` instead of `modules.iam.facade`
- The deferred import pattern in session_facade.py is removed
- `npm run typecheck` passes
- `npm run lint` passes
- `npm run test:unit:backend` passes

## Read-list (in order)

1. `modules/iam/facade.py` lines 67-80 - the function to move
2. `modules/iam/facade.py` lines 28-30 - the existing `domain.shared` import (where the function will be imported from)
3. `modules/iam/domain/shared.py` - the destination file (169 lines, already has `select`, `AsyncConnection`, `iam_identities`)
4. `modules/iam/session_facade.py` line 220 - the deferred import to fix
5. ADR-0006 - the sub-facade pattern and shared.py's role

## Do NOT read

- Test files (no changes needed)
- Frontend, deploy configs
- Other domain files beyond shared.py

## Baseline verify (must pass before the first edit)

- `npm run typecheck`
- `npm run lint`
- `npm run test:unit:backend`

## Done-verify (acceptance criteria -> commands)

- `npm run typecheck` passes
- `npm run lint` passes
- `npm run test:unit:backend` passes
- `grep -r "from modules.iam.facade import _identity_phone" apps/backend/` returns zero matches (no more circular dependency)

## Handoff notes

- `shared.py` already imports `select`, `AsyncConnection`, and `iam_identities` - the function fits without new imports
- The function is used in two places: `facade.py:166` (`emit_access_denied`) and `session_facade.py:220` (refresh replay path)
- After the move, `facade.py` should import it alongside `OtpSender` from the same `domain.shared` import block
- ADR-0006 section 4 explicitly places shared internals in `domain/shared.py` - this move is consistent with that decision
