# Brief - 472 F014-T12 Final review: combined partner-login implementation (/code-review)

**Ticket:** #472 · **Parent:** #460 · **Refreshed:** 2026-09-17
**Reading surface:** ~5K tokens fresh (budget 10K) - within budget (builds on the eleven prior briefs' loaded context)

## Scope

A final, whole-feature review: every ticket 01-11 has landed, and the entire partner-login feature is reviewed together on the two axes of the repo's code-review skill - **Standards** (does the code follow the documented coding/API/security/error-handling standards?) and **Spec** (does the combined result match what issue #460 asked for?). Any bug, contradiction or spec drift found is fixed here so the feature is actually done, not just merged piecewise.

Acceptance criteria (verbatim from ticket):

- [ ] A `/code-review` pass over the combined `01 → 12` implementation reports the Standards and Spec findings side by side.
- [ ] Every confirmed defect or spec drift from that review is fixed and re-verified; fixes land as part of this ticket's branch with the review noted.
- [ ] The repo harness is green after the fixes: unit suites, integration (with live Postgres), lint, typecheck, migration-check.
- [ ] Any unresolved finding is documented back on this ticket with an explicit reason, not silently dropped.

**Blocked by:** #461, #462, #463, #464, #465, #466, #467, #468, #469, #470, #471 - the whole feature must be present before it can be reviewed as a whole.

## Read-list (in order)

1. The repo `code-review` skill workflow (`D:\Dev\tools\opencode\config\opencode\skills\code-review\SKILL.md`) - the two-axis (Standards vs Spec) parallel-review procedure to run against the combined diff. (~0.8K)
2. The parent spec #460 full body - the Spec-axis reference: problem statement, user stories, implementation decisions (dedicated `POST /v1/auth/partner/*` routes, OTP-bound mint, pre-activation renewal in every non-suspended state, reachable-routes enforcement, silent phone verification, no `patient.verified`, role grant only via operator activation, ADR-0007 invariants), testing decisions, and out-of-scope list. (~4K)
3. The eleven briefs #461-471 in this folder - the per-slice contracts whose combined result this ticket verifies; the implementer already holds these from the serial chain. (~2K)
4. The combined diff surface of the eleven tickets (branch diff from the parent #460 base) - reviewed through the code-review skill, not re-read from scratch. Plus the relevant standards: `docs/standards/coding-standards.md`, `api-standards.md`, `security-phii-standards.md`, `error-handling-observability.md` (+ `docs/adr/0007-split-origin-deployment-session-invariants.md` as the hard auth/session gate). (~2K)

## Do NOT read

- Anything outside the feature's own surface and its standards: unrelated modules, the frontend/back-end internals not named by #460 or the briefs, `docs/archive/`.

## Baseline verify (must pass before the first edit)

Full harness on the pre-review tree (all eleven tickets merged): `npm run test:unit:backend` (2184 passed on the shared base), `npm run test:unit:frontend` (936 passed), `npm run lint`, `npm run typecheck`, `npm run migration-check` - all green this session. `npm run test:integration` requires live native PostgreSQL (reachable locally; the full suite runs long).

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`, `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck`, `npm run migration-check` all green after any fixes.
- `npm run test:integration` (live Postgres) and `npm run test:e2e` (Playwright) re-run where the review touched those surfaces.
- Code-review skill run recorded against the combined diff; both axes reported; unresolved findings written back on the ticket.

## Handoff notes

- Closest repo precedents: the `437-t9-combined-two-axis-review` brief and the `REVIEW-FIX-*` family - run the review, then land each fix as its own commit under this ticket, with the review recorded.
- Pay special attention to cross-ticket seams where each slice passes alone but the combined behavior must hold: the OTP machine shared by #462/#463, the phone-verified marker read by #464 and written by #463, the same router/facade files touched by #462-466 in sequence, the confirm-before-mint order enforced by #464 on the #468 wizard, and the state-driven landing of #469 feeding off #465's renewal + #466's gates.
- Watch spec-drift hotspots flagged during briefing: consultation-fee `[Active]` rule (was doctor-only before #466), the `partnerState`/suspended landing edge (#469), and the no`partner.verified` rule (any event added by #462/463 is a Spec violation).
- Any true contract gap (not just a bug) needs a spec change back at #460, not a silent scope expansion - the AC's "explicitly documented" escape hatch is for findings, not for moving the feature goalposts.
