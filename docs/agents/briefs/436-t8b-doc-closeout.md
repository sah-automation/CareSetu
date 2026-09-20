# Brief - T8b PHASE-8 review-close: doc closeout - PRD, roadmap, internal-modules, ADRs, glossary

**Ticket:** #436 · **Parent:** #426 · **Refreshed:** 2026-09-15
**Reading surface:** ~9.0K tokens (budget 10K) - within budget

## Scope

Phase-8 review-close T8b. The planning and decision documents are corrected to state exactly what Phase 8 now delivers, so the plan and reality agree: real case birth on `pre_summary.ready`, close-without-prescription with the `case.closed` publisher, the forced-review record-and-surface flag, doctor-scoped `get_approved_prescription`, the two-facade structure, and the drafting cap described honestly as two AI drafts per care case (fewer than two rejected drafts) wherever current wording says "three attempts" - the code is unchanged.

Acceptance criteria (verbatim from ticket):

- [ ] internal-modules §3.6 inbound/outbound lists, §4.1 sync matrix, and §4.2 event registry match delivered wiring (case birth real, `case.closed` published, forced-review flag surfaced, doctor-scoped read) and the payload-enrichment note is updated
- [ ] roadmap §2.8 and §3.1 statuses state delivered reality; PRD FEAT-008/009 wording aligned (including the close path and telemetry claims)
- [ ] ADR-0014/0015 note the CFL-002 seam landing and the record-only forced-review posture; drafting-cap wording normalized to two AI drafts per case in every document
- [ ] CONTEXT glossary stays consistent with the delivered cap and close semantics
- [ ] Docs-only change - no code, migration, or test edits except where a wording correction lands in a test docstring (handled by T8a)

**Blocked by:** All of #427 (T1), #428 (T2), #429 (T3), #430 (T4), #431 (T5), #432 (T6a), #433 (T7), #434 (T6b) - the docs must describe delivered reality, so the code lands first.

## Read-list (in order)

1. `docs/architecture/internal-modules.md` §3.6 MOD-006 spec (~L340-377), §4.1 sync matrix (~L573-597), §4.2 event registry (~L599-659) - the three sections whose care rows must match the delivered wiring; note the payload-enrichment follow-on note at the end of §3.6. (~3.0K)
2. `docs/roadmap/implementation-roadmap.md` §2.8 Phase-8 (~L544-587) and §3.1 feature-matrix rows (~L859-888) - statuses + drafting-cap wording to correct. (~2.5K)
3. `docs/prd/project-prd.md` FEAT-008 and FEAT-009 sections (~L336-403) - acceptance scenarios, the CFL-002/003 resolution wording, and the drafting-cap phrase. (~2.0K)
4. `docs/adr/0014-issued-prescription-approval-contract.md` and `docs/adr/0015-ai-assisted-drafting-posture.md` (both short) - the CFL-002 seam landing note and the record-only forced-review posture; the drafting-cap decision wording. (~0.8K)
5. `CONTEXT.md` Phase-8 glossary entries - drafting cap, close-without-prescription, case stage, forced-review-flag terms (~L204-257). (~0.7K)

## Do NOT read

- `docs/archive/` (superseded), any other docs, any code/migration/test files (docs-only), the frontend.

## Baseline verify

None executable (docs-only). Before writing, skim the code-reality markers the earlier tickets produced (the `case.closed` publisher in the care facade, `forced_review` in `care_cases`, doctor parameter on `get_approved_prescription`, the two facade classes, `MAX_REJECTED_DRAFTS = 2` / `can_create_draft` in the prescription machine) so the doc edits state the delivered truth. Baseline of the tree is green (see sibling briefs): unit 2076 passed, migration-check single head, lint + typecheck clean.

## Done-verify (acceptance criteria → commands)

- Diff review against code reality - for each claimed delivery (case birth, `case.closed`, forced-review flag, doctor-scoped read, two-facade split, cap = two AI drafts) confirm a code symbol exists and the doc matches it.
- `npm run lint` still green (docs included in prettier/no-em-dash hooks) - confirm no em-dashes introduced anywhere per the repo-wide gate.

## Handoff notes

- Canonical cap truth (from the code, unchanged by this fix): `MAX_REJECTED_DRAFTS = 2` and `can_create_draft(rejected_count) = rejected_count < 2`, so at most **two AI drafts per care case**. Every document currently saying "drafting cap 3" / "3 attempts (2 rejections)" (PRD, roadmap §2.8, internal-modules §3.6, ADR-0015, CONTEXT glossary) is corrected to "two AI drafts per care case"; CONTEXT's `drafting cap` entry currently says "at most 3 draft attempts per case" and must change to match the code.
- The forced-review flag is **record-and-surface only** (no handshake gate) - this posture is already ADR-0015/ADR-0001 phrasing; add the explicit record-only landing note where the review-close commits it.
- The `get_approved_prescription` doctor-scope change and the two-facade structure alter §3.6 inbound API list and §4.1 row 583 (MOD-008 -> MOD-006) - the fulfillment caller is Phase 10 and doesn't exist yet, so the doctor-parameter signature must be reflected without inventing a caller.
- The payload-enrichment note in §3.6 must be updated because T2 makes the enrichment real (patient identity added to `pre_summary.ready` producer payload + tolerant consumer mirror).
- CONTEXT.md is a glossary plus navigation guide; only the Phase-8 entries change, nothing about the doc inventory or build-session protocol.
- The repo's lint includes a no-em-dash gate and prettier on docs - run `npm run lint` as the docs-only verification hook.
