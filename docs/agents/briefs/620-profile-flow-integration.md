# Brief - #620 Prove the profile flow against real Postgres

**Ticket:** #620 · **Parent:** #599 · **Refreshed:** 2026-09-30
**Reading surface:** ~9.3K tokens (budget 10K) - within budget

## Scope

The doctor profile has no integration coverage today, so every central guarantee in this change is currently unproven. This ticket drives the real flow against real Postgres - register, submit credentials, operator approve, then real HTTP profile reads and writes - and closes that gap.

Acceptance criteria:

- [ ] An address save resolves the PIN, writes the derived position and re-derives the directory entry, and a subsequent directory search returns the doctor at the new position.
- [ ] A profile save does not change the doctor's listed flag and does not change credential validity; re-approving does not duplicate the directory row, and neither does a profile save.
- [ ] An unresolvable PIN rejects the address write with a field-level error, and every other section still saves.
- [ ] Multi-valued specialties round-trip and match in a specialty-filtered search, and a doctor with no specialties still appears in an unfiltered search.
- [ ] A doctor whose PIN resolves outside the peri-urban belt still saves and appears under the wider-area fallback.
- [ ] The new table exists after upgrade and the migration round-trips down.

**Environment fact that governs this ticket:** `npm run test:integration` SKIPS in this environment. The tier connects to a local native PostgreSQL (`TEST_DATABASE_URL`, falling back to `DATABASE_URL`) and calls `pytest.skip` from the `db_engine` and `reachable_db` fixtures when it is unreachable. A skip is not a pass. Write the suite, run it, and record it as **written but not executed here** unless a reachable native Postgres is actually present. Never report this tier green on the strength of a skip. See Handoff notes for the exact wording to use in the closing comment.

## Read-list (in order)

1. `CONTEXT.md` build-session protocol, cross-reference rule and do-not-read gate - the doc map, and the rule that `docs/archive/` is never read (~0.6K tokens)
2. `docs/standards/coding-standards.md` section 6 (Tests) and section 7 (Data Durability) - the three-layer split (unit / integration facade+schema vs a real Postgres / contract), the rule that PRD acceptance criteria are the source of test names with the `FEAT-xxx` id in the test docstring, and the harness command table (~0.5K)
3. `docs/standards/api-standards.md` section 2 (Error Envelope) and section 3 (Validation & Schemas) - the `422` + `details` shape the unresolvable-PIN case must return, so the client can render it under the PIN input (~0.5K)
4. The integration conftest, in full - the session fixtures `database_url`, `db_engine`, `reachable_db`, `throwaway_schema`, plus the `seed_daltonganj_service_area(connection)` helper every partner fixture re-seeds after truncating the vocabulary (~1.1K)
5. `tests/integration/README.md` - how the tier is run, the URL resolution order, and the bootstrap SQL for a local native Postgres (~0.3K)
6. The per-module `migration` + `clean_partner` fixture pair in the provider-profile integration suite (`_alembic_config`, `migration`, `clean_partner`, `_facade`) and the `EXPECTED_PARTNER_TABLES` set in the bootstrap-schemas suite - the replicate-per-module pattern the new suite copies verbatim, and the expected-table-set assertion the new table joins (~1.4K)
7. The real-path activation helper in the directory-search integration suite - `_activate_partner`, `_pending_partner`, `_seed_specialty`, `_expire_credentials`, `_CREDENTIAL_TYPE_BY_PARTNER_TYPE`, the `_phone_numbers` counter, and the `DALTONGANJ_LATITUDE` / `DALTONGANJ_LONGITUDE` / `PERI_URBAN_RADIUS_KM` constants. Register, then `submit_credentials`, then an attributed `operator_decision(approve=True)` is the ONLY way a real doctor becomes directory-visible; no fixture hand-builds those rows (~1.8K)
8. The real-HTTP seam in the partner-login-full-loop integration suite - `_app_client` over `create_app` + `Settings` with `app_environment="test"` and gateway JWT verify on, `_operator_token` over `issue_token`, `_bearer`, `_partner_session_token`, `_readMockOtp`, `_operator_approve`, `_register_partner`. This is how a facade-only suite becomes an HTTP suite against the same database; the new suite needs the same app-assembly step to make "real HTTP profile reads and writes" true (~1.4K)
9. The interfaces under test, located by symbol: `PartnerFacade.get_doctor_profile`, the four section-write methods the blockers land, `PartnerFacade.update_consultation_fee`, `PartnerFacade.search_directory`, `PartnerFacade.get_provider_profile`, `PartnerFacade.operator_decision`; the doctor console `router` (prefix `/v1/doctor`, `GET`/`PUT` `/profile` plus the photo verbs) and `directory_router` (prefix `/v1/directory`, `/search` and `/providers/{partner_id}`); the gateway edge `run_idempotent(request, call, *, namespace=...)`; and `DirectorySearchView.fell_back`, the wider-area flag the belt case asserts on (~1.2K)
10. `tests/integration/test_migrations.py` - `_version_nums` and `test_upgrade_head_then_downgrade_base_round_trips`, the existing up-and-down assertion the new-table case extends (~0.5K)

## Do NOT read

- Unrelated modules (intake, care, health, consent, audit, notify) and their integration suites.
- Other doctor-console pages and the patient profile pages.
- `docs/archive/` - superseded by the PRD.
- Anything under `docs/roadmap` or `docs/architecture` beyond what the read-list names.
- The unit suites for the same behaviour (the doctor-profile route suite and the doctor-profile facade suite) - they are the blockers' surface, not this ticket's.
- The frontend profile page and the public profile component - the assertions here are backend-observable.

## Baseline verify (must pass before the first edit)

- `npm run typecheck`
- `npm run test:unit:backend`
- `npm run test:integration` - **expected to report skipped, not passed**, in this environment. Read the skip count. If it reports passes, a native Postgres is reachable and the suite is genuinely runnable; say which in the closing comment.

## Done-verify (acceptance criteria -> commands)

- `npm run test:integration` - every acceptance criterion lives in this tier. Record the exact pytest summary line, including the skip count, verbatim in the closing comment.
- `npm run typecheck`
- `npm run lint`
- If and only if a native Postgres was reachable: re-run `npm run test:integration` twice to prove the suite is repeatable (the per-module `migration` fixture downgrades to `base` on teardown, so a second run must start clean).

## Handoff notes

- **Blockers.** This ticket waits on three siblings, all of which must have landed first:
  - **#611 (batch ordinal #12) Retire the whole-form profile write and register four section routes** - lands the four section-write routes on the doctor console `router` and removes `PUT /v1/doctor/profile`. Every "real HTTP profile read and write" assertion targets the new section routes, not the old whole-form one.
  - **#612 (ordinal #13) Make specialty search an overlap match and serve area from declared locality** - lands the overlap predicate in `search_directory` and drops the service-area join from the search read path. The specialty round-trip criterion and the locality-served `area` assertion both ride on it.
  - **#613 (ordinal #14) Extend the public provider profile with the new declared fields** - lands the extended `ProviderProfileView` behind `GET /v1/directory/providers/{partner_id}`. Read the response off the real endpoint, not off a facade stub, so the declared fields are proven to survive serialization.
- **The skip is the finding to report, not a footnote.** In this environment there is no local native PostgreSQL, so the `db_engine` session fixture and the per-test `reachable_db` probe both call `pytest.skip` and the whole tier reports skipped. A skipped suite proves nothing. Write the suite, get `typecheck` and `lint` green, and close the ticket with the literal status "written, not executed - no reachable native PostgreSQL in this environment; needs a CI run against the `integration` job's Postgres service to execute". Do not write "all tests pass". If the implementer can reach a native Postgres (the README has the `winget` bootstrap and the role/database SQL), run it for real and paste the pytest line.
- **Replicate the per-module fixtures; do not share them.** Every existing partner integration suite carries its own `migration` (module-scoped `command.upgrade(config, "head")` then `command.downgrade(config, "base")` on teardown) and its own `clean_partner` (truncate the partner and iam tables `CASCADE`, then re-seed the service-area vocabulary). That is the established convention, not an oversight. The new suite copies the pair from the provider-profile suite.
- **The truncation list needs one addition.** The existing `clean_partner` truncates `partner.partner_verifications`, `partner.partner_credentials`, `partner.partner_profiles`, `partner.partner_directory_index`, `partner.partner_outbox`, `partner.partner_service_areas` plus the `iam` tables. The PIN centroid table the address write resolves against is a new reference target: it must NOT be truncated (it is seeded vocabulary, like the service-area row) and it must be added to the `EXPECTED_PARTNER_TABLES` set in the bootstrap-schemas suite so the expected-table-set assertion covers the new table.
- **Assert the safety property at the row, not through the facade.** The "a profile save does not change the listed flag or credential validity" criterion is a SQL assertion against `partner_directory_index.is_active` and `partner.partner_credentials.verified` / `expires_at` / `revoked_at`, read back after the save. Asserting it through `search_directory` would pass even if the row were mutated, because search already filters on the status the write was supposed to preserve. Re-approving and re-saving must both leave exactly one `partner_directory_index` row for the partner - assert with a `COUNT`, not with a "fetch one" read.
- **The belt case is a data choice, not a code path.** Pin a PIN whose centroid sits outside `PERI_URBAN_RADIUS_KM` (the existing directory-search suite keeps a `_FAR_LATITUDE` of `24.90` on the Daltonganj meridian for exactly this) and assert the doctor still appears, under the wider-area fallback, by reading `fell_back` off the search view. Do not reach for a geocoder or a second coordinate.
- **Field-level error shape.** The house pattern for a module-owned validation failure is a module-domain `*ValidationError` exception plus an exception handler registered with `app.add_exception_handler` in the module adapter, returning `error_response(status.HTTP_422_UNPROCESSABLE_CONTENT, <CODE>, message, request=request, details=...)` from the shared gateway error helper. The intake module's validation handler is the reference. The PIN field detail must be keyed to the PIN field so the client can render it under that input - that key is the contract the #616 address card and #609 address write were built against, so read their briefs before choosing the key.
- **Relevant ADRs.**
  - **ADR-0003 (db per module isolation)** - the new PIN centroid table lives in the `partner` schema and nothing cross-schema may reference it. The migration-FK scanner in `npm run migration-check` will fail a cross-schema foreign key, so the profile's `address_pin` column is a plain value, not an FK.
  - **ADR-0012 (directory indexed per partner, one geo point)** - the decision this change amends: the entry carries "the partner's practice location **as recorded at registration**". #620 is the seam that proves the amended behaviour, and ADR-0021 supersedes this one.
  - **ADR-0002 (transactional outbox as the async seam)** - why operator approval writes the directory entry in the same transaction as the credential stamps, and why the test drives the real approve route rather than inserting an index row.
- **Judgement call while mapping the surface.** The ticket body names "the provider profile integration suite, for the operator-approval helpers". On the live tree that suite seeds profile, credential and index rows directly through `_seed_partner` rather than approving through an operator; the operator-approval helper actually lives in the directory-search suite (`_activate_partner`) and the HTTP one lives in the partner-login-full-loop suite (`_operator_approve`). The read-list points at both real locations instead. The provider-profile suite is still on the list, for the fixture pair and for the visibility-gate assertions the declared-band work must not break.
