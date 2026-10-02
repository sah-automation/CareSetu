# Brief - 601 Ship the PIN centroid table and its bulk seed migration

**Ticket:** #601 · **Parent:** #599 · **Refreshed:** 2026-09-30
**Reading surface:** ~8.7K tokens (budget 10K) - within budget

## Scope

The practice position is derived from a 6-digit PIN code resolved against a bundled India-wide PIN centroid dataset. This ticket makes that dataset real: a table in the partner schema holding PIN as primary key with office name, district, region, latitude and longitude, seeded in bulk by a reversible migration. Until it lands, nothing else about the address can work.

Acceptance criteria (from ticket):

- [ ] The source dataset is fetched from a Government Open Data Licence India publication of all-India post office PIN codes, and source, licence and retrieval date are recorded in the repository alongside the seed file.
- [ ] A migration creates the table in the partner schema with PIN as primary key and the district, region, latitude and longitude columns, and seeds it through a bulk insert path - not row-by-row writes.
- [ ] The migration downgrade removes the seeded rows and the table cleanly, and the repository up-and-down round-trip passes.
- [ ] The integration-level assertion on the expected table set after upgrade is extended to include the new table.
- [ ] The single-head migration check passes with exactly one head.

## Read-list (in order)

1. `CONTEXT.md` - the build-session protocol, the cross-reference rule and the "Do NOT read" section, then the "Partner onboarding & gated activation" and "Provider directory & credential validity" glossary sections. Tells the implementer why the practice position is a stored coordinate today (the directory entry is a read-side cache, one geo point per partner) and which glossary terms the new table must not be confused with. (~1.35K tokens)
2. `docs/adr/0003-db-per-module-isolation.md` - the isolation decision, and in particular the consequence that a migration is immutable and never imports current source. This is the rule that makes the new migration hand-written raw `op.execute` SQL. (~0.75K tokens)
3. `docs/standards/coding-standards.md` §2 Module Structure, §3 Typing & Naming, §5 Migrations & Schema, §6 Tests (including the local harness table), §7 Data Durability. The additive-only migration rule, the `partner_`-prefixed table naming rule the boundary checker enforces, and the unit-vs-integration test split that decides where the new table's assertions go. (~0.65K tokens)
4. The partner schema model file - the module docstring, `MODULE_METADATA`, and the `partner_service_areas` `Table` declaration with its `UniqueConstraint` and `server_default=text("now()")` column style. This is how a partner-schema table is declared, and it is the closest existing analogue to the new table: a vocabulary, not an entity, with a natural key. (~0.75K tokens)
5. The two precedent migrations: the Daltonganj service-area seed (a vocabulary seed: `ON CONFLICT DO NOTHING` on the natural key so a re-run against an already-seeded database is safe, and a reversible `DELETE` downgrade) and the active-directory-index backfill (a data backfill: an idempotency guard that makes a re-run a no-op, plus a no-op downgrade when the converged data is not worth reversing). The new migration is a third shape - bulk seed - and it picks its guard and its downgrade from these two. (~1.6K tokens)
6. The integration migration seams: the `EXPECTED_PARTNER_TABLES` set and the `upgrade head` / `downgrade base` harness in the bootstrap-schemas suite, and the whole of the migration round-trip suite (`_alembic_config`, `_version_nums`, and `test_upgrade_head_then_downgrade_base_round_trips`, which asserts the version table starts empty, reaches the single head, and returns to empty). This is where the "expected table set" and "round-trip passes" criteria are actually proven. (~1.7K tokens)
7. The integration conftest - `database_url`, `db_engine`, `reachable_db`, `throwaway_schema`, and the `seed_daltonganj_service_area` helper. Note there is no "migration fixture": both migration suites drive the alembic command API directly against the session engine and skip cleanly when the native PostgreSQL is unreachable. (~1.05K tokens)
8. `docs/standards/api-standards.md` §2 Error Envelope and §3 Validation & Schemas. The contract the later address write depends on: a 422 with a `details` list of field errors, and a stable `SCREAMING_SNAKE` code. Read it to know what the unresolvable-PIN rejection will have to produce, not to build it here. (~0.4K tokens)
9. The repository ignore rules. There is no committed data-file convention in the tree today, and both `apps/backend/var/` and `/var/` are gitignored runtime scratch, so the seed file needs a committed home of its own. (~0.4K tokens)

## Do NOT read

- `docs/archive/` - superseded by the PRD.
- `docs/roadmap/implementation-roadmap.md` and `docs/architecture/internal-modules.md` - the module spec and traceability rows this table gains are owned by **#622**, not here. The roadmap's existing PHASE-5 geo-accuracy mitigation is the design rationale the parent already records; you do not need to read it.
- The whole dataset once fetched. Read its header, its row count and a few sample rows; never load it into context.
- `modules/partner/facade.py`, `directory_facade.py`, `credential_validity.py` and the operator gate facade. The PIN lookup itself is **#603**'s pure decision and **#609**'s write; this ticket lands the table and the seed only.
- `check_migrations_fk.py` and the `migration-check` driver script. You run the gate, you do not read it. It is worth knowing it asserts a single alembic head and scans for cross-schema foreign keys, which is why the new table gets no FK at all.
- The other 36 revisions. Two precedents are enough.

## Baseline verify (must pass before the first edit)

- `npm run migration-check` - single-head gate plus the cross-schema-FK scan. Verified green on this tree immediately before this brief was written, at single head `c4e1a97b2d30`.
- `npm run test:integration` - **environment-gated.** It skips cleanly unless a local native PostgreSQL is reachable via `TEST_DATABASE_URL` or `DATABASE_URL` (see `tests/integration/README.md`). A skip is not a pass for this ticket: the round-trip and the table-set assertion are two of its five acceptance criteria, so confirm the suite actually ran rather than skipping.
- `npm run typecheck` - `mypy --strict` over the backend.

Not needed here: `npm run test:e2e` (Playwright, slow, no browser-facing change), `npm run test:unit:backend` and `npm run test:unit:frontend` (no unit-level change in this slice), `npm run check:pages`.

## Done-verify (acceptance criteria to commands)

- `npm run migration-check` - proves the "single head, exactly one" criterion and that the new migration adds no cross-schema foreign key. The head id will have moved; that is expected.
- `npm run test:integration` - proves three criteria at once: the expected table set now includes the new table, the upgrade-to-head / downgrade-to-base round trip returns the version table to empty, and the seeded rows survive upgrade. Check the run is not a skip.
- `npm run typecheck` - the model declaration typechecks under `mypy --strict`.
- `npm run lint` - whitespace, ruff and the no-em-dash gate over the new migration and model code.
- Worth stating in the closing comment: the seeded row count, the bulk-insert mechanism chosen, and the source/licence/retrieval-date record. The reviewer cannot verify a licence from a diff that does not carry it.

## Handoff notes

- **No blockers.** The ticket's Blocked by section is "None - can start immediately", and that is correct. This ticket is on the critical path _outward_: **#609** (the address section write that resolves the PIN, writes the derived position and re-derives the directory entry) is blocked on it explicitly, and **#620** (the real-Postgres integration proof) transitively depends on it. #609 will need the exact table name, column names and primary key this migration creates, so pin those in the closing comment, not only in the diff.
- **Judgement call, recorded: there is no in-repo precedent for a bulk seed, and that is the main design decision in this ticket.** No existing revision reads a data file from disk - all 36 are pure `op.execute` SQL. An all-India PIN dataset is on the order of 150k rows, which cannot live as literals in a revision file. So the seed has to take a path the repo has not used before: either a single `INSERT ... SELECT` from a server-side `VALUES` list, or `op.bulk_insert` against a `sa.table()` declared inside the revision, or `op.execute` of a generated `COPY`-shaped statement. Whichever you choose, it must satisfy all three of: reversible by the downgrade, a re-run against an already-seeded database is a no-op, and not row-by-row writes. Say which mechanism you picked and why in the closing comment, because the next person to add a vocabulary will copy it.
- **ADR-0003 constrains the shape, and the harness confirms it.** `target_metadata` in the alembic environment is `None`, so nothing autogenerates and nothing reconciles. The model declaration and the migration SQL are two independent statements of the same shape and neither validates the other - which is exactly why the integration table-set assertion is the only real check that they agree. Get the name, the schema and the column set identical in both places by hand.
- **Judgement call, recorded: where the seed file lives is yours to choose, but it must be committed and must not be gitignored.** Both `apps/backend/var/` and `/var/` are ignored as runtime scratch, so a dataset dropped there would vanish for everyone else and break the migration. The natural home is beside the revisions, next to the migration that reads it. The source, licence and retrieval date go in a short record alongside the seed file, per the first acceptance criterion.
- **Judgement call, recorded: no foreign key, and the PIN is a string.** The primary key is a 6-digit PIN code, so it must be a character column, not an integer - leading zeros are meaningful and the dataset will carry them. There is nothing to key a foreign key to: a PIN centroid is a reference dataset, not a partner row, and ADR-0003 forbids cross-schema references anyway. Match the coordinate columns to the existing `Numeric(9, 6)` precision used by the profile's practice position, so the values drop straight into the derived-position write without a lossy conversion.
- **The region and district columns are the ones the later tickets actually read.** The parent decision states that district and state are derived from the PIN and shown back to the doctor as a read-only confirmation, and that a PIN resolving outside the peri-urban belt must still save. So the two text columns are load-bearing for the read-only confirmation, not decorative. Name them so the read side can find them without a translation table.
- **Relevant ADRs.** **ADR-0003** (db-per-module isolation) is the one that governs, and it is read-list item 2. **ADR-0012** (directory entry, one unit per partner) is adjacent and worth a skim if you want to know why the new table is a lookup rather than a column on the profile, but it is not required. The ADRs this parent work writes are reserved as **0021** and **0022** and are owned by **#622**; **0022** in particular will record the PIN-centroid-not-geocode decision that this ticket's table is the data half of. Do not write either one here.
- **A PIN that is not in the table is the designed failure mode, not a bug.** The parent decision is explicit that a PIN either resolves or it is not, with no partial resolution, no coarse fallback and no default position. Do not add a not-found row, a default centroid, or a nearest-neighbour fallback to make the seed look complete. The unlisted-PIN path raises an operator support request, and **#620** covers that queue; this ticket's only obligation is that the lookup can honestly say "no".
