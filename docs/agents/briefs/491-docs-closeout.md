# Brief - 491 Docs closeout

**Ticket:** #491 · **Parent:** #479 · **Refreshed:** 2026-09-19
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

Docs closeout for the PHASE-8.1-completion delivery, per the CONTEXT.md cross-reference rule, after all functional tickets (T1-T11) land: `internal-modules.md` §3/§5 (MOD-001 `patient_profiles` plus its traceability rows), `implementation-roadmap.md` §2.8a status/notes, `ui-blueprint.md` §5.3 (authed Find Care page), and the consent glossary note that pick-at-doctor grants consultations and prescriptions scopes together. Also records the D-E decision: the "No consented history available for this patient" empty state is correct behaviour (consent passes; the record is legitimately empty until `report.filed`/`prescription.issued`/`prescription.delivered`/`settlement.recorded` events fire) - documented so the next session does not chase it. No application code.

AC:

- [ ] `internal-modules.md` §3/§5 rows for MOD-001 `patient_profiles` (schema, facade functions, traceability) present and consistent
- [ ] `implementation-roadmap.md` §2.8a status/notes reflect the PHASE-8.1-completion delivery
- [ ] `ui-blueprint.md` §5.3 documents the authed Find Care page as delivered
- [ ] Consent glossary note states pick-at-doctor grants consultations + prescriptions scopes together
- [ ] D-E no-change is documented (empty consented history = correct behaviour) with its event-driven explanation

## Read-list (in order)

1. `docs/architecture/internal-modules.md` §3.1 MOD-001 spec (L146-186, storage list L154 + inbound APIs L160) + §5 traceability matrix (L683-721, PHASE-8.1 row L710) - where the `patient_profiles` schema, facade functions, and traceability rows land (~1.4K tokens)
2. `docs/roadmap/implementation-roadmap.md` §2.8a (L592-647, Status currently "Planned - issue #438" at L595, stale) + §3 matrices (L914-978) - status/notes + any scope-deviation subsection (~1.4K tokens)
3. `docs/design/ui-blueprint.md` §5.3 (`/patient/find`, L297-302, today unauthenticated public browse), §5.9 gating rules (L342-347, "never gated"), §10 G5 (L624) - the authed Find Care delta (~800 tokens)
4. CONTEXT.md glossary "Record & consent" (L102-122) + consultation section - where the "pick-at-doctor grants consultations + prescriptions scopes together" note goes (~500 tokens)
5. The D-E section of the parent PRD #479 + `docs/agents/briefs/483-doctor-cases-tab-index.md` Handoff note - the exact wording/explanation to record (~400 tokens)
6. Existing doc conventions in the same files - how rows/notes are phrased so the edits match (~600 tokens)

## Do NOT read

- `docs/archive/`; application code beyond confirming delivered shapes.

## Baseline verify (must pass before the first edit)

- `npm run lint` (prettier/markdown hooks)
- Known pre-existing (unrelated): backend `test_app_shell` demo/OTP + `test_contract_check` fail under the local `DEFAULT_APP_ENVIRONMENT="dev"` override in `apps/backend/app/config.py`; frontend homepage parity fails on one Daltonganj string.

## Done-verify (acceptance criteria → commands)

- `npm run lint`
- Manual diff review of the doc edits

## Handoff notes

- Pure docs; no schema or application changes.
- The D-E note is the "documented no-change" the issue asks for - write it so a fresh session does not re-litigate the empty state.
- `ui-blueprint.md` §5.9 currently asserts Find Care is never auth-gated and §5.10 asserts consent is never bundled - both must be reconciled with the delivered reality (#485/#480) or marked as superseded deltas.
