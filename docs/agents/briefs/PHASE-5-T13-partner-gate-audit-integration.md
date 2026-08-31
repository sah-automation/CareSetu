# Brief - T13 Partner gate audit integration (decisions + credential views)

**Ticket:** #256 · **Parent:** #243 · **Refreshed:** 2026-08-31
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

The audit depth for the partner gate (MOD-011 consumption). Every terminal decision (`partner.activated` / `partner.rejected`) and every operator credential view (`partner.credential_reviewed`, with actor + partner + timestamp) must reach the audit ledger, so regulated decisions and "who saw this document" are traceable.

From the perspective of trust: a complete, attributed trail exists for every operator decision and every credential view in the partner gate.

Implementation:

- Ensure the partner terminal events and `partner.credential_reviewed` are consumed by MOD-011 and appended to the audit hash chain (the regulated-act whitelist already names some of these events - wire them through the audit consumer path).
- The credential-revision audit layered on top of the terminal-decision audit.
- Unit/integration tests mirroring `test_audit_consumer.py` / `test_audit_chain.py` proving each decision and credential view yields an audit event.

Acceptance criteria (verbatim from #256):

- [ ] `partner.activated` / `partner.rejected` each yield a MOD-011 audit-chain append
- [ ] Every `partner.credential_reviewed` view yields an audit event attributed with actor + partner + timestamp
- [ ] The terminal-decision audit and the credential-view audit coexist (both present in the chain)
- [ ] Unit + integration tests mirror `test_audit_consumer.py` / `test_audit_chain.py`
- [ ] `npm run test:unit:backend`, `npm run typecheck`, `npm run test:integration` pass

## Read-list (in order)

1. `modules/audit/adapters/__init__.py` - the consumer pattern: `register_payload_model` + ledged-idempotent handler + `_run_handler` (the record-access handler at lines 130-166 is the exact template to copy for a per-event-type append) (~0.8K)
2. `modules/audit/domain/consumer.py` - the payload mirrors (`RecordAccessAuditPayload`, `build_record_access_row`) + the deterministic uuid5 actor/target derivation; add partner terminal + credential-review payload mirrors and row builders here (~1.2K)
3. `modules/audit/facade.py` - the append path (`_latest_hash` + `append_audit_event` / `append_record_access_event`); reuse for partner events (~0.8K)
4. `apps/backend/bus/events.py` - the T04-promoted `partner.activated`, `partner.rejected`, `credential.invalidated` constants + `REGULATED_ACT_TYPES` (they are already whitelisted literals); `partner.credential_reviewed` and its whitelist entry live here from T04 (~0.5K)
5. `tests/unit/test_audit_consumer.py` - THE test to mirror for the partner decision + credential-view audit appends (~3K)
6. `tests/unit/test_audit_chain.py` - the hash-chain test pattern for the coexisting terminal + credential-view events (~0.8K)

## Do NOT read

- iam internals, notify internals, `docs/archive/`. The audit module consumes partner events - it does not read the partner schema directly.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` (874 passed, 1 warning - clean baseline)
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- New audit-consumer/chain unit + integration tests green (subset of unit suite)
- `npm run test:unit:backend`
- `npm run typecheck`
- `npm run test:integration`

## Handoff notes

- Blocked by #252 (T08 - operator verification queue + approve/reject: the decision + credential-review events originate there). Also depends on T04 (#247) having promoted the partner event constants and added `partner.credential_reviewed` to `bus/events.py` and `REGULATED_ACT_TYPES` - confirm both before editing.
- The current audit consumer only handles `audit.event` (generic carrier, hardcoded `consent.<action>`) and `record.accessed`/`record.denied`. Partner terminal events arrive as their OWN event types, so add new `register_payload_model` + handler per partner event, mirroring the record-access handler (lines 130-166): event type IS the regulated act -> append directly, no act derivation (unlike the consent carrier).
- Whitelist state today: `partner.activated`, `partner.rejected`, `credential.invalidated` are ALREADY literal strings in `REGULATED_ACT_TYPES`. Add `partner.credential_reviewed` to the whitelist (T04 constant). Each whitelisted event -> one chain append.
- `partner.credential_reviewed` carries actor + partner + timestamp - map actor -> `actor_id` (deterministic uuid5), partner -> `target_id`, timestamp from payload, mirroring `build_record_access_row`'s use of `accessed_at`. One append per credential view (every view is traceable, not just a summary).
- Terminal-decision and credential-view appends share the same chain (`audit_events` with `prev_hash` linkage) - they "coexist" by both calling the append path; no second ledger.
- Idempotency via the audit `consumed_events` ledger (`record_consumed_event`), same as every other handler.
- Prior art: PHASE-4 T4 (#239) consumer, T5 (#238) record-access publishing - the pattern to replicate for partner events.
