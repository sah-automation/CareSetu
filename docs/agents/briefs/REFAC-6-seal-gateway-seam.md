# Brief - 175 Seal the gateway seam: re-export InvalidAccessTokenError from facade

**Ticket:** #175 · **Refreshed:** 2026-08-20
**Reading surface:** ~2K tokens (budget 10K) - within budget

## Scope

The gateway (`app/gateway/jwt_verify.py`) reaches past the facade into `modules.iam.domain.exceptions` for `InvalidAccessTokenError`. Re-export it from `modules.iam.facade` and update the gateway import so the facade is the only interface the gateway touches.

Acceptance criteria:

- `InvalidAccessTokenError` is re-exported from `modules.iam.facade`
- `app/gateway/jwt_verify.py` imports from `modules.iam.facade` instead of `modules.iam.domain.exceptions`
- `npm run typecheck` passes
- `npm run lint` passes
- `npm run test:unit:backend` passes

## Read-list (in order)

1. `modules/iam/facade.py` lines 12-58 - the existing re-export block (pattern to follow for `InvalidAccessTokenError`)
2. `app/gateway/jwt_verify.py` line 31 - the leak to fix
3. `modules/iam/domain/exceptions.py` line 50 - the class being re-exported

## Do NOT read

- Test files (no changes needed)
- Other domain files
- Frontend, deploy configs

## Baseline verify (must pass before the first edit)

- `npm run typecheck`
- `npm run lint`
- `npm run test:unit:backend`

## Done-verify (acceptance criteria -> commands)

- `npm run typecheck` passes
- `npm run lint` passes
- `npm run test:unit:backend` passes
- `grep -r "from modules.iam.domain" apps/backend/app/` returns zero matches (gateway no longer reaches into domain)

## Handoff notes

- Follow the existing re-export pattern: `from modules.iam.domain.exceptions import InvalidAccessTokenError as InvalidAccessTokenError` in `facade.py`
- The boundary checker (`scripts/check_module_boundaries.py`) does not scan `app/`, so this leak is not caught by CI - the grep in done-verify is the manual check
- ADR-0003 and coding-standards section 2 define the isolation rule: `facade.py` is the sole legal cross-module import target
