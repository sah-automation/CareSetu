# Brief - T7 Access-denial attempts emit patient.auth_failed

**Ticket:** #87 · **Parent:** #75 · **Refreshed:** 2026-08-13
**Reading surface:** ~8K tokens (budget ~10K) - within budget

## Scope

Access denials on protected routes become auditable. When an authenticated caller is refused on a protected route (insufficient scope / missing role), the iam module publishes `patient.auth_failed` (reason `access_denied`) for that identity, so the release-readiness criterion "access-denial attempts written to audit events" holds. Anonymous denials carry no identity to attribute and stay log-only, documented as a boundary.

Acceptance criteria:

- [ ] A 403 on a protected route for an authenticated caller writes `patient.auth_failed` (reason `access_denied`) to the iam outbox, in its own transaction
- [ ] The event names the correct identity and phone
- [ ] Anonymous 401s remain log-only (documented) - no outbox write
- [ ] The `access_denied` failure reason is part of the shared failure-reason vocabulary
- [ ] Unit tests cover the authenticated-denial emission and the anonymous no-op

## Read-list (in order)

1. Spec #51 (PHASE-2-IAM-AUTH): user story 44 + release readiness - "access-denial attempts and auth failures reach the audit event stream"; events flow through the module outbox (Implementation Decision 6) (~0.3K).
2. `docs/architecture/internal-modules.md` §4.2 event registry - the `patient.auth_failed` row: `MOD-001` (IAM) -> `MOD-011`, JSON, at-least-once; the doc-side single source of truth (~0.5K).
3. `docs/standards/security-phii-standards.md` - authn/authz failures 100% audited (`KPI-006`), appended to MOD-011's hash-chained append-only log; `docs/standards/error-handling-observability.md` - no-PHI in logs (never the phone/token), `trace_id` correlation (~0.5K).
4. The protected-route dependency + gateway error handlers (where 403 is produced and where the request carries the principal):
   - `require_patient(request)` dependency (`app/gateway/rbac.py`) - raises `InsufficientScopeError` for an authenticated principal without the patient role (403), `AuthenticationRequiredError` for anonymous/missing (401); `resolve_scope_roles(scope)` maps the token scope claim to roles (~0.4K).
   - `error_response(...)` + `register_gateway_error_handlers` (`app/gateway/errors.py`) - the single 401/403/429 envelope funnel; the 403 handler is currently log-only (`gateway_rejection` line), no outbox write (~0.5K).
   - The `Principal` model (`app/gateway/principal.py`) - `for_subject(subject_id, *roles)`, `anonymous()`, carries the authenticated identity the 403 must name (~0.3K).
   - `JWTVerifyMiddleware` (`app/gateway/jwt_verify.py`) - attaches the typed `Principal` to `request.state` on every verified request (~0.4K).
5. The `patient.auth_failed` payload + emitter - `PatientAuthFailedPayload` (`identity_id: int | None`, `phone_e164`, `reason: FailureReason`, `attempts_left`) and the `patient_auth_failed_envelope(...)` builder in the iam event builders (`modules/iam/domain/events.py`); canonical name constant `EVENT_PATIENT_AUTH_FAILED` in `bus/events.py` (~1K).
6. The shared failure-reason vocabulary - `FailureReason` Literal in the challenge machine (`modules/iam/domain/verify.py`): today `wrong_code | expired | spent | replay | no_challenge | suspended | locked`. `access_denied` is NOT yet present; grep for `access_denied` returns nothing repo-wide (~0.5K).
7. The iam facade's existing outbox-write pattern for auth-failure events (`modules/iam/facade.py`) - the reject helpers (`_reject_no_challenge` / `_reject_suspended` / `_reject_locked`) and the refresh-replay path: `write_outbox(connection, ...)` inside its own `engine.begin()` transaction, envelope built by `patient_auth_failed_envelope`; the `_identity_phone` helper used to resolve a phone from a session (~2.5K).
8. The outbox writer API - `write_outbox(connection, schema, table_name, envelope)` (`bus/outbox_writer.py`): inserts a pending row in the caller's active transaction, never inspects the payload; "own transaction" means a fresh transaction boundary on the caller side (~0.3K).

## Do NOT read

- Frontend, dispatcher internals (`bus/dispatcher.py`, `bus/registry.py`, worker), `docs/archive/`, `phase0/`.
- MOD-011 audit-module internals - Phase 4 consumes the events; this ticket only emits.
- The OTP/session state machines beyond the auth-failure write pattern (lockout counter, rotation details).
- T1 (#84) and T10 (#82) bodies - they are open; only their constraints matter here (see Handoff notes).

## Baseline verify

- `npm run test:unit:backend` (from ticket; the backend unit suite was already verified green centrally: 494 passed on 2026-08-13)

## Done-verify

- `npm run test:unit:backend`
- `npm run typecheck:backend`
- `npm run lint`

## Handoff notes

- Parent #75 finding: access-denial attempts were never audited - the gateway 403 terminates in `error_response` as a log-only `gateway_rejection` line; there is no outbox write anywhere on that path.
- T10 (#82) will refactor the facade guard-state/reject paths this ticket touches - keep behavior identical, do not pre-refactor while wiring the emission.
- T1 (#84) establishes event-name/status-literal single source of truth (still open) - `FailureReason` currently lives in `modules/iam/domain/verify.py`; add `access_denied` to that shared vocabulary, not a new ad-hoc literal.
- Boundary to document (and unit-test): anonymous 401s stay log-only - only authenticated 403s write to the outbox.
- Wiring seam: the 403 path carries the `Principal` (`subject_id`, roles), but `PatientAuthFailedPayload` also requires `phone_e164`; resolving the phone for the named identity (e.g. the facade's `_identity_phone`) belongs in the iam module per spec #51 (user story 44, Implementation Decision 6) - the gateway stays a thin adapter. Verify whether T1's literal changes affect `check_event_names.py`-style guards.
