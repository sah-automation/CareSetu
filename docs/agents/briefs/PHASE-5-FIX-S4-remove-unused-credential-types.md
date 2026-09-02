# Brief - 277 Phase-5 review fix: remove unused REQUIRED_CREDENTIAL_TYPES_BY_PARTNER (S4)

**Ticket:** #277 · **Parent:** #243 · **Refreshed:** 2026-09-02
**Reading surface:** ~1K tokens (budget 10K) - well within budget

## Scope

`REQUIRED_CREDENTIAL_TYPES_BY_PARTNER` in `modules/partner/domain/credentials.py` (line 35) is defined but never referenced anywhere in the codebase - only `ALLOWED_CREDENTIAL_TYPES_BY_PARTNER` is consumed (by `prefilter.py`). This is dead / speculative code flagged in the review as S4.

Delete the unused constant. Do NOT touch `ALLOWED_CREDENTIAL_TYPES_BY_PARTNER` or the `CredentialType` enum.

Acceptance criteria (from #277):

- [ ] `REQUIRED_CREDENTIAL_TYPES_BY_PARTNER` deleted from `modules/partner/domain/credentials.py`.
- [ ] Grep confirms no imports or references to the constant remain anywhere in the codebase.
- [ ] `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`, `npm run typecheck`, `npm run lint` pass.

## Read-list (in order)

1. `apps/backend/modules/partner/domain/credentials.py` - the constant at line 35 (lines 29-39), and note its docstring context is about the allowed set. Delete the `REQUIRED_CREDENTIAL_TYPES_BY_PARTNER` dict only. (~0.5K)
2. Grep the whole repo for `REQUIRED_CREDENTIAL_TYPES_BY_PARTNER` to confirm zero references before deleting (`rg` / the grep tool).

## Do NOT read

- anything else - this is a one-constant deletion.

## Baseline verify (must pass before the first edit)

- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`
- `npm run typecheck`
- `npm run lint`

## Handoff notes

- Confirmed dead: `prefilter.py` uses `ALLOWED_CREDENTIAL_TYPES_BY_PARTNER` only; the `REQUIRED_...` dict has no consumers. Safe to delete.
- Leave the `CredentialType` enum and `ALLOWED_CREDENTIAL_TYPES_BY_PARTNER` untouched - the pre-filter depends on them.
- Parent for all Phase-5 review-fix briefs is #243. Finding drawn from the code-review S4.
