# Brief - 01 Doctor cases projection on the doctor console facade

**Ticket:** #646 · **Parent:** #645 · **Refreshed:** 2026-10-06
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

A doctor console read that lists a doctor's open care cases as rows a doctor can tell apart at a glance. Each row carries the care-case facts the console already reads - case id, case stage, forced-review flag, created / updated timestamps - plus the patient's name, age, and a photo-presence flag, resolved at read time through the same degrade-safe identity-profile seam the patients list already uses.

The read lives in the console facade (MOD-012), not the care module: MOD-006 cannot read the identity schema, so the enrichment must happen at the seam that already composes care and identity reads. The care-scoped cases read keeps its current shape and its current consumers; this projection is additive and stores nothing.

Composition order matches the patients list: the facade's own active-doctor re-check runs before anything else. A profile read that fails degrades the whole batch to anonymous rows with a warning that carries no PHI - it never fails the list. Rows are ordered creation-ascending, closed cases are absent, and there is no new query parameter.

Every served row is access-logged with a caller-supplied surface marker naming this cases-list surface, and egress-disclosed against a live grant exactly as the patients list does - fail closed for a row with no live grant.

## Acceptance criteria

- [ ] The console facade exposes a cases-list read returning a list view of case rows. Each row carries case id, case stage, forced-review flag, created and updated timestamps, patient id, plus nullable patient name, patient age, and a photo-presence flag.
- [ ] Name and age come from the existing degrade-safe profile resolver, not a second one. A photo reference never appears on the read - only a presence flag.
- [ ] A failing profile read degrades the whole batch to anonymous rows, logs a warning carrying no patient identifier and no PHI, and still returns the list.
- [ ] A non-active or non-doctor partner is refused before any case, grant, or profile read happens.
- [ ] Closed cases are absent; rows are ordered creation ascending.
- [ ] Every served row is access-logged once with a cases-list surface marker, distinct from the patients-list marker.
- [ ] A served row backed by a live standing grant is egress-disclosed against that grant; a row with no live grant is not disclosed.
- [ ] No schema, no migration, no cross-schema SQL, and no cross-module import beyond the console facade's existing allowed set. The console facade still owns no schema of its own.
- [ ] Facade tests exercise all of the above against stubbed collaborator facades, reusing the patients-list stub pattern.

## Read-list (in order)

1. The `#645` spec's "Doctor console cases projection (MOD-012)" decision block - the field list, the composition order, the degrade rule, and the ledger discipline are all decided there; do not re-derive them. (~800 tokens)
2. `DoctorConsoleFacade.list_doctor_patients` and the module-level helpers above it (`_bucket_for`, `_filter_by_name`, `_grants_allow_contact`) - the composition order, the search-then-sort-then-page pipeline, and the per-served-page-row ledger loop you are mirroring. Also `_require_active_doctor`, `_resolve_patient_profiles`, `_live_grants`, `_authorizing_grant`, `_disclose_against_grant`. (~2K)
3. `doctor_models.py` in full - the wire DTO conventions (pydantic v2, `Field(default_factory=...)`, the docstring discipline that explains why `has_photo` exists instead of a photo ref). (~1.2K)
4. `HealthFacade.log_doctor_patient_view` signature - note the keyword-only `scope` parameter and its existing default marker; you pass a different marker, you do not change the default. (~250 tokens)
5. `ConsentFacade.record_egress_disclosure` and `ConsentFacade.list_counterparty_grants` signatures. (~200 tokens)
6. `CaseDetailView` and `CaseConsoleFacade.list_doctor_all_cases` - the case fields already on the wire, and that this read returns closed cases too (so you filter). (~400 tokens)
7. The stubbed-facade test module for the patients list - the five stub collaborators, the `_facade(...)` builder, the `_grant` / `_case` / `_profile` row builders, and the egress-kwargs assertion shape. Copy this shape. (~2K)
8. `docs/architecture/internal-modules.md` - the doctor-console module spec, including its registered schema-less deviation. (~800 tokens)
9. `docs/adr/0019-derived-doctor-patients-list.md` - the D3 ledger discipline you are deliberately extending to a second read surface. (~700 tokens)

## Do NOT read

- `docs/archive/` - the PRD supersedes it.
- The care module's schema, models file, or any SQL. You consume `CaseDetailView`; you never join it.
- The partner module beyond the two collaborator method signatures on the constructor.
- Any other data module's schema or internals.
- The whole frontend app. This ticket is backend-only; the route is #647 and the page is #652.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - **currently green: 2867 passed.**
- `npm run migration-check` - confirms the single-head gate and the cross-schema-FK scan, so "no migration introduced" is a measured fact.
- `npm run typecheck` - **currently green** (mypy `--strict` over 255 backend files, then `tsc --noEmit`).

The frontend unit suite has one **pre-existing** failure unrelated to this work: `record/page.test.tsx > RecordPage access history > shows an empty state when there is no access history` cannot find "No access yet.". It fails on the untouched tree. Do not attribute it to your change and do not fix it here.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` - the new facade cases are green and the existing 2867 still pass.
- `npm run migration-check` - still green, proving no migration and no cross-schema foreign key.
- `npm run typecheck` - mypy `--strict` is the gate that keeps the new DTOs and the stub signatures honest.
- `npm run lint` - ruff, bandit, and the module-boundary hook, the last of which enforces that the console facade's import list did not grow.

## Handoff notes

- **Reuse, do not re-create.** `_resolve_patient_profiles` already implements the wholesale-degrade convention this ticket requires (one `except` around the whole batch, a warning that names no patient, and `{}` returned). Adding a second resolver for the cases read is the specific failure mode the spec names.
- **The photo flag is a boolean by design.** `photo_ref` is a storage key in a private bucket; a leaked reference discloses the bucket layout. The existing `DoctorPatientRow.has_photo` docstring already explains this - the case row needs the same reasoning, not a new one.
- **The patients-list stub for the health facade takes no `scope` parameter.** If you pass a cases marker, update that stub's signature too, or every existing test in that file fails on an unexpected keyword argument. This is the one place where adding the marker ripples.
- **No schema.** If implementation pressure ever pushes toward a stored case-to-patient denormalisation, that is the signal the spec names: stop and write a fresh ADR rather than proceed.
- **No pagination, no sorting, no filtering.** Creation-ascending over the full derived list, and no new keyword arguments on the facade method.
