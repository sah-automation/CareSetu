# Brief - 260 Phase-5 fix: dedupe grant_role upsert/reactivate (S6)

**Ticket:** #260 · **Parent:** #243 · **Refreshed:** 2026-09-01
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

`grant_partner_role` and `grant_operator_role` in `apps/backend/modules/iam/session_facade.py` are byte-for-byte parallel duplicates (finding S6): both do the same Suspended->Active UPDATE, existing-Active-grant SELECT, and INSERT-if-none, differing only in the role constant. Extract one parameterized helper and keep the two public wrappers (or one `grant_role`). No behavior change.

Acceptance criteria (from #260):

- [ ] A single shared `_grant_role(connection, identity_id, role)` (or equivalent) holds the upsert/reactivate logic; the two public functions delegate to it.
- [ ] Both caller sites keep their public names (see Handoff for call sites).
- [ ] IAM role-grant tests pass unchanged.

## Read-list (in order)

1. `apps/backend/modules/iam/session_facade.py` lines 471-505 (`grant_partner_role`) and 528-561 (`grant_operator_role`) - the two duplicates to merge; note the module constants `_PARTNER_ROLE` and `_OPERATOR_ROLE` they branch on. Also `_partner_role_status` 564-575 and `suspend_partner_role` 508-525 for surrounding idiom (~1.2K).
2. Call sites (so the public names are preserved): `iam/adapters/__init__.py` lines 43 & 119 (`grant_partner_role` - the `partner.activated` consumer), `iam/identity_facade.py` line 42 import + line 300 call (`grant_operator_role` - the operator seed/invite flow). Also check `iam/facade.py` re-exports (~0.8K).
3. `tests/unit/` IAM role-grant / operator-activation tests - find by grep for `grant_operator_role` / `grant_partner_role` in tests; these must stay green (~1.5K).

## Do NOT read

- notify/audit/partner internals, the MFA/session issuance logic (handled by #261), `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`

## Done-verify (acceptance criteria -> commands)

- IAM unit tests green (grep the role-grant test files and run those + the full unit suite)
- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`
- `npm run typecheck`

## Handoff notes

- The two functions differ ONLY in `_PARTNER_ROLE` vs `_OPERATOR_ROLE`; everything else (statement SQL, column names, ordering) is identical. A `_grant_role(connection, identity_id, role)` parameterized by the role constant cleanly collapses ~35 lines of duplication into one.
- Keep both public names (`grant_partner_role`, `grant_operator_role`) as thin wrappers so the callers in `iam/adapters/__init__.py` and `iam/identity_facade.py` need no changes - OR switch all call sites to one `grant_role` if the maintainers prefer a single entry point. Confirm which in the ticket.
- Note there is NO operator suspend mirror (`suspend_partner_role` is partner-only) - do not invent one; out of scope.
- The unit tests may patch/assert on rowcount via the `_FakeResult`/`_FakeScalar` mock idiom used elsewhere in this repo's iam tests - keep that contract.
