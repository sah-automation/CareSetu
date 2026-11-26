# Brief - 265 Phase-5 fix: validated queue status filter (S12)

**Ticket:** #265 · **Parent:** #243 · **Refreshed:** 2026-09-01
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

`list_verification_queue` takes a free-string `status` defaulting to `"Under Verification"` and filters with `WHERE status == status` with NO validation - an unknown string silently returns an empty queue (finding S12). Follow the existing `_QUEUE_SORTS`/`InvalidQueueSortError` precedent (validated against a whitelist, mapping to a 422) and validate the status against the allowed statuses.

Acceptance criteria (from #265):

- [ ] `status` is validated against the partner status enum (`Registered`/`Under Verification`/`Active`/`Rejected`) before the WHERE clause; unknown status raises the analogous queue error and maps to a 422 with the repo envelope.
- [ ] The default `"Under Verification"` behavior is unchanged.
- [ ] Route + facade mirror the `_QUEUE_SORTS`/`InvalidQueueSortError` precedent.

## Read-list (in order)

1. `apps/backend/modules/partner/facade.py` - `list_verification_queue` (1028-1093; signature 1032; the free-string WHERE at 1071-1072), `_QUEUE_SORTS` (269-273), and the `InvalidQueueSortError` raise at 1047-1049 (~0.8K).
2. `apps/backend/modules/partner/domain/exceptions.py` - `InvalidQueueSortError` (31-36) - the precedent to mirror for `InvalidQueueStatusError` (~0.3K).
3. `apps/backend/modules/partner/adapters/routes.py` - `list_verification_queue` route (221-251; `status` Query default at 231) and the 422 mapping pattern (`INVALID_QUEUE_SORT` handler at 415-422, registered at 471) (~0.8K).
4. `apps/backend/modules/partner/domain/partner_status.py` (or wherever the `PartnerStatus` enum lives - grep it) - the canonical status values to whitelist (~0.3K).
5. `tests/unit/` - the queue-list tests (grep `verification_queue` / `InvalidQueueSort`) to extend with status validation (~1.5K).

## Do NOT read

- audit/notify/iam internals, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`

## Done-verify (acceptance criteria -> commands)

- Queue tests green (grep `verification_queue` tests and run them + full unit suite)
- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`
- `npm run typecheck`

## Handoff notes

- Exact precedent: `sort_by` is validated via `_QUEUE_SORTS` whitelist + `InvalidQueueSortError`, which maps to a 422 `INVALID_QUEUE_SORT` with a registered handler. Mirror it: a `_QUEUE_STATUSES` whitelist (from the `PartnerStatus` enum) + `InvalidQueueStatusError` + 422 `INVALID_QUEUE_STATUS`.
- The free-string `WHERE status == status` (facade 1071-1072) must only run AFTER validation; an unknown status becomes an explicit error, not an empty list.
- Keep default `"Under Verification"` exactly as-is (from route 231 and facade 1032).
- Do not change the sort behavior or touched-view shape; additive validation only.
