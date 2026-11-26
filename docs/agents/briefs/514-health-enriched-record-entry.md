# Brief - #514 Health stores enriched prescription.issued payload in record entry

**Ticket:** #514 · **Parent:** #512 · **Refreshed:** 2026-09-23
**Reading surface:** ~3K tokens (budget 10K) - within budget

## Scope

The health record entry created from a `prescription.issued` event (MOD-003) carries the enriched, self-contained snapshot: `items` and `attributed_doctor_name` copied from the envelope into the record entry payload, so the patient timeline (`GET /v1/records`) returns professional prescription detail without any extra reads. The tolerant consumer mirror accepts both enriched and legacy (pre-enrichment) envelopes, so replaying an old event id still stores `{prescription_id, status}` only and never breaks.

Acceptance criteria (from the ticket):

- [ ] A `prescription.issued` round-trip (integration) produces a wiretime `prescription` entry whose payload carries `items` and `attributed_doctor_name` exactly as delivered.
- [ ] Idempotent replayed `event_id` remains a no-op (no second ledger row, no second entry).
- [ ] A replayed/enqueued legacy envelope without the new fields is still accepted and stores the lean `{prescription_id, status}` payload (tolerant mirror).
- [ ] The tolerant mirror model accepts care's produced enriched envelope in the cross-module registry test.

## Read-list (in order)

1. Health's tolerant `PrescriptionIssuedPayload` consumer mirror - the model to extend with optional `items` + `attributed_doctor_name`; it stays the health-side contract (care owns the producer model) (~0.5K).
2. The `handle_prescription_issued` consumer - currently writes the hardcoded 2-key payload dict `{prescription_id, status}`; copy the new fields through only when present (~0.5K).
3. The integration prior-art `test_dormant_entry_consumers.py`: `test_prescription_issued_creates_prescription_entry` (round-trip, producer-shaped envelope helper + payload asserts), `test_replayed_prescription_issued_is_no_op`, and the producer-shaped envelope helper - extend with an enriched variant and a legacy variant (~1.5K).
4. The cross-module registry mirror-accept test in the care event suite (uses `model_validate` on the health mirror) - confirm extra producer fields are tolerated (~0.5K).

## Do NOT read

- Care's producer payload model or publish site (that is #513's surface; work from the spec contract, which this ticket's blocked-by #513 implements).
- Frontend modules, `prototype/`, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - verified green 2026-09-23 (2336 passed).
- `npm run test:typecheck:backend` - green. Integration file baseline: `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/integration/test_dormant_entry_consumers.py -q` - verified 8 passed. The full integration suite shows an unrelated early failure under load on this machine; rely on the file-scoped run.

## Done-verify (acceptance criteria → commands)

- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/integration/test_dormant_entry_consumers.py -q`
- `npm run test:unit:backend`, `npm run typecheck:backend`.

## Handoff notes

- The mirror model gains `items` and `attributed_doctor_name` as **optional**; making them optional is what keeps the legacy-replay tolerance (criterion 3) and the dev-seed path (#513) valid.
- The record entry payload `status` stays `"issued"` for this consumer; `chemist_name` is a reserved key produced by MOD-008 later, never this handler.
- The producer-shaped envelope helper in the integration suite mirrors care's field set (incl. `case_id`/`doctor_id`, which the mirror drops on validate) - add the enriched fields to that helper rather than inventing a new shape, and add a legacy (un-enriched) helper for the tolerance case.
- Registered-handler wiring and the `consumed_events` ledger are untouched - replay no-op must be re-proven, not re-implemented.
