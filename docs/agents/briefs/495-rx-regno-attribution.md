# Brief - 495 PHASE-8.1 T10c: issuing doctor name attribution on issued rx e-prescription

**Ticket:** #495 · **Parent:** #486 · **Refreshed:** 2026-09-19
**Reading surface:** ~2.5K tokens (budget 10K) - within budget

## Scope

An issued e-prescription shows the issuing doctor's display name instead of the static "Attributed to you". The name (`practice_name`) comes from the partner profile read for the `attributed_doctor` already on the prescribed record - no new schema.

**Scope change:** the registration number (reg-no) is deliberately out of scope. No scalar reg-no exists in the codebase today (the `medical_registration` credential is stored as an encrypted document artifact, never a number string), so the attribution surfaces the doctor's display name only.

AC:

- [ ] The issued-read projection exposes the issuing doctor's display name (from the `attributed_doctor` partner read; no new schema)
- [ ] The issued e-prescription block renders the doctor's name in place of the static attribution string, with bilingual parity
- [ ] An attribution with an unresolvable name degrades gracefully (existing "Attributed to you" copy, no error)
- [ ] Tests: backend attribution payload on the issued read, frontend issued name render + fallback + parity

## Read-list (in order)

1. `modules/care/rx_facade.py` `get_approved_prescription` (framed around L704-781, the issued-read projection assembly) + `modules/care/care_models.py` `PrescriptionDetailView` (`attributed_doctor: int | None`) - the projection that must carry the issuer name (~700 tokens)
2. `modules/care/adapters/routes.py` (L76-93 already uses `PartnerFacade.resolve_partner` off `request.app.state.partner_facade`; the issued GET at L429-444) - the reuse seam; mirror the pattern, do NOT call partner internals from the facade body (~250 tokens)
3. The partner read that surfaces `practice_name`: note `resolve_partner` returns only `partner_id`/`partner_type`/`status`/`round` (registration_models.py `PartnerView`), so the name read is the directory provider-profile / operator-gate share surface (`practice_name` at directory_models.py L26/83 or the operator-gate share views) - the no-new-schema name source; wire it as a seam consistent with module isolation (~450 tokens)
4. The case-page issued e-prescription block (page.tsx L1321-1370; static `issuedAttributedTo` at L1366) - the render point; show the issuer name above/beside the existing copy (~250 tokens)
5. `lib/care/api.ts` view model + `lib/i18n/dictionaries.ts` `issuedAttributedTo` (EN L1163, Hi L2277) + parity - the copy to enrich and its fallback (~300 tokens)
6. Test patterns: `tests/unit/test_care_routes.py` + the case-page `page.test.tsx` + `api.test.ts` type-guard - attribution payload and render tests (~350 tokens)

## Do NOT read

- Patient pick/intake consent internals, `docs/archive/`

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - 2306 passed, 1 failed (tests/unit/test_contract_check.py, pre-existing)
- `npm run test:unit:frontend` - 1056 passed, 3 failed (2 pre-existing jsdom navigation fails in `choose-role/page.test.tsx`, 1 Daltonganj parity string in `page.test.tsx`)
- Note: sibling #493 and #494 are already committed locally on `feat/phase-8-care-eprescription` - the frequency field and edited tracker exist; this ticket builds on that tree.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` - new attribution-payload test passes
- `npm run test:unit:frontend` - issued name render + fallback + parity pass
- `npm run typecheck`

## Handoff notes

- Reg-no is out of scope by decision (no scalar reg-no exists - only encrypted `medical_registration` artifact docs and `practice_name`); do not invent a number, do not add schema.
- Keep the projection additive (an issuer block beside `attributed_doctor`) so unaffected consumers keep compiling.
- Degrade to the existing "Attributed to you" copy when the issuer name is unavailable.
