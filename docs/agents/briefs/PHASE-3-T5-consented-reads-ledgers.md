# Brief - T5 Consented history reads + two ledgers

**Ticket:** #214 · **Parent:** #209 PHASE-3 · **Refreshed:** 2026-08-24
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

The gate becomes the door on history: `read_consented_history(patient_id, scope, counterparty)` checks `check_consent` per read (no capability tokens anywhere - the previously specced consent_token param is dropped), while the owner always reads their own full record regardless of consents. One successful partner read writes exactly one row to EACH ledger: health-schema record access history (every attempt: owner, partner, denied) and consent-schema egress log (what left, when, to whom, citing lineage id + version + disclosed entries). A listing endpoint exposes the egress log so patients see "what has left your record".

Acceptance criteria: see #214 body verbatim.

## Read-list (in order)

1. Internal-modules MOD-003 + MOD-004 specs - the two-ledger division of responsibility (~1K)
2. CONTEXT.md glossary - egress log vs record access history vs revocation (never conflate them) (~0.5K)
3. Roadmap PHASE-3 testing decisions - which tier proves what (~1K)
4. Health + consent modules as T2/T4 landed them - facades, ledgers' table shapes, gate signature (diffs of blockers, ~2K)
5. IAM integration suite prior art for facade-over-real-Postgres patterns (~1K)
6. `docs/standards/security-phii-standards.md` - consent gating + PHI disclosure rules (~1.5K)

## Do NOT read

- Phase 4 audit-engine design; AI egress flows (Phase 7); frontend code; `docs/archive/`.

## Baseline verify (must pass before the first edit)

Recorded green on 2026-08-24: lint; typecheck; migration-check single head; backend units 654 passed.

For this ticket: `npm run lint`, `npm run typecheck`, `npm run test:unit:backend`, `npm run test:integration`.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` (route-level owner-only/RBAC suites)
- `npm run test:integration` (gated-read + dual-ledger one-row-each + denied-not-in-egress + egress-listing suites green)

## Handoff notes

- Neither ledger mirrors the other: one counterparty read = one row in each, answering different questions (attempt vs disclosure).
- Egress rows cite lineage id + exact version and the disclosed entry ids - this is what T8's "who has seen this" trail renders.
- Denied attempts land in access-history only, never egress.
- Owner path bypasses the gate entirely by design (consent governs sharing, never own access).
