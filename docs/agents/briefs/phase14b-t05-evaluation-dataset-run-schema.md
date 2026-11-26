# Brief - #766 Evaluation dataset, run, and judge score schema

**Ticket:** #766 - **Parent:** #761 - **Published:** 2026-10-23
**Reading surface:** ~7K

## Scope

Add versioned evaluation datasets and examples, judge run records, and extend evaluation scores with an optional run reference and metadata, a judge source, and a partial unique key for judge rows.

- [ ] Dataset versions carry name, version, and status (draft, active, retired).
- [ ] Examples carry task type, input, expected output, and tags.
- [ ] Judge runs carry dataset version, budget, status, and run reference.
- [ ] Evaluation scores accept source judge with run reference and metadata.
- [ ] Existing code and human uniqueness is unchanged and judge uniqueness is partial.
- [ ] The migration follows the current head and the migration check reports a single head.

## Blocked by

- #765 - Observability security signal, CSP aggregate, and alert delivery schema

## Read-list (in order)

1. Spec #761, evaluation decisions and schema registration decisions.
2. The existing evaluation score model, its migration, and the golden dataset.
3. The evaluation domain and the worker job pattern.

## Do NOT read

- docs/archive/
- Production data paths.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run typecheck`
- `npm run migration-check`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run migration-check`
- `npm run typecheck`

## Handoff notes

- Production content cannot enter the observability schema.
- Active dataset immutability is enforced in the service layer, not by deleting history.
- Do not change existing score uniqueness for code and human rows.
- Read only the named sections and grep for interfaces by name. Do not read whole files, unrelated modules, or generated files.
