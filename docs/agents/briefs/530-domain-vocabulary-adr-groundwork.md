# Brief - 530 Domain vocabulary + ADR groundwork for the doctor-console/profiles batch

**Ticket:** #530 · **Parent:** #529 · **Refreshed:** 2026-09-24
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

Register the new domain vocabulary and architectural decisions for this batch in the project's canonical docs, so every later ticket uses names that already exist. This is the naming-authority ticket for the batch; it runs first so later tickets (consent scope, doctor Patients, profile photo, health background) reference settled terms and registered seams.

From the #529 Implementation Decisions and US-33/35, add to the CONTEXT.md glossary:

- **health background** - the patient-authored snapshot (blood group, conditions, allergies, medications, immunizations, family history) plus height/weight time series, owned separately from care-generated record entries; surfaced to a doctor only through a `health_background` consent check.
- **care loop** - the continuous patient-doctor relationship where a patient returns to the same doctor across visits; the doctor Patients list is the care-loop anchor (patient stays listed until standing-grant revocation).
- **doctor patients list** - the derived, consent-gated Current/Past patient list for a doctor.
- Extend the existing **record scope** glossary entry to include the new `health_background` value in the closed enum.

Also write three ADRs following the repo ADR conventions (they are the decisions the batch is built on):

1. `health_background` becomes its own consent scope, subsumed by `full_record`, grantable/revocable independently; auto-granted to a doctor the patient has a live relationship with on the first health-background save (first-save acknowledgment), revocable in Settings.
2. Doctor Patients list is derived, never stored: Current = live standing grant (any scope) or open care case; Past = closed care cases only, no live grant; no new patient-relationship table.
3. Private `profile-media` bucket (patient/ + doctor/ prefixes) for profile photos; never public, AES-256-GCM at rest, service-role writes, refs only in SQL.

Register any new facade seams and events this batch introduces in `internal-modules.md` sync matrix (4.1) and event registry (4.2), and mark the batch in `implementation-roadmap.md` (which modules/features it touches). Terms must match exactly - no invented synonyms.

AC:

- [ ] CONTEXT.md glossary gains the new terms and the extended record-scope enum, with `_Avoid_` lines
- [ ] Three ADR files committed describing the consent scope, derived Patients list, and private photo bucket decisions
- [ ] `internal-modules.md` registry rows and `implementation-roadmap.md` status reflect the batch seams
- [ ] `npm run lint` passes (markdown is gated by prettier/whitespace)

## Read-list (in order)

1. `CONTEXT.md` "Language (glossary)" - the `record scope` entry to extend and the partner/record glossary structure to mirror (existing entries carry a definition + `_Avoid_` line) (~1K).
2. `docs/agents/domain.md` - the glossary conventions (canonical terms, `_Avoid_` synonyms, ADR conflicts surfaced) (~0.3K).
3. `#529` parent spec "Implementation Decisions" + solution points 3-5 - the exact decisions these ADRs and glossary terms encode (~2K).
4. `docs/adr/0017-professional-prescription-record-cards.md` - the ADR file format/length precedent to copy (~0.4K).
5. `docs/adr/0004-consent-gate-cache.md`, `0011` , `0012` - the prior decisions the batch builds on (full_record subsumption, verified derivation, one-directory-entry-per-partner) (~0.8K).
6. `docs/architecture/internal-modules.md` §4.1 sync matrix + §4.2 event registry - the registration form for the new seams/events this batch introduces (~1.5K).
7. `docs/roadmap/implementation-roadmap.md` §2.8a (Phase 8.1) + §3.x traceability matrices - where the batch status is marked (~1K).

## Do NOT read

- Backend/frontend source code, `docs/archive/`, prototype assets, the other 21 batch tickets' bodies (the naming is settled here first).

## Baseline verify (must pass before the first edit)

- `npm run lint` - confirmed green 2026-09-24 (all 17 hooks).
- `npm run migration-check` - confirmed green 2026-09-24 (single head `ca8d2419f2b6`).

## Done-verify (acceptance criteria -> commands)

- `npm run lint` - prettier / whitespace / no-em-dash gate on the new markdown.
- Read-through of the new glossary entries, ADR files, and registry rows - they must match the batch vocabulary exactly.

## Handoff notes

- `docs/adr/` already contains a numbering collision: two `0004-*` files exist (`0004-consent-gate-cache.md` and `0004-otp-challenge-and-brute-force-contract.md`). The next new ADR numbers are `0018`+; do not reuse `0004`.
- The doctor-console seam is greenfield (`modules/doctor` does not exist today); the parent spec says "one new module seam: modules/doctor". Whether the facade/routes land in a new module or in care/intake affects what gets registered in §4.1/§4.2 - decide and register it here so #539/#540 conform.
- `health_background` appears in three code places that must stay consistent (see #531 brief) - the glossary enum must name all three.
- No em-dashes anywhere (lint-gated); use simple dashes.
