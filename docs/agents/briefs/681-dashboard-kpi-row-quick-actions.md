# Brief - 681 Dashboard: KPI row and quick actions

**Ticket:** #681 · **Parent:** #673 · **Refreshed:** 2026-10-09
**Reading surface:** ~1.8K tokens (budget 10K) - within budget

## Scope

A row of workload KPI tiles and a quick-actions row on the dashboard. Tiles: open care cases, pre-summaries awaiting review, current patients, and current consultation fee; each links to the relevant page. Current patients is backed by a new best-effort patients-count read (page 1, page size 1, using the returned total); on failure that tile degrades to an em dash rather than failing the page. Quick actions: Patients, My cases, Profile.

## Acceptance criteria

- [ ] Four KPI tiles: open cases, pre-summaries awaiting review, current patients, consultation fee
- [ ] Each tile links to its relevant route
- [ ] The current-patients count comes from a best-effort patients read using the returned total; a failure degrades to an em dash and the page still renders
- [ ] The open-cases count reflects the enriched cases feed, the awaiting-review count reflects the review queue, and the fee reflects the shared profile read
- [ ] Quick actions for Patients, My cases and Profile are present and link correctly
- [ ] Every new string ships in both English and Hindi (parity preserved)
- [ ] `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` pass

## Read-list (in order)

1. The dashboard page state and `load`, plus the sections added by #676 (enriched cases) and #678 (profile read) - the sources the counts read from. (~500 tokens)
2. `listDoctorPatients`, `ListDoctorPatientsParams` and `PatientsListView.total` in the doctor API client - the best-effort count read (page 1, per-page 1, use `total`). (~300)
3. The `doctorConsole` i18n namespace in both locales. (~300)
4. The dashboard test blocks. (~600)

## Do NOT read

- The backend.
- The profile page and the patients list page internals.
- `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - confirmed green 2026-10-09 (134 files / 2157 tests passed).
- `npm run typecheck:frontend` - confirmed green 2026-10-09.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend` - KPI tile and quick-action assertions, including the em-dash degradation on a failed patients read.
- `npm run lint`
- `npm run typecheck`

## Handoff notes

- **The patients-count read is best-effort and ledger-writing.** It is a consent-gated read that writes access-history/egress entries, so a failure must degrade the tile to an em dash and never fail the page (spec ledger note). Keep it isolated from the page `loadStatus`.
- **Counts must agree with their sections.** Open cases come from the enriched feed (#676), awaiting-review from the review queue, fee from the shared profile read (#678). Do not introduce a separate count source that can disagree.
- **Each tile is a link** to the page it summarises (user story 7).
- **No em-dashes anywhere** in code/comments, but the em-dash glyph is the intended degraded value for the patients tile - follow the spec and existing dash conventions in copy; keep the rest free of em-dashes (lint-gated).
