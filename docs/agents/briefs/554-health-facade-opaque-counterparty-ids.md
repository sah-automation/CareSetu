# Brief - 554 Health facade: treat live-relationship counterparty ids as opaque text

**Ticket:** #554 · **Parent:** #553 · **Refreshed:** 2026-09-27
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

A patient's first acknowledged health-background save **succeeds**, and grants the `health_background` scope to exactly the counterparty lineages discovery actually found. Acceptance criteria are in the ticket; the load-bearing ones are that a granted `doctor`-namespace consent with a **non-numeric** counterparty id no longer raises out of discovery, that the method is renamed to return counterparty ids (a set of strings), and that the auto-grant passes each discovered id through **unchanged** so the grant lands on the discovered lineage triple rather than a re-derived orphan.

Unchanged by contract: the first-save acknowledgment contract, the `health_background` scope vocabulary, the fail-closed consent gate, the egress ledger, and the transaction boundary (grants in the snapshot write's transaction, cache invalidation after commit).

## Read-list (in order)

1. **`_discover_live_relationship_doctors`** in the health module facade - the coercion site. Currently returns `set[int]`, and the set comprehension calls `int(item.counterparty_id)` on every consent-log row whose `counterparty_type == "doctor"` and `status == "granted"`. That single call is what raises. Docstring states the live-relationship definition (live standing grant of any scope, OR assigned doctor on an open care case) - that definition does not change. Also read the module constants `_HEALTH_BACKGROUND_SCOPE` and `_COUNTERPARTY_TYPE_DOCTOR`. (~450 tokens)

2. **The first acknowledged save that calls discovery** - same facade. Read the whole method: the acknowledgement gate, the snapshot write, the discovery call, the grant loop, and the post-commit invalidation loop. Note the grant and invalidation call sites both iterate the discovered set and re-derive the id as `str(doctor_id)` - that re-derivation is the quieter defect. (~1.1K tokens)

3. **`ConsentFacade.grant_consent_on`** and **`ConsentFacade.invalidate_consent_cache`** - both already take `counterparty_id: str` and pass it straight through. **Neither signature changes.** This is the seam where "pass the discovered id through unchanged" actually lands. (~300 tokens)

4. **`ConsentFacade.list_consents`** - opens its own connection, selects the lineage columns for the patient, orders pending-first. Read it only to confirm the shape of `item.counterparty_id` (text) and the filters the discovery applies. (~280 tokens)

5. **The consent schema's lineage table** - `counterparty_id` is a **`Text`** column, not an integer. Read the column, the `counterparty_type` CHECK constraint (`doctor` / `lab` / `chemist`), and the uniqueness key on `(patient_id, counterparty_type, counterparty_id, record_scope)`. This is the physical proof that the id is opaque text and the orphan-triple failure is real. (~600 tokens)

6. **`CareConsoleFacade.list_open_case_doctor_ids`** - returns `set[int]` from a `BigInteger` FK, including the unclaimed-row path that resolves pre-summary assignment through the intake seam. Both sides must end up in the same namespace, so read enough to know what it returns and nothing more. (~710 tokens)

7. **The existing health-background facade test** - `test_health_background_facade.py`. Read the `StubConsentFacade` (records 5-tuples on `grant_consent_on`), the `StubCareFacade`, the `_consent()` factory, and `test_acknowledged_first_save_auto_grants_live_relationship_doctors`. **Extend this, do not replace it** - its numeric-only fixtures are the reason the bug shipped. (~1.1K tokens)

8. **ADR-0018, decision D3** and **ADR-0004** - the auto-grant's transaction and deferral contract, and the consent-gate cache invalidation rule. (~1.2K tokens)

## Do NOT read

- The intake module's `pick_doctor` and its egress pipeline. Those are the **producers** of the ids; the fix is to tolerate them, not change them.
- The doctor's account-menu disc, the doctor-read vocabulary (explicitly Out of Scope on the parent).
- `docs/archive/` (the PRD supersedes it), binary assets, migration files, CI config.
- The route layer - the fix is below the route and the envelope tests must stay green untouched.

## Baseline verify (must pass before the first edit)

```bash
node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit/test_health_background_facade.py tests/unit/test_health_background_route.py -q
```

Confirmed green on the untouched tree at brief time: **27 passed**.

## Done-verify (acceptance criteria → commands)

- Facade unit test asserts the exact grant tuples for a non-numeric id and that the call does not raise:
  ```bash
  node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit/test_health_background_facade.py -q
  ```
- Everything the fix must leave untouched stays green - the full backend unit suite:
  ```bash
  npm run test:unit:backend
  ```
- Strict typing holds after the return type becomes `set[str]`:
  ```bash
  npm run typecheck:backend
  ```

## Handoff notes

- **#552 (closed, `f10f1b2`)** fixed the _frontend_ half of the health-background bug: the ack-required branch now turns a stale-read refusal back into a question. It could not have worked, because the backend was 500ing below the route. Do not re-touch the frontend in this slice.
- **Premise correction (recorded on #553).** The parent spec claims intake pick-doctor writes a partner slug. It does not - `pick_doctor` takes `partner_id: int` and writes `str(partner_id)`, a numeric string. The only non-numeric producer today is the AI egress pseudo-counterparty, registered under the id `intake-ai` in the `doctor` namespace and read by the intake pipeline's consent check and egress disclosure. So user story 15 on the parent ("intake-pick doctors don't receive the grant") is **not** a symptom of this bug - it is the Out-of-Scope doctor-id vocabulary split. Do not widen this slice to chase it.
- **`intake-ai` is inert and will land in the target set.** It never requests the `health_background` scope, so the extra grant is harmless. Tolerating arbitrary ids was chosen over hardcoding a foreign module's identifier into the health module. Flagged, not special-cased, deliberately.
- **The test must use a non-numeric id.** Numeric fixtures cannot reach the bug - that is exactly the gap that let it ship. A route-level test would only observe the 500; the facade method is the right seam because the bug is in its own logic.
- **Both halves matter.** Dropping the coercion stops the 500. Passing the discovered id through unchanged is what makes the auto-grant _take effect_ rather than persist an orphan lineage triple no doctor read matches. A fix that only does the first leaves user story 15's underlying mechanism unaddressed for `intake-ai`.
