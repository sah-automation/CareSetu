# Brief - T12 Doc deltas for the remediation

**Ticket:** #83 · **Parent:** #75 · **Refreshed:** 2026-08-13
**Reading surface:** ~8K tokens (budget ~10K) - within budget

## Scope

The docs record the contracts this remediation settles, so later phases read the truth rather than drift. The event registry in internal-modules.md §4.2 gains the `otp.failed` delivery reason and the access-denial audit boundary; the release-readiness note is updated; and the deliberate phase-2 choices the review flagged as scope creep (dev/test OTP read-back route, the repo-wide snake_case event-name gate, reserved partner/operator scopes, the backend-only refresh seam) get their justifications recorded. No em-dashes (repo rule).

Acceptance criteria:

- [ ] internal-modules.md §4.2 reflects `otp.failed` (lockout + delivery) and the access-denial boundary (authenticated -> `patient.auth_failed`; anonymous -> log-only)
- [ ] The roadmap §2.2 release-readiness line reflects the measured `validate_token` criterion
- [ ] The dev/otp route, check_event_names gate, reserved scopes, and backend-only refresh seam each carry a recorded justification
- [ ] `npm run lint` passes (whitespace + em-dash gate)

## Read-list (in order, token estimates)

1. Blocker tickets T3 #76, T5 #81, T7 #87 bodies - the settled contracts to record (already read for this brief; ~2K).
2. The doc-delta conventions from the original phase-2 doc ticket - `docs/agents/briefs/PHASE-2-T11-doc-deltas.md` and its parent ticket: event registry §4.2 is the single source of truth, updated in the same pass as the MOD-001 spec; the `_Avoid_` note for legacy snake_case event names supersedes the PRD's legacy telemetry names (~0.5K).
3. `docs/adr/0004-otp-challenge-and-brute-force-contract.md` - the OTP challenge + brute-force contract: latest-wins resend with >= 60 s cooldown, 15-min temporary lockout as a counter (never identity state), lockout distinct from `Suspended`, and the auth-events-through-the-outbox line (decision 6). The cooldown/lockout contract from T3 and the `otp.failed` reason set from T5 both land here (~1K).
4. `docs/architecture/internal-modules.md` §4.2 event registry - the `otp.failed` and `patient.auth_failed` rows (`MOD-001` -> `MOD-011`, JSON, at-least-once); §3.1 MOD-001 - outbound events list, the OTP challenge machine bullet (cooldown/lockout), and the brute-force lockout bullet. T5 adds the delivery reason to `otp.failed`, T3 extends the lockout enforcement wording to the begin-or-resume path, T7 adds the access-denial boundary (~2K).
5. `docs/roadmap/implementation-roadmap.md` §2.2 (Phase 2) release-readiness line - the `validate_token` p95 < 100 ms criterion (measured by T9) and the "access-denial attempts written to audit events" criterion (verified by T7); §3.1 feature->module->phase traceability matrix for the `FEAT-001` row (~1.5K).
6. `CONTEXT.md` glossary - the domain single-context layout; confirm no new terms this ticket needs and that the `_Avoid_` snake_case event-name note still reads consistently with the §4.2 registry (~1K).

## Do NOT read

- `docs/archive/` (explicitly out), `phase0/`, any application code, frontend, dispatcher internals, other modules' specs (MOD-002..MOD-011).
- The OTP/session state-machine internals beyond their documented contract - the contracts are what this ticket records, not re-derives.

## Baseline verify

- `npm run lint` (from ticket; unit suites already verified green centrally: backend 494 passed on 2026-08-13)

## Done-verify

- `npm run lint` (whitespace + em-dash gate)
- Review the three doc files (ADR-0004, internal-modules.md, implementation-roadmap.md) against the acceptance criteria

## Handoff notes

- T5 #81 - `otp.failed` gains a delivery emitter: the event payload models both reasons (`lockout` unchanged + `delivery`); the event registry §4.2 must list both emitters and the shared failure-reason vocabulary must carry both.
- T3 #76 - register/login honours the resend cooldown & lockout: the begin-or-resume entry enforces the same 60 s cooldown and brute-force lockout as the resend gate; no fresh challenge or SMS when refused. ADR-0004 and internal-modules §3.1 are the targets - the lockout/cooldown wording must cover the register path, not just verify/resend.
- T7 #87 - access-denial boundary: authenticated 403 -> `patient.auth_failed` (reason `access_denied`) in the iam outbox in its own transaction; anonymous 401 stays log-only, documented as a boundary. ADR-0004 decision 6 and internal-modules §4.2 are the targets.
- The three doc files under review are ADR-0004, internal-modules.md, and implementation-roadmap.md (the ticket's "review the three doc files" plus the release-readiness line) - confirm placement of the four scope-creep justifications (dev/otp read-back route, check_event_names gate, reserved partner/operator scopes, backend-only refresh seam) in the doc that best matches their nature: contract decisions belong in ADR-0004, module/interface shape in internal-modules.md, phase choices in the roadmap.
- No em-dashes anywhere (repo rule) - the `npm run lint` gate enforces this; check all four recorded justifications and any copied verbatim strings.
