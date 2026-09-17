# Brief - 461 F014-T01 Docs reconciliation: partner login method (phone-OTP)

**Ticket:** #461 · **Parent:** #460 · **Refreshed:** 2026-09-17
**Reading surface:** ~9K tokens (budget 10K) - within budget

## Scope

The project's own documents stop disagreeing about the partner login method. A doctor, lab or chemist reading any of the authoritative docs learns that partner login is phone + SMS one-time code, and the blueprint/spec/roadmap/code all say the same thing. The new decision is recorded as an ADR under the next genuinely free number, with the duplicated `0004` noted. The UI blueprint's stale email/password staff-login sections, the registration-wizard description and the relevant gap entries are corrected; `CONTEXT.md` gains the partner login vocabulary.

Acceptance criteria (verbatim from ticket):

- [ ] A new ADR is written under the next genuinely free ADR number, recording: partner login is phone-OTP via dedicated `POST /v1/auth/partner/*` routes; the OTP-bound session mint; pre-activation renewal; the pre-activation restriction is enforced by reachable routes rather than a distinct login kind; patient login stays OTP, operator stays TOTP. The duplicated `0004` (OTP challenge / consent-gate cache) is noted without silently perpetuating the collision.
- [ ] The UI blueprint §4.2 staff-login page no longer specifies email + password for partner login and no longer says "No OTP for staff"; it describes the partner phone-OTP mode and the still-hidden operator entry. The registration wizard §4.3 gains the phone-confirmation step. Gap G3 (and any successor text) no longer assumes email/password staff auth.
- [ ] `CONTEXT.md` glossary gains the partner login vocabulary: credential account, partner login, the clarification that the pre-activation restriction is enforced by reachable routes (not a distinct kind of login), and phone-OTP vs operator-TOTP distinction. Any inverse terminology (`_Avoid_` notes) are added.
- [ ] The Phase 5 spec's phone-OTP pre-activation login section and the roadmap Phase 5 / Phase 2.5 deferred items are consistent with the new ADR; where the roadmap or internal-modules menu contradicted the login method, it is corrected or explicitly superseded by the new ADR.
- [ ] The internal-modules event registry §4.2 confirms no new event names are introduced by this feature (partner phone verification is silent).

**Blocked by:** None - can start immediately.

## Read-list (in order)

1. `docs/design/ui-blueprint.md` §4.2 Staff login page, §4.3 Provider registration wizard, §4.4 state-specific screens, §4.5 post-login routing, §4.6 fate of /choose-role; §10 gaps register (entry G3); §12 PHASE-2.6 scope sketch (entry W3) - the stale email/password partner-login text to correct ("email + password for all staff roles. No OTP for staff.", the §4.3 email/password wizard step, G3's email+password credential type, W3's "staff authentication stays Phase 5"). (~1.5K)
2. `docs/spec/phase-5-partner-onboarding.md` "Pre-activation login (restricted scope)" under Implementation Decisions (near "Partner account creation (ADR-0010)") - the authoritative phone-OTP partner-login contract this reconciliation aligns everything to. (~0.6K)
3. ADRs: `docs/adr/0004-otp-challenge-and-brute-force-contract.md`, `0004-consent-gate-cache.md` (the duplicate - confirms the collision to note), `0009-partner-notification-channel-fallback.md` ("no email field", phone-OTP-based), `0010-partner-account-sync-at-registration.md` (sync credential account for pre-activation login), `0007-split-origin-deployment-session-invariants.md` (only if session-transport wording is touched). Next genuinely free ADR number is 0016. (~1.9K)
4. `docs/roadmap/implementation-roadmap.md` §2.2 (Phase 2, deferred list), §2.2a (Phase 2.5, deferred phone+OTP auth flows), §2.2b (Phase 2.6, deferred "email-credential backend" line), §2.5 (Phase 5) - the deferred-item text to reconcile. Note the roadmap heading numbers are shifted: Phase 2.5 lives under §2.2a and §2.5 IS Phase 5. (~1.5K)
5. `docs/architecture/internal-modules.md` §3.1 (MOD-001 outbound events), §3.2 (MOD-002 outbound events), §4.2 async event registry - confirm `otp.sent` is reused and no new event name (there is deliberately no `partner.verified`). (~2.5K)
6. `CONTEXT.md` glossary, "Partner onboarding & gated activation (Phase 5)" section - where the partner login vocabulary goes, including the `_Avoid_` inverse terms. (~1.0K)

## Do NOT read

- `docs/archive/` (superseded; the PRD/spec are the single source), any brief files under `docs/agents/briefs/` (they are prior-session artifacts, not authoritative), backend or frontend source for this ticket.

## Baseline verify (must pass before the first edit)

- `npm run lint` (includes the no-em-dash and legacy snake_case event-name gates) - confirmed green this session.
- `npm run migration-check` (single-head + cross-schema-FK + ADR cross-ref check) - confirmed green this session.

## Done-verify (acceptance criteria → commands)

- `npm run lint` and `npm run migration-check` green after the doc edits.
- Manual grep: no remaining "email + password for all staff roles", "No OTP for staff", or email/password partner wizard step in `docs/design/ui-blueprint.md`; `grep -rn "partner.verified"` returns nothing outside any explicit "no such event" note.
- New ADR present as `docs/adr/0016-<slug>.md` referencing PHONE-OTP partner login; `CONTEXT.md` inventory row for the new ADR updated.

## Handoff notes

- ADR numbering: highest existing is 0015; the next genuinely free number is 0016. Two files claim 0004 (`0004-otp-challenge-and-brute-force-contract.md` and `0004-consent-gate-cache.md`, the latter self-titled "ADR-004" - title/filename mismatch); the new ADR must note the collision without renumbering the existing files.
- Authoritative sources for the new ADR's claims: phase-5 spec "Pre-activation login (restricted scope)", ADR-0009 line ~9 (no email field; phone-OTP-based), ADR-0010 (sync credential account created so pre-activation login works), and parent spec #460's Implementation Decisions (dedicated `POST /v1/auth/partner/*` routes, OTP-bound mint, pre-activation renewal, reachable-routes enforcement).
- Stale text inventory (grep targets): blueprint §4.2 "No OTP for staff" + "email + password for all staff roles", §4.3 wizard step 1 email/password, §4.6 "until Phase 5 MOD-001 staff auth exists", §10 G3 email+password credential type, roadmap §2.2b "email-credential backend" deferred line. Correct these in place.
- Event registry: partner phone verification must stay SILENT. Do not add a `partner.verified` event anywhere - the parent spec explicitly forbids it and the registry confirms no such event.
- Tests for #461 are doc-level only (no code); route-seam tests for the new vocabulary land in OB-462 and later.
