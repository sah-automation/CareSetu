# Brief - FIX 5 Repo-wide event-name gate + otp domain + roadmap migration fix

**Ticket:** #105 · **Parent:** #51 · **Refreshed:** 2026-08-14
**Reading surface:** ~4K tokens (budget ~10K) - within budget

## Scope

Repo hygiene in two small pieces: the pre-commit `check-event-names` hook scans the full tree (not just changed files) and gates the `otp` domain alongside `patient`, with the one legitimate legacy test token (the `otp.sent` outbox-row local) renamed; and the roadmap's stale single-script migration name is corrected to the shipped alembic series.

Acceptance criteria:

- [ ] `.pre-commit-config.yaml`: `check-event-names` hook runs repo-wide (`pass_filenames: false`, `always_run: true`) like `check-module-boundaries`.
- [ ] `check_event_names.py` falls back to `git ls-files -z` when invoked with no files; `_GATED_DOMAINS` includes `otp`; docstring caveat updated.
- [ ] `test_iam_registration.py:168` local variable renamed to `sent_row` (no false positive).
- [ ] `tests/unit/test_event_names.py` covers the no-files -> full-tree fallback path.
- [ ] `docs/roadmap/implementation-roadmap.md:180` references the shipped alembic series (`v1.0`/`v1.1`/`v1.2`) instead of the single `v1.0__init_iam.sql`.
- [ ] `npm run lint` passes and now exercises the repo-wide gate.

## Read-list (in order, token estimates)

1. `scripts.check_event_names` - the gate: `_GATED_DOMAINS`, `_legacy_tokens` (derives forbidden spellings from `bus.events` `EVENT_*`), `check_event_names`/`scan_file`, `main` (the arg-driven entry that gets the no-files -> `git ls-files -z` fallback), and the docstring's `otp.*` caveat (~1.2K).
2. `.pre-commit-config.yaml` - the local hooks block; mirror `check-module-boundaries`' `pass_filenames: false` + `always_run: true` on `check-event-names` (~0.6K).
3. `tests/unit/test_event_names.py` - the fixture-test surface and `_tracked_repo_files` helper (the exact `git ls-files -z` pattern the script's fallback reuses); add the no-files case (~0.8K).
4. `tests/integration/test_iam_registration.py` around line 168 - the local variable context to rename (the outbox row for `otp.sent`; assert payload + challenge_id, no behavior change) (~0.3K).
5. `docs/roadmap/implementation-roadmap.md` §2.2 line ~180 - the migration-name line to fix; confirm the shipped alembic series name from the `iam` migrations dir if unsure (~0.3K).

## Do NOT read

- Anything else - this ticket is a config + script + two one-line edits. No behavior code, no other modules, no frontend, `docs/archive/`.

## Baseline verify (from ticket)

- `npm run lint` (green this session: all 16 pre-commit hooks pass, event-name gate currently on changed-files mode)
- `npm run test:unit:backend` (green: 545 passed)

## Done-verify (acceptance criteria -> commands)

- `npm run lint` - now runs the repo-wide scan; must pass with the test local renamed
- `npm run test:unit:backend` - the new fallback-path test passes

## Handoff notes

- Parent #75 finding: the gate only scans changed files in pre-commit; `test_repo_is_clean` catches drift only in pytest. Repo-wide scanning closes the gap.
- Risk noted in the plan: gating `otp` could surface pre-existing snake_case tokens. The only known one (a local variable at test_iam_registration.py:168) is renamed in this ticket.
- `git ls-files -z` + stdlib subprocess is the exact pattern `test_event_names.py::_tracked_repo_files` already uses - keep the fallback stdlib-only like the other `check_*.py` gates.
