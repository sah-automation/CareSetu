# Surface overhaul: content depth and design quality

**Status:** Plan only. No group implemented.
**Created:** 2026-10-03
**Scope:** Doctor console (`/doctor/cases`, `/doctor/cases/[caseId]`, `/doctor/patients`, `/doctor/patients/[patientId]`), patient surfaces (`/patient`, `/patient/record`, `/patient/record/[entryId]`, `/patient/record/consent-log`), and the demo dataset that makes all of them verifiable.
**Character:** Maintenance-grade pass over delivered surfaces, in the shape of the #529 batch. Creates no new PRD feature identity; it deepens delivered ones.

## Decisions locked (2026-10-03, do not re-litigate)

1. **Backend extension is in scope.** New and extended read contracts are allowed, including schema migrations where a payload genuinely lacks a field. Each backend ticket must ship its doc delta in the same group.
2. **No divergence from `docs/design/ui-blueprint.md`.** The blueprint is the target, not a floor to exceed. Doctor console stays a task-focused full shell (blueprint section 6); patient app stays a mobile-first light shell with bottom tabs (blueprint section 5). "Professional and modern" means executing the blueprint's own rules properly - real information architecture, real hierarchy, real states - not importing a different product's visual idiom. Every visual decision must cite a blueprint rule.
3. **Seed data means a complete, realistic dataset.** Not fixture rows. Enough content, variety and history that a peer exploring the app sees every screen in a realistic state and every state transition is explorable. Real drug names and dosages, real-sounding complaints, real lab panels with reference ranges, a spread of case stages and consent statuses.
4. **Strictly sequential, one group per session.** Work G1, then G2, then G3, through G19, in the order given. Never start a group before the one before it has landed. Never batch two groups into one session.

## How to use this plan

This file is the whole context. In each new session, open it and say:

> Read `docs/plans/surface-overhaul-content-and-design-plan.md` and implement **G\<N\>**.

Then, within that session:

1. Read this file's group section for G\<N\> only. Do not read the other groups.
2. Read the source-of-truth map rows that group names, plus `CONTEXT.md` first, always.
3. Read the relevant standard from `docs/standards/` for the area being edited.
4. Read the prior-art briefs the group names.
5. Plan the group, write its context brief to `docs/agents/briefs/`, then implement it.
6. Run that group's done-verify. Do not proceed to the next group in the same session.

If a group turns out to need more than roughly 10K tokens of context you have not yet read, re-cut it before implementing rather than proceeding. If a group is blocked by something outside this plan, stop and report it rather than working around it.

A group is done when its done-verify passes and its doc delta has shipped. Nothing else counts as done.

## Source-of-truth map for a fresh session

| Concern                                               | Read                                                                                                                                                     |
| :---------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Navigation and build protocol                         | `CONTEXT.md` (first, always)                                                                                                                             |
| Design system, per-surface IA, cross-cutting patterns | `docs/design/ui-blueprint.md` sections 1, 5, 6, 9                                                                                                        |
| Module specs being changed                            | `docs/architecture/internal-modules.md` - MOD-001 identity, MOD-003 record/health, MOD-004 consent, MOD-005 intake, MOD-006 care, MOD-012 doctor console |
| Feature acceptance criteria                           | `docs/prd/project-prd.md` - FEAT-002 (record), FEAT-003 (consent), FEAT-004 (care), FEAT-005 (doctor console)                                            |
| Coding / API / security / observability rules         | `docs/standards/` - the relevant one before editing that area                                                                                            |
| Prior art for the surfaces in scope                   | `docs/agents/briefs/` - 511, 515, 517, 539, 540, 544, 545, 546, 564, 600, 614, DEPLOY-3                                                                  |
| Roadmap batch conventions                             | `docs/roadmap/implementation-roadmap.md` section 2.8a and the #529 batch rows                                                                            |

**Do not read** `docs/archive/`. The PRD supersedes it.

## Test-enforced gates that constrain every group

These fail the build if violated. Verify them before declaring any group done.

| Gate              | File                                                      | Rule                                                                                                                                                                         |
| :---------------- | :-------------------------------------------------------- | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Bilingual parity  | `apps/frontend/src/lib/i18n/dictionaries.test.ts:67`      | Every new dictionary key exists in both `en` and `hi`, same shape, same arity.                                                                                               |
| Design tokens     | `apps/frontend/src/app/design-tokens.test.ts:559,648,700` | No raw hex or framework-default palette entry in any class attribute. Arbitrary values only from the whitelisted set. Colour utilities must resolve to a token by full path. |
| Page weight       | `npm run check:pages`                                     | Per-route bundle budget. Heavier cards compete for this.                                                                                                                     |
| Alembic           | `npm run migration-check`                                 | Single head; no cross-schema FK.                                                                                                                                             |
| Module boundaries | `npm run check:boundaries`                                | A facade may compose other modules' facades; it may not reach into their schema or adapters.                                                                                 |
| Full baseline     | `npm run lint` and `npm run typecheck`                    | mypy `--strict` on the backend, `tsc --noEmit` on the frontend.                                                                                                              |

## Deliberate reversal to record

Brief **#515** (`docs/agents/briefs/515-professional-prescription-cards.md`) ratified the decision that "the medicine name leads as the title" for prescription cards, and brief **#517** ratified the unlabelled `name - dose - frequency - duration` join for the detail medicine block. Both shipped, and both are the direct cause of reported defects 5 (card title reads `Amlodipine`; medicine block reads `Amlodipine 9 3 3`).

**Group 10 reverses both.** That is a decision change, not a bug fix: it needs its own docs delta recording the supersession, and it must update the traceability that points at #515 and #517. Do not treat it as a silent correction.

## Ordering

Strictly sequential. One group per session, in the order below. The "Wave" labels are grouping headings only - they carry no meaning beyond readability.

```
G1   demo dataset                          (blocks everything visual)
G2   baseline audit

G3   consent counterparty label            (backend)
G4   doctor case-list enrichment          (backend)
G5   doctor patient-list enrichment       (backend)
G6   doctor patient-detail enrichment     (backend, incl. consented metrics)

G7   doctor-console view-model extraction
G8   shared UI primitives + display components

G9   consent counterparty display, 4 patient surfaces
G10  record entry titles + deliberate #515 reversal
G11  medicine presentation + Rx item vocabulary

G12  /doctor/cases list
G13  /doctor/patients list

G14  /doctor/patients/[patientId]
G15  /doctor/cases/[caseId] pre-summary body + history tab

G16  /patient + /patient/record record cards
G17  /patient/record/[entryId]
G18  /patient/record/consent-log

G19  docs and traceability closeout
```

Why this order, so a future session does not re-litigate it:

- **G2 before G1.** G2 is a read-only audit that captures the passing baseline. `AGENTS.md` requires the baseline run before the first edit, so it must be the opening session even though G1 is the bigger one.
- **G1 before every visual group.** Restyling an empty list is how briefs #545 and #546 landed as "looks designed" with no information on it. Working against real content is the whole point.
- **G3 to G6 before the frontend.** Each adds a read contract a later group consumes. G5 before G6 because both edit `apps/backend/modules/doctor/doctor_models.py` and `facade.py` (G5 owns `DoctorPatientRow` at line 17, G6 owns `DoctorPatientDetailView` at line 97), so serialising them avoids merge friction.
- **G7 before G9 to G11.** Those three write into the view-model module G7 creates, so they land in the right place instead of creating a fifth duplicate of the existing helpers.
- **G8 before G12 to G18**, and its content is decided by what G1 actually needs to display.
- **G12 to G18 are the eight surfaces.** Each is independently shippable and must not be batched.
- **G19 last.** It aggregates the doc deltas the earlier groups already shipped.

---

## G1 and G2 - foundations

### G1 - Full demo dataset

**Goal.** One command produces a database where every surface in scope shows realistic, varied content: partner doctors, patients with complete profiles, health backgrounds with metric series, standing grants, intakes with transcripts, pre-sumsaries including low-confidence ones, care cases across every live stage plus closed ones, prescriptions in every lifecycle state, record entries of all five types, and consent lineages covering every status.

**Current state.** `apps/backend/scripts/seed_demo.py` creates exactly two rows: a demo patient identity (`+919000000001`) and a bootstrap operator (`+919000000002`). It is wired into `deploy.yml` immediately after `alembic upgrade head`, and its own brief is `docs/agents/briefs/DEPLOY-3-demo-seed.md`.

**Why first.** Every other group in this plan is a content-density and hierarchy problem. Verifying them against two rows proves nothing.

**Work items.**

1. Split the seeder. Keep `seed_demo.py` as the deploy-path bootstrap (identity + operator only, unchanged behaviour, unchanged deploy wiring). Add a separate, explicitly dev/staging-gated dataset builder.
2. New entrypoint `python -m scripts.seed_demo_data`, plus a root `package.json` script (`npm run seed:demo`) so it is discoverable without knowing the Python path.
3. Hard gate: refuse to run when the resolved environment is production, and refuse when `DEMO_MODE` is off. Fail loudly with a non-zero exit, matching `seed_demo.py`'s existing convention. A production database must be unreachable from this code path.
4. Add a `reset` mode that removes only rows this builder owns (namespace-tagged demo identities), never a blanket truncate.
5. Populate, in dependency order:
   - `iam`: partner identities for at least three doctors (mixed specialties, verified, with credentials), one lab, one chemist; role grants and credential accounts through the real facade paths, not raw inserts.
   - `partner`: doctor profiles, directory entries, service areas, so the public directory and the pick-a-doctor step also look real.
   - `iam` patient profiles: complete records (name, age, gender, area, emergency contact), plus deliberately incomplete ones so the "profile incomplete" fallbacks are explorable.
   - `health`: `health_background_snapshots` with blood group and populated conditions, allergies, medications, immunizations, family history; `health_background_metrics` height/weight series of 3 to 6 points per patient so a trend is visible.
   - `consent`: standing grants per doctor, deliberately including one `full_record` grant, one revoked lineage, one still-pending request, and one `intake-ai` pseudo-counterparty grant so the Group 9 label fix has something real to render.
   - `intake`: intakes with realistic transcripts and media refs, and pre-sumsaries with a realistic confidence spread including at least one `low_confidence` row.
   - `care`: cases across `pre_summary`, `prescription_pending` and `closed`; prescriptions across draft, approved and issued; rx approvals with both decisions; at least one closed case per `close_reason` that is reachable in the UI.
   - `health` record entries: all five `entry_type` values with realistic payloads. Prescriptions use real drug names with real dose / frequency / duration strings (`Amlodipine`, `5 mg`, `once daily`, `10 days`) - never bare numbers. Lab reports carry `results` rows with `value`, `range` and `status` including at least one `below_range` and one `above_range` so the amber flag states are reachable. Consultations carry a complaint and a summary. Metrics and settlements carry plausible values.
   - `consent` egress log rows matching every disclosed read, so the record-detail egress trail is populated.
6. Idempotency: converge on re-run and under concurrency. Unique-index `ON CONFLICT`, never SELECT-then-INSERT, per the duplicate-resolution rule in `CONTEXT.md`.
7. Bilingual-realistic content. The app ships `en` and `hi`; demo clinical text should read naturally in both, since half the UI renders Hindi.

**Constraints the builder must respect** (verify against the live schema, do not trust this list blindly):

- `iam_identities.phone_e164` unique; E.164 normalisation is server-side.
- `iam_identities.status` CHECK; `iam_role_grants` role and status enums.
- `consent`: UNIQUE `(patient_id, counterparty_type, counterparty_id, record_scope)`; `lineage_ref` unique; `counterparty_type` in the closed vocabulary; `status` in the closed set; `version >= 0`.
- `health_record_entries.entry_type` in `consultation | prescription | lab_report | metric | settlement`.
- `care_cases.stage` CHECK is exactly `pre_summary | prescription_pending | closed` (`apps/backend/modules/care/schema/models.py:120`); `close_reason` CHECK.
- `care_prescriptions.status` and `.source` closed sets; `care_rx_approvals.decision` closed set.
- `health_background_metrics`: `height_cm` 30-250, `weight_kg` 1-500, at least one of the two present (`apps/backend/modules/health/schema/models.py:156-164`).

**Collision safety.** Must not collide with the fixtures in `tests/e2e/` or the integration suites. Namespace demo phones and counterparty ids distinctly.

**Done-verify.** `npm run seed:demo` twice on a migrated database, then: every page in scope renders non-empty; `npm run migration-check`, `npm run check:boundaries`, `npm run lint`, `npm run typecheck` green; the production refusal path proven by running with production settings and observing the non-zero exit.

**Doc delta.** None required. This is demo tooling, not a delivered surface. Note the new entrypoint in `docs/agents/issue-tracker.md` if that doc tracks operational commands.

### G2 - Baseline and constraint audit

**Goal.** Every later group opens its session knowing the exact gate it must satisfy and exactly which existing tests it will break.

**Work items.**

1. Record the current baseline: run `npm run test:unit:backend`, `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck`, `npm run migration-check`, `npm run check:boundaries` and capture the pass/fail state, so any later failure is attributable.
2. Enumerate the tests that assert current (defective) behaviour and will need updating:
   - `apps/frontend/src/lib/record/timelineView.test.ts:154,202,237,255` - four assertions that `card.title === "Amlodipine"`.
   - `apps/frontend/src/app/(doctor)/doctor/cases/page.test.tsx:195` - asserts the `Case #N` label.
   - `apps/frontend/src/app/(doctor)/doctor/patients/page.test.tsx` and `.../patients/[patientId]/page.test.tsx:264`.
   - `tests/e2e/doctor-workspace.spec.ts`, `tests/e2e/patient-journey.spec.ts`, `tests/e2e/auth-loop.spec.ts`.
3. Confirm and document the current page-weight headroom per affected route from `npm run check:pages`, since G8 spends it.
4. Note the token vocabulary available for new UI, read from `apps/frontend/src/app/tokens.css` - in particular which of `shadow-card`, `shadow-pop`, `radius-lg` and the `accent` / `warm` / `success` / `warn` / `danger` slots are currently underused and therefore free to adopt.

**Done-verify.** A written baseline note in the group's commit or issue. No code change.

---

## G3 to G6 - backend read contracts

All four are facade-level composition in `apps/backend/modules/`, each gated to an active doctor, each access-logged, and each egress-disclosed against the authorising grant exactly as the existing consented reads are. Reuse the degrade-safe enrichment precedent at `apps/backend/modules/doctor/facade.py:283-305` rather than inventing a new failure mode: a cosmetic enrichment failure must never take a list down.

### G3 - Consent counterparty display label

**Blocks:** G9, G18.

**Problem.** `apps/backend/modules/consent/facade.py:109-127` - `ConsentView` carries only `counterparty_type` and `counterparty_id`. There is nothing in the response from which a human name can be produced, so the UI shows `10` and `intake-ai`.

**Work items.**

1. Add a resolved display label to `ConsentView` (and `EgressLogEntry`, which has the same defect at `facade.py:150-159`, plus the reverse view `CounterpartyGrantView` if its consumers need it).
2. Resolution rules: a doctor / lab / chemist counterparty resolves to the partner's practice display name, degrade-safe to `None` when the partner row is missing so the frontend can fall back rather than crash. The `intake-ai` pseudo-counterparty (`apps/backend/modules/intake/adapters/__init__.py:66`) resolves to a stable machine-readable marker, not a name - the UI owns the human wording for it in both locales.
3. A new counterparty type appearing later must degrade to the type name, never to a raw id.
4. Never widen consent's own module reach. If the partner name lives in `partner`, resolve it through the partner facade's seam, or resolve it in `MOD-012` and project it in. Decide in the ticket and record the choice in the module-boundary checker if it introduces a new permitted edge.
5. Frontend client type and shape guard updated to match.

**Doc delta.** `internal-modules.md` MOD-004 view contract; `MOD-012` if resolved there. New event name only if a disclosure-worthy read is introduced - do not invent one, register it in section 4.2 if used.

**Done-verify.** Backend unit tests for each counterparty type including the pseudo-counterparty and a missing partner row; `npm run test:unit:backend`, `npm run check:boundaries`, `npm run lint`, `npm run typecheck` green.

### G4 - Doctor console case-list enrichment

**Blocks:** G12.

**Problem.** `GET /v1/care/cases` (`apps/backend/modules/care/adapters/routes.py:236-242`) returns bare `CaseDetailView` (`apps/frontend/src/lib/care/api.ts:66-79`). No patient identity, no clinical context, no timing. A case card can never show a name because nothing carries one.

**Work items.**

1. New doctor-console read (or an additive enrichment on the existing one) returning per case: patient display name, age, photo presence; the case stage; the pre-summary's chief complaint snippet, chief-complaint count, structuring confidence and `low_confidence` flag; and the timestamps needed for a waiting-since and last-activity figure.
2. Compose `care` for the cases and `iam` for the profiles, degrade-safe on the profile resolution exactly as `facade.py:283-305` does. The intake-derived snippet must degrade to absent, never to a fabricated one.
3. Sort order must satisfy the blueprint's queue-first rule: needs-review cases first, oldest first, and `low_confidence` cases floated above clean ones.
4. Bounded page with `total`, per `api-standards` section 4. The current read is unbounded.
5. Access-log each served row and egress-disclose against the authorising live grant, matching the Patients list discipline at `apps/backend/modules/doctor/facade.py:248-260`. A row with no live grant must fail closed and leave the egress log untouched.

**Doc delta.** `internal-modules.md` MOD-012 read list; roadmap traceability section 3.1 rows for the new surface if it is a new endpoint.

**Done-verify.** Facade tests covering degradation (profile resolution failure, missing pre-summary, no live grant), ordering, and paging bounds; `npm run test:unit:backend`, `npm run check:boundaries`, `npm run lint`, `npm run typecheck` green.

### G5 - Doctor patient-list enrichment

**Blocks:** G13.

**Problem.** `DoctorPatientRow` (`apps/frontend/src/lib/doctor/api.ts:71-82`) carries name, age, photo presence, bucket, scopes and latest stage. No clinical signals, no activity, and the page throws away `total` so it cannot page.

**Work items.**

1. Add the signals a patient card legitimately needs to be actionable: most recent consultation date, active case count, a consent-locked allergy flag (presence only, never the allergy text, unless the scope grants it), and a profile-completeness indicator so incomplete patients are distinguishable.
2. Make the existing server-side `search` usable and widen it beyond name substring (area, phone last digits). The route already accepts it (`apps/backend/modules/doctor/adapters/routes.py:327`); the page simply does not send it (`apps/frontend/src/app/(doctor)/doctor/patients/page.tsx:398-406`).
3. Add a sort parameter. Today the backend sorts by name only (`facade.py:243`).
4. Preserve the Current / Past bucket derivation (ADR-0019) unchanged.
5. Keep every read access-logged and egress-disclosed, page-size bounded per `api-standards` section 4.

**Constraint.** Any added field must respect the scope rules already encoded at `apps/backend/modules/doctor/facade.py:60,105`: a `lab_results` or `health_background` grant is not a licence to read identity contact. Allergy presence under a `health_background` grant only.

**Done-verify.** Facade tests for scope-gating each new field, for search and sort, and for paging bounds; `npm run test:unit:backend`, `npm run check:boundaries`, `npm run lint`, `npm run typecheck` green.

### G6 - Doctor patient-detail enrichment

**Blocks:** G14.

**Problem.** `DoctorPatientDetailView` (`apps/frontend/src/lib/doctor/api.ts:144-154`) gives contact, consultation history, health background and one case-workspace link. Three concrete gaps: no height/weight series at all, no consent-state detail, and no list of the doctor's own cases for that patient.

**Work items.**

1. **Consented height/weight read.** The data exists (`health_background_metrics`) and an owner-only read exists (`apps/backend/modules/health/facade.py:842` `list_health_background_metrics`), but there is no consented counterpart, so a doctor cannot read a patient's trend. Add one through the same `_consent_gated_read` spine as `read_consented_health_background` (`facade.py:1017-1040`), gated on the `health_background` scope which `full_record` subsumes, fail-closed, with both ledgers written on success. Surface it on the doctor detail block.
2. **Consent-state detail.** Granted-at, version, lineage reference and which scopes are live, so the doctor can see what access they actually hold rather than inferring it from pills.
3. **Case list for this patient**, not a single link: the doctor's own cases with this patient, each with stage and timestamp.
4. Keep the section-gating discipline intact: contact under `consultations` or `full_record`, consultation history under `consultations`, health background and its metrics under `health_background`, case workspace never consent-gated. A patient with no live grant answers every section locked and leaks nothing.

**Done-verify.** Facade tests per scope including `full_record` subsumption, the denied path answering `None` rather than raising, and both-ledger writes; `npm run test:unit:backend`, `npm run check:boundaries`, `npm run lint`, `npm run typecheck` green.

**Doc delta.** `internal-modules.md` MOD-003 (new consented read) and MOD-012 (extended detail view).

---

## G7 and G8 - shared frontend substrate

### G7 - Doctor-console view-model extraction

**Blocks:** G9 through G18.

**Problem.** `stageLabel`, `scopeBadges`, `stageChipClass` and the date formatters are copy-pasted across five files with four different fallback strings, and the list and detail pages format age and name differently from each other (`patients/page.tsx:97,102` versus `patients/[patientId]/page.tsx:170,177`, plus a third fallback at `:457`).

**Work items.**

1. Create a doctor-console view-model module mirroring what `apps/frontend/src/lib/record/timelineView.ts` already does for the patient side: pure functions from a wire type to a display shape, no JSX, fully unit-testable, locale-parameterised.
2. Move every duplicated helper into it: stage labels, stage chip tone (including a distinct `closed` tone, which does not exist today), scope pills, patient name and age formatting with one agreed fallback chain, waiting-since, relative time, and date formatting.
3. Define one fallback chain for a patient with no recorded name. It must degrade to a monogram, not to a generic word that makes two different patients indistinguishable.
4. Rewrite the five call sites to consume it. No behaviour change beyond unification and the new `closed` tone.
5. Frontend shape guards for any new response types from G4, G5, G6.

**Done-verify.** New unit tests for every view-model function in both locales; all five page suites green with no assertion changes other than where a fallback string unifies; `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` green.

### G8 - Shared UI primitives and display components

**Blocks:** G12 through G18.

**Problem.** `apps/frontend/src/components/ui/` holds eleven primitives: avatar, badge, button, card, dropdown-menu, input, sheet, skeleton, switch, textarea, toggle-group. There is no Table, Tabs, Tooltip, Accordion, Separator, Dialog, Popover, Select or Progress. Every group from G12 onward would otherwise hand-roll these a fifth time.

**Work items.**

1. Decide the needs list from G1's actual content, not from speculation. Candidate components, in likely order of use: Tabs (G15), Table or list-row variants (G12, G13), Separator, Tooltip, Accordion, Progress (confidence and completeness figures), Dialog or Popover (confirm and filter surfaces).
2. Add shadcn primitives where they exist upstream, following the approach already taken in brief #600. Weigh each against the page-weight budget recorded in G2 and against `docs/research/ui-component-library.md`. If a component cannot fit the budget, build a local token-only equivalent rather than shipping a heavy dependency.
3. Build the shared display components these surfaces all need: a meta list, a stat chip, a timeline row, a section card with heading and action, a filter bar, an enhanced empty state. Blueprint section 9 already specifies the empty-state anatomy (what this is, why empty, exactly one next action, neutral `accent.soft` styling, never error-like) - implement it once, properly, rather than five times.
4. Every new class must be token-only and must satisfy `design-tokens.test.ts`.
5. Every new string must exist in both locales.

**Done-verify.** Component tests for each primitive; `npm run check:pages` no worse than the G2 baseline; `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` green.

**Doc delta.** `docs/design/ui-blueprint.md` section 1.1 component-library note, and `docs/research/ui-component-library.md` migration record.

---

## G9 to G11 - correctness fixes

These three are the highest-visibility defects and the smallest changes. They land here, not earlier, because G7 gives them a correct module to live in and G1 gives them realistic data to be verified against.

### G9 - Consent counterparty display across the patient app

**Depends on:** G3 (backend), G7 (view-model).
**Blocks:** G18.

**Problem.** `apps/frontend/src/lib/consent/consentView.ts:14` returns `counterpartyId || counterpartyType`. That string is the card heading at `apps/frontend/src/app/(patient)/patient/record/consent-log/page.tsx:402-406,438`, so the UI reads `10` and `intake-ai`.

**Work items.**

1. Replace the raw-id return with the resolved label from G3. Where G3 returns absent, fall back to a type-word plus a localised secondary line, never to a bare id.
2. Give the `intake-ai` pseudo-counterparty its own human label in both locales, distinct from any partner.
3. Fix all four call sites, not just the consent log: `consent-log/page.tsx:320,402`, `apps/frontend/src/components/patient/profile/ConsentGrantsPanel.tsx:118,170`, `apps/frontend/src/components/patient/home/ActionRequiredCard.tsx:131`.
4. Fix the avatar initials, which are currently derived from the raw id (`consent-log/page.tsx:406`) and therefore produce meaningless monograms. Initials come from the resolved name; a pseudo-counterparty gets a fixed glyph, not initials.
5. Add the missing context the card never showed: what the counterparty can see (scope), since when, partner type or specialty as a secondary line, and relative time.

**Done-verify.** Unit tests per counterparty type including the pseudo-counterparty and the degraded case, in both locales; assertions that no raw id ever reaches the DOM; `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` green.

### G10 - Record entry titles

**Depends on:** G7. **Reverses** brief #515 - see "Deliberate reversal to record" above.

**Problem.** `apps/frontend/src/lib/record/timelineView.ts:458` sets `title: first.name` in the prescription branch of `describeEntry`. That single line drives four surfaces: the `/patient` dashboard (`apps/frontend/src/components/patient/home/RecentActivityCard.tsx:146`), the `/patient/record` list (`.../patient/record/page.tsx:629`), the `/patient/record/[entryId]` heading (`.../patient/record/[entryId]/page.tsx:175`), and `HealthSnapshotCard.tsx:34`. The whole record reads as a list of drug names.

**Work items.**

1. Prescription title becomes a record-level identity, not a drug name. The doctor who issued it and the issue date belong on the card; the medicines belong in the body. Decide the exact shape against G1's data and record it in the brief.
2. Fix the fallback chain at `timelineView.ts:462-469`. It currently falls back to an internal prescription id, then to a bare type label. Neither is a real title.
3. Lab report title is a raw filename (`timelineView.ts:478`, `payloadString(entry, "filename")`), so a heading reads `cbc-panel.pdf`. Use the order or panel identity; fall back honestly when the payload carries only a filename.
4. Consultation and metric entries have no title beyond the type label (`timelineView.ts:421,487`). Give them a real one from the payload.
5. Update the four assertions at `timelineView.test.ts:154,202,237,255`.
6. Add the docs delta that supersedes #515's ratified decision, and update every traceability row pointing at #515.

**Done-verify.** View-model unit tests per entry type, enriched and legacy payloads, both locales; the four surfaces render the new titles; `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` green.

### G11 - Medicine presentation and Rx item vocabulary

**Depends on:** G1 (realistic data), G7. **Reverses** brief #517.

**Problem, part one - presentation.** `joinMedicineLine` (`timelineView.ts:245-248`) filters nulls and joins with `" - "`. Called as `joinMedicineLine([name, dose, frequency, duration])` at `.../patient/record/[entryId]/page.tsx:352-357`, it produces `Amlodipine - 9 - 3 - 3`. Nothing tells a patient that 9 is a dose, 3 a frequency and 3 a duration. The block is a bare `<ul>` of strings (`:340-378`).

**Problem, part two - vocabulary.** `dose`, `duration` and `frequency` are unvalidated `String(100)` columns (`apps/backend/modules/care/schema/models.py:181-183`) and all three are optional in `RxItemInput` (`apps/backend/modules/care/care_models.py:103-105`) with no format guidance. That is why `9 3 3` is storable at all.

**Work items.**

1. **Labels, not a join.** Render dose, frequency and duration as individually labelled values. A medicine line that cannot be labelled is a data problem, not a display problem, and must be flagged as such in the UI rather than silently joined.
2. **Restructure the medicine block** into a per-medicine presentation with clearly separated fields, replacing the flat string list. Blueprint section 5 governs this surface, mobile-first.
3. **Add an instruction field** ("after food", "at bedtime"). It does not exist in the Rx item schema at all. This needs a migration, a backend contract change, a doctor-editor input with hint text, and the issued-snapshot payload. Confirm the label against real Indian prescribing convention.
4. **Validate and normalise the existing three fields.** Client-side hint text on the doctor Rx editor plus a server-side format check, and a normalisation pass on display. Decide whether a closed vocabulary (issue #602 established the closed-vocabulary precedent) is right for frequency, and record the decision.
5. **Surface prescription-level metadata on the detail page**: prescribing doctor, issue date, Rx reference, status, and the chemist when the payload carries one. The payload already carries `attributed_doctor_name` and `chemist_name` (`apps/backend/modules/health/adapters/__init__.py:114-115`) but the detail page gives them no prominence.
6. **Allergy cross-check.** The patient's health background allergies are readable and the medicine list is on the same page; nothing compares them. Surface a plain-language warning on overlap. Confirm the consent basis before doing this and record it - if the doctor-side read is gated, the patient-side read is the patient's own record and needs no gate, but the security standard must be checked, not assumed.
7. Update the docs that supersede #517.

**Done-verify.** Migration is single-head and passes `npm run migration-check`; backend validation tests; view-model and page tests covering labelled values, a missing-field medicine, a multi-item prescription, and the new instruction field, both locales; `npm run test:unit:backend`, `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` green.

---

## G12 and G13 - doctor console lists

### G12 - `/doctor/cases`

**Depends on:** G1, G4, G6, G7, G8.

**Current state.** `apps/frontend/src/app/(doctor)/doctor/cases/page.tsx:151-187`. Each card is a flat `<li>` with a bottom hairline, rendering exactly two of the eleven available fields. Brief #545 restyled this list "to the patient-shell visual language" and the result still carries no information, which is the evidence that a restyle without content is the wrong fix.

**Work items.**

1. Patient name leads the card; the case reference becomes a quiet secondary identifier rather than the title. Remove the `Case #N` string as the primary label. `t.caseItemMeta` (`apps/frontend/src/lib/i18n/dictionaries.ts:1459` en, `:3328` hi) survives only as that secondary line.
2. Render the full clinical and temporal payload G4 delivers: complaint snippet, complaint count, confidence with the `low_confidence` Verify chip floated above clean cases per blueprint section 6, waiting-since, last activity.
3. Add the missing stage tone for `closed`, so a closed case is visually distinct from a pending-Rx case.
4. Use `Card` and `shadow-card`, and give the list real hover, focus and selected states. Adopt the `radius-lg` and elevation tokens that G2 confirmed are free.
5. Build the filters the page has never had: stage, Verify chip, doctor-input state, and a search box. All from the G4 read, no client-side guessing.
6. Honour `total` and page properly.
7. **Fix the same defect on the doctor landing page.** `apps/frontend/src/app/(doctor)/doctor/page.tsx:431-460` renders an `OpenCasesCard` with the identical `caseItemMeta` title. Extract one shared case-card component and drive both surfaces from it, so they cannot diverge again.
8. Retune the loading skeleton to match the new card anatomy, per blueprint section 9. A skeleton that does not match the final layout is worse than none.

**Done-verify.** Page and component tests for every card state (loading, empty, error, filtered-empty, populated, closed); assertions that a case with a patient name never renders `Case #N` as its title; desktop and mobile verified; both locales; `npm run check:pages` within the G2 baseline; `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` green.

### G13 - `/doctor/patients`

**Depends on:** G1, G5, G7, G8.

**Current state.** `apps/frontend/src/app/(doctor)/doctor/patients/page.tsx:124-190`. `PatientRow` renders name, age, scope pills and a stage chip. `has_photo` is on the type and computed by the backend (`apps/backend/modules/doctor/facade.py:231`) and never read. Search is client-side name-substring only against a hard `perPage: 100` fetch, so `total` is discarded and the list silently truncates past 100.

**Work items.**

1. Avatar or monogram on every card, driven by `has_photo` with a monogram fallback from the view-model.
2. Replace the generic-word name fallback so two incomplete patients are distinguishable.
3. Render the G5 signals: last consultation, active case count, consent-locked allergy presence, profile completeness.
4. Switch to the server-side search and the sort parameter. Widen matching beyond name.
5. Honour `total`, show a result count, and page.
6. Search field gets debounce, a clear button, match indication, and a distinct filtered-empty state.
7. Card visual depth: `Card`, `shadow-card`, hover and focus states, and a density hierarchy so the actionable patient reads first.
8. Unify fallbacks with the detail page via G7, closing the three-way disagreement at `patients/page.tsx:97,102`, `patients/[patientId]/page.tsx:170,177,457`.

**Done-verify.** Page tests per bucket, per card state, search and sort and paging; both locales; `npm run check:pages` within baseline; `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` green.

---

## G14 and G15 - doctor console details

### G14 - `/doctor/patients/[patientId]`

**Depends on:** G1, G5, G6, G7, G8.

**Current state.** `apps/frontend/src/app/(doctor)/doctor/patients/[patientId]/page.tsx:492-510`. Four stacked sections, no navigation. The `PageHeader` title is the generic `t.contactHeading` while the real name sits inside the first section, below the fold. Health background joins arrays with commas (`:281-290`) so an allergy gets the same visual weight as an immunisation. Consultation history rows show only type and date. The case workspace is one link. Every locked section renders identically with no indication of which scope is missing.

**Work items.**

1. **Identity band at the top**: avatar, name, age, gender, area, and the consent state G6 delivers. The patient is identifiable without scrolling.
2. **Navigation**: tabs or an anchor index per blueprint section 6, so the four sections are reachable on a long page.
3. **Health background with real hierarchy.** Allergies render as individual emphasised entries, not a comma list. Conditions as tags. Blood group as a prominent single value. Each of the five areas gets a consistent, scannable treatment.
4. **Height/weight series** from G6, as a trend rather than a number. Handle the not-granted case as a locked state that names the missing scope.
5. **Consultation history** rows gain the clinical content the payload already carries, using the same timeline row component as G15 so the two doctor surfaces agree.
6. **Case list** for this patient, from G6, each row deep-linking into the case workspace.
7. **Locked states differentiated**: name the missing scope, and give the doctor something to do about it.
8. Retune loading, empty and error states to blueprint section 9, matching the new anatomy.

**Done-verify.** Page tests per section in all four gating states (granted, `full_record`, denied, absent); both locales; `npm run check:pages` within baseline; `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` green.

### G15 - `/doctor/cases/[caseId]` pre-summary body and history tab

**Depends on:** G1, G4, G6, G7, G8.

**Current state.** `apps/frontend/src/app/(doctor)/doctor/cases/[caseId]/page.tsx`. Brief #546 restyled this workspace "to the patient-shell visual language"; it still reads as a flat label grid.

**Pre-summary body, `:1061-1350`.**

1. Replace the flat `grid-cols-[140px_1fr]` label grid (`:1149-1322`) with real clinical sectioning: history of present illness, review of systems, clinical impression, each with a heading and a scannable body. A doctor reads this under time pressure; a two-column label dump is the wrong shape.
2. Add a provenance banner making the AI draft's status unmissable, per the glossary: a pre-summary is always a draft for a licensed doctor, never presented as verified. The `low_confidence` / forced-review state must be visually dominant, not a small chip.
3. Fix the leaked dictionary key at `:1168-1171`, where `t.durationNotSet` renders as user-visible copy.
4. Confidence becomes a scale against the 0.70 threshold rather than a bare percentage (`:169-172`).
5. `patient_edits` and `doctor_corrections` stop being `k: v` string joins (`:1245-1267`) and become a labelled change list with snake_case keys mapped to real field names.
6. Transcript becomes a contained reading pane with speaker turns and timestamps, and the bare `<audio controls>` (`:1113-1128`) gets a proper player affordance.
7. Tab state moves into the URL so refresh, back and deep links preserve it (`WorkspaceTabs`, `:359-423`).

**History tab, `:1353-1380` and `apps/frontend/src/components/case/ConsentedHistory.tsx`.**

8. Render the clinical content each entry's payload carries. Today only `entry_type` and `occurred_at` are shown (`ConsentedHistory.tsx:142-162`), so a doctor's history tab is a list of labels and dates.
9. **Fix the hardcoded `HISTORY_SCOPE = "consultations"`** (`ConsentedHistory.tsx:24`). Prescriptions, lab reports, metrics and settlements can never appear, and a `full_record` grant is not honoured as a superset. Resolve the granted scopes first, then request the widest the patient actually granted.
10. **Add the patient's health background**, under a live `health_background` grant, so the case workspace agrees with the patient detail page. Reuse the G14 treatment rather than inventing a third one.
11. Timeline treatment: month grouping, a visual rail, and entry-type filters.
12. Paging per `api-standards` section 4, rather than rendering an unbounded list.

**Done-verify.** Workspace tests for each pre-summary state (draft, reviewed, final, `low_confidence`, patient-edited, doctor-corrected, absent); history tests per scope combination including `full_record` and a denied background; assertions that a history row is never label-plus-date-only; both locales; `npm run check:pages` within baseline; `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` green.

**Doc delta.** `internal-modules.md` MOD-012 case-workspace read; MOD-003 if the history read's scope resolution changes.

---

## G16 to G18 - patient surfaces

These consume G9, G10 and G11. They are the visual half of the reported defects; the correctness half already landed.

### G16 - `/patient` and `/patient/record` record cards

**Depends on:** G1, G8, G10.

1. Redesign the record card around the new title model from G10: the record leads, the detail follows. The current card is a tinted circle, a drug name, and a joined string.
2. Per-entry-type anatomy for all five types, matching blueprint section 5 (mobile-first, big targets, minimal typing) rather than one generic shape.
3. On `/patient`, `RecentActivityCard` and `HealthSnapshotCard` both consume `describeEntry` and must reflect the new model without drifting from `/patient/record`.
4. Prescription cards show medicine count and issuing doctor prominently, and never lead with a drug name.
5. Lab result flags get consistent, accessible presentation on both the card and the list.
6. Verify the `/patient/record` snapshot strip and filter bar still read correctly against the new card anatomy, per blueprint section 5 and the PROTO-3.1 design in brief #511.

**Done-verify.** Page and component tests per entry type, both locales; `npm run check:pages` within baseline; `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` green.

### G17 - `/patient/record/[entryId]`

**Depends on:** G1, G8, G11.

1. The heading is now correct via G10; give it the page treatment it deserves rather than a bare `PageHeader` string.
2. Medicine block per G11: labelled dose, frequency, duration and the new instruction field, per medicine, in the layout G11 defines.
3. Prescription-level header: prescribing doctor, issue date, Rx reference, status, chemist when present.
4. Allergy cross-check surface per G11.
5. Give the source and consent-reference card, the lab results table and the egress trail the same visual language, and re-check the lab table's block-level scroll against the new card system.
6. The action bar still carries a disabled "Download PDF". Either implement it or confirm it stays a `SoonBadge`; do not leave a permanently dead control looking like an action.

**Done-verify.** Page tests per entry type, both locales; assertions that no medicine renders as an unlabelled number sequence; `npm run check:pages` within baseline; `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` green.

### G18 - `/patient/record/consent-log`

**Depends on:** G1, G3, G7, G8, G9.

1. Cards are correct by G9; this group is the presentation.
2. Group by counterparty so a patient sees "Dr X can see these" as one thing rather than N unrelated cards.
3. Scope iconography and a plain-language "what they can see" summary. The scope enum is closed (`consultations | prescriptions | lab_results | metrics | health_background | full_record`) and must read as meaning, not as a token.
4. Status filter, and status explained rather than merely badged.
5. Granted-since and relative time, from the consent-state data.
6. The expandable receipt timeline (`consent-log/page.tsx:459-472`) gets the timeline treatment shared with G14 and G15.

**Done-verify.** Page tests per status, per grouping, filtered and unfiltered, both locales; assertions that no raw counterparty id reaches the DOM; `npm run check:pages` within baseline; `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` green.

---

## G19 - closeout

### G19 - Docs and traceability closeout

**Depends on:** every prior group.

1. `docs/design/ui-blueprint.md` sections 5 and 6: reconcile the delivered information architecture of these eight surfaces against what the blueprint specifies. Any divergence found in G12 through G18 must be resolved in the blueprint or in the code, explicitly - not left ambiguous.
2. `docs/architecture/internal-modules.md`: MOD-003 (consented metrics read), MOD-004 (counterparty label), MOD-006 (Rx instruction field), MOD-012 (the four enriched reads). Update section 4.1 sync matrix, section 4.2 event registry if any new event was introduced, and section 5 traceability.
3. `docs/roadmap/implementation-roadmap.md`: a maintenance batch in the #529 shape, with section 3.1, 3.2 and 3.3 rows.
4. **The two deliberate reversals** (#515 medicine-name title, #517 unlabelled medicine join) recorded as supersessions with rationale, in the PRD feature sections they touch and in the glossary if vocabulary changed.
5. `docs/agents/issue-tracker.md` and the demo-data entrypoint from G1.
6. Verify no group left an undocumented divergence. The point of this group is that the docs describe the code that shipped.

**Done-verify.** Every doc file named above was edited in this group, not deferred. A diff review shows each of G3 to G6 and G11 has its documented contract change present. `npm run lint`, `npm run typecheck`, `npm run migration-check`, `npm run check:boundaries` green. No group from G1 to G18 has an open question in the issue tracker about what it was supposed to deliver.

---

## Explicitly out of scope

- New features, new surfaces, new navigation destinations.
- Any change to the blueprint's shells, navigation model, palette, typography or token set. Improvements execute the blueprint; they do not rewrite it.
- The partner and operator consoles, the public directory and the public provider profile. Out of the reported scope; file separately if wanted.
- Intake capture, the AI pipeline, the doctor review queue's data contract. Only the case-workspace _display_ of pre-summary data is in scope (G15).
- Real clinical validation of prescriptions or drug-interaction checking. G11's allergy cross-check is a literal string overlap against the patient's own recorded allergies, not a drug database, and must be labelled as such in the UI.

## Risks

| Risk                                                                                                                   | Mitigation                                                                                                                                                                               |
| :--------------------------------------------------------------------------------------------------------------------- | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A restyle lands on empty data again and repeats the #545 / #546 outcome.                                               | G1 is a hard barrier. No visual group starts before it.                                                                                                                                  |
| Group size. The largest single item is G15 (twelve work items across two surfaces).                                    | The standing size gate applies: if a group cannot be planned inside roughly 10K tokens of unread context, re-cut it before implementing rather than proceeding.                          |
| Consent scope creep in G5 and G6. New fields on a doctor-facing patient read are the highest-risk change in this plan. | Every added field names its authorising scope in the ticket and has a test proving it is absent without that grant. `apps/backend/modules/doctor/facade.py:60,105` is the existing rule. |
| i18n volume. This plan adds a large number of strings to a dictionary file already around 245KB.                       | Every group adds both locales in the same commit and runs `npm run test:unit:frontend` before finishing. Never stage a half-translated change.                                           |
| Page-weight budget. G8 spends it and G12 to G18 keep spending it.                                                      | G2 records headroom. G8 measures before adopting anything. Every group re-runs `npm run check:pages`.                                                                                    |
| Two reversals of ratified decisions.                                                                                   | Both are documented as supersessions in G10, G11 and G19, not applied silently.                                                                                                          |
