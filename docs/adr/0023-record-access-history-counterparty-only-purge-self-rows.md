# ADR-0023: Record access history holds counterparty acts only; stored owner self rows are purged

**Status:** accepted
**Date:** 2026-10-08
**Decides:** Whether `health.health_record_access_history` keeps recording the record owner's own reads, and what happens to the self rows already stored. The ledger exists to answer one question - "who ELSE has seen my record" - so owner reads stop dual-writing a ledger row and an outbox envelope entirely, already-stored self rows are purged by a destructive data migration (alembic `5a6fc4715675`, v8.18), and the read path applies the same both-columns predicate as belt-and-suspenders. Cross-patient denied rows are retained as security events.
**Traceability:** `FEAT-003`, `MOD-003`, `MOD-011`, `KPI-006`, `ADR-0019`, spec #662 (US-14/15/21/22/25); implemented by #665. This ADR is the written authorization coding-standards §5 requires for the destructive migration.

## Context

The trust view ("Who accessed my record", `FEAT-003`) listed the patient's own reads alongside counterparty acts - noise in a view whose purpose is showing who else opened the record (spec #662, problem 2). The ledger had recorded every read attempt since PHASE-3 (`KPI-006`), and `MOD-011`'s hash chain accumulated the matching `record.accessed` / `record.denied` outbox envelopes. Stopping the owner-read writes therefore touches three coupled things at once: stored rows (cleanup needs a DELETE - a destructive migration), the read query (must not depend solely on the migration having run), and the audit-chain scope (owner self-reads stop being regulated acts).

## Decision

- Owner reads - the plain own-record read (`get_own_record`) and the allowed path of the addressed owner-only read (`get_record_as_owner`) - write no access-history row and no outbox envelope. The addressed read's DENIED path (a non-owner identity attempting a read) is kept: it is a security event, not self-access.
- A destructive data migration (`5a6fc4715675_v8_18__access_history_purge_self_rows`) purges stored self rows with the both-columns predicate: the row's actor is the `patient` type AND its accessor is the record's own owner identity. The downgrade is a no-op - a data purge is irreversible and the read filter hides self rows either way.
- The read query excludes the same both-columns predicate at read time (belt-and-suspenders), so a database the migration has not touched still answers only counterparty rows.
- `KPI-006` is restated as "100% of counterparty read attempts logged": allowed partner/console reads, consent-gated reads, and every denied attempt - owner self-reads are no longer a logged category.

## Rejected alternatives

- **Filter-only (no purge):** leaves meaningless rows in the ledger forever, keeps the trust view's storage scaling with noise, and contradicts spec #662 US-15 ("self-access rows already stored in the ledger purged").
- **Accessor-only filter (`accessor_identity_id <> owner`):** doctor console rows store partner ids in the same accessor column - a bare accessor comparison mis-handles patient/partner id-namespace collisions and would drop legitimate counterparty rows whose partner id numerically equals the patient's identity id.
- **Purge via app-level backfill script:** the purge must ship in the same release as the write-stop and be gated like every other schema-state change; the alembic single-head gate provides that.

## Reasoning

- **Purpose-fit:** the view's contract is "who else" (spec #662 US-14); owner rows never answered that question.
- **Both columns:** keying on actor type AND accessor identity makes cross-patient denied rows (patient-type actor, different accessor) survive while self rows die, in both the DELETE and the read filter.
- **Belt-and-suspenders:** deployment order ships migration with code; a code rollback after the migration still hides self rows (harmless), and reads filter correctly even if the migration has not run.
- **Audit scope:** `MOD-011`'s chain accumulating only counterparty acts is recorded as an explicit spec consequence - no event names change, no registry change.

## Consequences

- Owner reads emit no `record.accessed` / `record.denied` envelopes; `MOD-011`'s hash chain accumulates counterparty acts only (spec #662 records this consequence).
- The "record access" regulated-act category in `error-handling-observability.md` §4 and `security-phii-standards.md` §6 is unchanged in name but now means counterparty record access in practice - owner self-reads are simply not ledgered ("Making owner-read audit retention configurable" was explicitly rejected in spec #662 out-of-scope: owner reads are simply not ledgered).
- The purge is irreversible; the no-op downgrade is deliberate.
- The integration suite seeds and proves the view via counterparty reads; owner-read tests assert zero rows instead of rows.
