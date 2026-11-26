# Brief - T2 Hash chain logic and verification

**Ticket:** #236 · **Parent:** #234 PHASE-4 · **Refreshed:** 2026-08-27
**Reading surface:** ~4K tokens (budget 10K) - within budget

## Scope

Implement the deterministic SHA-256 hash computation for the audit chain and a chain verification function. Pure logic, no database writes. The hash function produces a deterministic digest from event fields; the verification function iterates a list of rows and asserts chain integrity.

Acceptance criteria: see #236 body verbatim.

## Read-list (in order)

1. `docs/architecture/internal-modules.md` - MOD-011 section for hash chain specification (~1K)
2. `docs/adr/0002-transactional-outbox-as-async-seam.md` - section 5 on audit events (~0.5K)
3. `tests/unit/test_consent_state_machine.py` - example of pure-logic parametrized tests for style reference (~1K)
4. `tests/unit/test_envelope.py` - another pure-logic test example (~0.5K)

## Do NOT read

- Other module code, bus infrastructure, schema DDL files, docs/archive/.

## Baseline verify (must pass before the first edit)

For this ticket: `npm run test:unit:backend`.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` (all hash chain tests green)

## Handoff notes

- `compute_audit_hash(event_type, actor_id, target_id, scope, metadata, timestamp, prev_hash) -> str`: SHA-256 over a canonical string. Use sorted JSON keys for metadata to ensure determinism. Return hex digest.
- `GENESIS_HASH = hashlib.sha256(b"CareSetu-audit-genesis").hexdigest()` - hardcoded constant.
- `verify_chain(rows)`: iterate in timestamp order, recompute each hash, assert `row.hash == computed`. First row's `prev_hash` must equal `GENESIS_HASH`. Return bool.
- Tests: 3-event chain verifies, tampered actor_id breaks chain at that row, single-row chain (genesis -> first event) verifies.
- Place the logic in `modules/audit/domain/chain.py` or similar within the audit module.
