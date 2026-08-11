# ADR-0003: DB-per-module isolation on a single PostgreSQL instance

**Status:** accepted
**Date:** 2026-08-10
**Decides:** Storage isolation strategy - one PostgreSQL instance, eleven private schemas, machine-enforced boundaries.
**Traceability:** `internal-modules.md` §1, `coding-standards.md` §2/§5, `PHASE-1-FOUNDATION` (issue #16), `NFR-001`, `NFR-004`.

## Context

The `NFR-001` cost floor forbids separate database instances per bounded context, yet the architecture must stay re-cuttable into services later without redesign. If module isolation relies on review discipline alone it erodes within a few phases; every later phase inherits whatever boundaries Phase 1 establishes, and small deviations now compound into a large re-cut later.

## Decision

1. **One PostgreSQL instance, eleven private schemas, one per module.** No cross-schema SQL, no foreign keys across schemas, and namespace-prefixed tables (`consent_consents`, `care_prescriptions`, …) so table provenance is readable at a glance.
2. **Only two cross-module seams exist.** Sync via `facade.py` (the only legal import target across modules) and async via the outbox event bus (ADR-0002). No module ever queries another module's tables.
3. **Transport carve-out.** The dispatcher and the migration harness are the only cross-schema readers in the system, and they touch outbox/schema plumbing only - never domain tables. This is whitelisted in the boundary checker, not an accident.
4. **Enforced in CI from day one.** A boundary checker walks the import graph and rejects module→module imports of `domain`/`schema`/`adapters`; the migration gate rejects cross-schema foreign keys and keeps a single migration head. Both run in pre-commit and CI.

## Considered options

- **Separate database instances/containers per module:** rejected - multiplies hosting cost, violating `NFR-001`.
- **One shared schema with ownership conventions:** rejected - nothing stops a stray join or FK from coupling contexts, and a later re-cut into services becomes a data-migration project.
- **Review-only enforcement:** rejected - the isolation rule is a non-negotiable seam; the roadmap targets it as CI-enforced from Phase 1.

## Consequences

- The bootstrap migration (`v0.0__bootstrap_schemas`) carries its own frozen copy of the module names (`FROZEN_MODULE_SCHEMAS`, issue #47) and never imports `bus.bootstrap.MODULE_SCHEMAS`. A migration is immutable: it records the exact database state applied at its revision, so modules added by later phases arrive as new migrations, never as edits to the frozen tuple.
- The `audit` schema is append-only at the DB level (no UPDATE/DELETE grants) and written only by MOD-011.
- The monolith can be re-cut into services later without redesign: each module's schema + facade + outbox is already a bounded deployment unit.
- The boundary checker is itself under test (fixture violations must fail the gate) so the rule cannot silently weaken.
