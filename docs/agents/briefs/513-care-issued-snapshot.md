# Brief - #513 Care publishes issued snapshot (items + attributed_doctor_name) in prescription.issued

**Ticket:** #513 · **Parent:** #512 · **Refreshed:** 2026-09-23
**Reading surface:** ~9K tokens (budget 10K) - within budget

## Scope

When a doctor approves a prescription (care module, MOD-006), the `prescription.issued` event now carries the frozen issued snapshot: the medicine items (`items`, each `{name, dose, frequency, duration}` with only `name` required) and the attributed doctor's display name (`attributed_doctor_name`, `str | None`). The name reuses the existing module-isolated partner seam (`attributed_doctor_name_resolver`) already used for the approve response; on a missing seam or unresolvable partner it degrades to `None`, never an error. The envelope's registry round-trip and emit-order guarantees hold with the new field set, and the dev-seed construction path stays compatible with the tolerant health mirror.

Acceptance criteria (from the ticket):

- [ ] `prescription.issued` payload gains `items` (array of `{name, dose, frequency, duration}`, each nullable except `name`) and `attributed_doctor_name` (`str | None`).
- [ ] `approve_prescription` publishes the enriched envelope with the items frozen at issue time and the resolver-resolved doctor name (resolved for the envelope, not only the response view); emit order stays `prescription.approved` then `prescription.issued` in the same transaction.
- [ ] Resolver returns `None` / resolver absent -> `attributed_doctor_name` is `None` in the envelope; approval still succeeds (no new failure path).
- [ ] Unit tests updated: field-set/no-PHI test reflects the new fields with the PHI note wording updated accordingly; emit-order, registry round-trip, and validate-through-registry tests still pass.
- [ ] Dev-seed path that builds a `prescription.issued` envelope still constructs a valid envelope (items optional in the tolerant mirror).

## Read-list (in order)

1. **Parent spec #512, "Event contract" + D1 + "Seam 3" sections** - the exact payload contract (`items` shape, `attributed_doctor_name` null semantics, no-PHI wording that needs reconciling) (~1.5K).
2. `PrescriptionIssuedPayload` + `prescription_issued_envelope` (care event domain) - the two interfaces to change; model docstring documents the `e-prescription` semantics (~1K).
3. `approve_prescription` (care facade) - the approve slice: item loading, the two `write_outbox` calls, the `attributed_doctor_name_resolver` seam and `_with_attributed_name`, and the `RxItemView`/`_to_rx_item_view` shape used to build the response `items` (the envelope's item shape drops `rx_item_id`/`prescription_id`/`sequence`) (~2K).
4. `_resolve_attributed_doctor_name` composition-root wiring (care never imports partner - the resolver is injected) and the dev-seed `rx_envelope` construction (must keep compiling; it builds the envelope from health's tolerant mirror with 3 fields) (~1K).
5. Tests: `test_care_events.py` header docstring (lines ~8-14 - currently claims `prescription.issued` is "no-PHI: ids and lifecycle facts only"; the spec (D1) deliberately moves the issued snapshot into the event, so reword rather than leave the false claim) + the field-set test + the registry round-trip + the health-mirror acknowledge test; `test_care_facade_rx.py` emit-order test + the two resolver-seam tests (~3K).
6. `REGULATED_ACT_TYPES` in the bus events module - confirm `prescription.issued` already registered; expected no change (~0.3K).

## Do NOT read

- Health consumer handling beyond the tolerant mirror model (`PrescriptionIssuedPayload` in the health domain events module) - that is #514's surface.
- Any frontend module, `prototype/`, `docs/archive/`, or unrelated care verticals.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - verified green 2026-09-23 (2336 passed).
- `npm run typecheck:backend` - verified green 2026-09-23.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` (care event + facade suites updated and green).
- `npm run typecheck:backend`.
- Targeted: `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit/test_care_events.py tests/unit/test_care_facade_rx.py -q`.

## Handoff notes

- The new fields are additive to health's tolerant mirror: `model_validate` ignores extra fields, so this ticket landing before #514 does not break `test_health_consumer_mirror_accepts_cares_produced_payload`. The mirror's own payload model is #514's concern only.
- Resolve the name for the envelope inside `approve_prescription` (reuse the injected seam); the response-view resolution already happens at the end of approve - the envelope must carry the same name, resolved defensively (None on miss, never raise).
- Items to freeze are already in scope at the approve site (`item_rows` → `_to_rx_item_view`); the envelope payload item must be the trimmed `{name, dose, frequency, duration}` shape, matching the spec contract.
- The dev-seed path builds `prescription.issued` from health's mirror model (3 fields) - untouched and still valid; do not force it onto care's payload.
- Pessimistic wording on field-set test: it asserts exact field membership; the new keys join the set, and `attributed_doctor_name` is `str | None` so the model dump includes it even when None.
- Use the glossary terms: `e-prescription`, `attributed_doctor`, `prescription.issued` - no drifted synonyms.
