# Brief - T03 Split auth & role-entry UX detail

**Ticket:** #181 · **Parent:** #178 Wayfinder map: Top-level UI Blueprint · **Refreshed:** 2026-08-21
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

Decision question (verbatim): Nail down the split-auth UX: patient phone-OTP wizard (existing) vs staff professional login page (email+password vs OTP+MFA mix, per role); registration flows per role (patient self-serve; partner/doctor registration wizard with credential upload and gated-activation states: registered -> under verification -> active/rejected); post-login routing by role; pending-activation and rejection screens.

Resolution must produce: the staff login page composition and credential scheme per role, the partner/doctor registration wizard step list, state-specific screens (pending, rejected-with-reason), post-login routing rules, and explicit notes of backend implications (MOD-001 staff credentials are NOT built yet - Phase 5 territory).

## Read-list (in order)

1. Map #178 body (Notes) - split-auth standing preference (~0.5K)
2. `docs/prd/project-prd.md` §4.1.1 `FEAT-001` Patient Registration & Identity - the OTP loop, lockout, duplicate resolution the patient side already follows (~2K)
3. `docs/prd/project-prd.md` §4.7.1 `FEAT-014` Open Registration & Gated Activation - partner states: Registered -> Under Verification -> Active | Rejected (~1.5K)
4. `docs/adr/0005-cookie-localstorage-dual-jwt.md` - current token transport; staff flow must fit or explicitly revise it (~1K)
5. Auth interfaces (names only): `AuthContext` API (`user`, `selectedRole`, `switchRole`, `logout`) and `PatientAuthWizard` props - what the new flows must integrate with (~1K)

## Do NOT read

- Backend IAM implementation, SMS provider code, roadmap phases other than the Phase 5 summary table row, archive docs.

## Baseline verify (must pass before the first edit)

- None - read-only decision session; do not edit code.

## Done-verify (acceptance criteria → commands)

- Resolution comment on #181 with the flows/screens decided; ticket closed
- Map #178 Decisions-so-far gains one line linking #181

## Handoff notes

- Operators get MFA eventually (roadmap Phase 5 mentions role grants/MFA) - decide whether MFA is designed-in now as a later slot or out of the top-level blueprint.
- Current `/choose-role` page exists because one OTP login serves all roles; split auth may obsolete it - coordinate with "Shell & navigation model" (its brief audits the same surfaces).
- Phone lockout and OTP budgets (5-min validity, attempt caps) are settled domain vocabulary in `CONTEXT.md` - reuse, don't reinvent.
