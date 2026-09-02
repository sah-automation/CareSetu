# Brief - 276 Phase-5 review fix: collect practice_name at partner registration (P6, US-1)

**Ticket:** #276 · **Parent:** #243 · **Refreshed:** 2026-09-02
**Reading surface:** ~4K tokens (budget 10K) - within budget

## Scope

`partner_profiles.practice_name` (nullable) is never populated: `RegisterPartnerRequest` has no `practice_name` field, `register()` does not accept it, and `_insert_registered_profile()` does not write it. The queue item and verification-detail views already SELECT this column, so operators always see `null` for practice name. This is the review gap P6 (US-1 "registers with basic profile") and degrades the operator's ability to identify partners in the queue.

Collect an optional practice name at registration and thread it through to the INSERT.

Acceptance criteria (from #276):

- [ ] `RegisterPartnerRequest` includes `practice_name: str | None = None` field.
- [ ] `register()` facade method accepts and passes `practice_name`.
- [ ] `_insert_registered_profile()` writes `practice_name` to the INSERT.
- [ ] `GET /v1/partner/verification-queue` returns non-null `practice_name` when provided.
- [ ] `GET /v1/partner/verification/{partner_id}` returns non-null `practice_name` when provided.
- [ ] Tests verify practice_name flows through registration and appears in queue/detail.
- [ ] `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`, `npm run typecheck` pass.

## Read-list (in order)

1. `apps/backend/modules/partner/adapters/routes.py` - `RegisterPartnerRequest` (95-113) and `open_partner_registration` (151+): add the field and pass it through. (~0.8K)
2. `apps/backend/modules/partner/facade.py` - `register` (656-728) and `_insert_registered_profile` (430-474): add the parameter and the `.values(...)` entry. Note the existing `on_conflict_do_nothing` on `identity_id`. (~1.2K)
3. `apps/backend/modules/partner/schema/models.py` - `PartnerProfile.practice_name` (line 66, `String(120)`, nullable). A non-null value must fit 120 chars (validate length). (~0.4K)
4. Route tests: `tests/unit/test_partner_register_route.py` and the queue/detail route tests (grep `verification-queue` / `verification/{partner_id}` tests) to extend. (~1.0K)

## Do NOT read

- IAM/notify/audit internals, `docs/archive/`, frontend.

## Baseline verify (must pass before the first edit)

- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- Partner register + queue + detail route tests green (grep `test_partner_register_route`, `verification`)
- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`
- `npm run typecheck`
- `npm run lint`

## Handoff notes

- Keep `practice_name` OPTIONAL (`None`) so existing registrations that omit it still work - do not force it. The spec's "basic profile" is flexible, so optional is the right shape.
- The queue (`PartnerQueueItem.practice_name`) and detail views already SELECT the column, so no view/serializer change should be needed once the value is written. Verify rather than assume.
- Add a max-length constraint (the column is `String(120)`) so the Pydantic field rejects over-long values before the DB truncates/errors.
- Parent for all Phase-5 review-fix briefs is #243. Finding drawn from the code-review P6.
