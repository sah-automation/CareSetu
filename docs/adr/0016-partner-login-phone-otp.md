# ADR-0016: Partner login is phone-OTP on dedicated auth routes

**Status:** accepted
**Date:** 2026-09-17
**Traceability:** `FEAT-014`, `MOD-001`, `MOD-002`, `EXT-001`, `ADR-0010`. Supersedes the UI blueprint's earlier "email + password for all staff roles / No OTP for staff" assumption (§4.2), the §4.3 email/password wizard step, and gap entry G3.

## Context

Partner login had no settled contract. The UI blueprint specified email + password for all staff roles with "No OTP for staff", while the Phase 5 spec and ADR-0010 described a phone-OTP pre-activation login, and the backend has no password storage, hashing, reset, or email ownership check at all (parent spec #460). A doctor, lab, or chemist who registered and closed the browser had no way to log back in, and the pre-activation session could be minted for a phone without proving the caller owns it.

This ADR records the login method decision from parent spec #460's Implementation Decisions so the documents and the backend agree on one mechanism.

## Decision

**Partner login is phone + SMS one-time code, served on dedicated `POST /v1/auth/partner/*` routes**, reusing the existing patient OTP challenge machine unchanged (single-use hashed code, short validity, limited attempt budget per challenge, latest-wins resend with cooldown, temporary phone lockout). Phone input is normalized server-side to E.164; the country code is never trusted from the client.

1. **Dedicated routes, never the patient routes.** `POST /v1/auth/partner/login` issues a challenge only for a phone that has a partner profile (refusing otherwise and never creating an identity); `POST /v1/auth/partner/verify` consumes the challenge and marks the partner's phone verified, granting no patient role and emitting no `patient.*` event; `POST /v1/auth/partner/session` is tightened to require the phone-verified identity before minting. Because the routes are dedicated, a partner login can never accidentally grant patient capability or emit patient events.
2. **OTP-bound session mint.** No partner session is minted without a successful phone-code verification on the dedicated route - knowing a partner's number is not enough to become them.
3. **Pre-activation renewal.** A `[Registered]`, `[Under Verification]`, or `[Rejected]` partner renews normally (`POST /v1/auth/refresh` reuses the same composition-boundary partner check as the session mint); only a suspended identity is refused. Approval gates patients and the partner role, never the session.
4. **Restriction enforced by reachable routes, not a distinct login kind.** Every partner uses the same phone-OTP login in every lifecycle state. The pre-activation restriction on what an unactivated partner can do lives in which routes the partner self-service surface exposes per state: status, rejection reason, and appeal are reachable in every state except suspended; credential submission is reachable for registered, under-verification, and rejected partners; the consultation fee is reachable only when active; suspended is a contact-support-only surface. There is no separate, reduced login.
5. **One method per audience.** Patient login stays phone-OTP; operator login stays phone + authenticator-app TOTP with its entry hidden from the partner-facing login page. Partners never use email/password or an authenticator app.

## Note on the duplicated `0004`

Two files claim ADR number `0004` and cover different decisions: `0004-otp-challenge-and-brute-force-contract.md` (the IAM OTP challenge and brute-force posture) and `0004-consent-gate-cache.md` (self-titled "ADR-004" - title and filename disagree - the consent-gate cache). The collision is noted here rather than silently perpetuated; the existing files keep their numbers and the next genuinely free number (0016, this file) is used from here on.

## Events

Partner login registers **no new event name** in the internal-modules §4.2 registry. OTP issuance reuses the existing `otp.sent`; partner phone verification is deliberately silent - it is not a lifecycle transition and must not touch the `patient.*` family. There is no `partner.verified`.

## Consequences

- The UI blueprint §4.2 staff-login page, §4.3 registration wizard (which gains a phone-confirmation step), and gap G3 are corrected to the phone-OTP model; `CONTEXT.md` gains the vocabulary.
- Existing partners registered through the earlier no-OTP wizard keep their identities and verify their phone on their next login; no data migration.
- Session transport is unchanged: partner sessions use the same access-token-with-refresh model, cookie transport, and frontend save path as ADR-0005/ADR-0007.
