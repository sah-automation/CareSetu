# Spec: Issue #330 Code Review Findings

## Problem Statement

The architecture deepening pass (#330) split the partner facade into four sub-facades, concentrated credential-validity into one module, absorbed the duplicate OTP re-issue choreography, and removed the `iam`-to-partner circular dependency. A two-axis code review (issues #331-#338) found two hard standard violations, one partial spec requirement, and one potential atomicity regression in the refactored partner module. These findings must be fixed before the work can be considered complete.

## Solution

Address all four review findings in a single focused pass:

1. Replace `Any` type annotations on sub-facade constructor parameters with minimal `Protocol` types that capture the surface actually called, satisfying the coding standard requirement to type everything.
2. Eliminate the duplicate `PARTNER_SCHEMA` constant by importing from the canonical `shared.py` source.
3. Relocate `PartnerView` from `common_models.py` to `registration_models.py`, establishing a single owning sub-facade per result model.
4. Restore the partner-profile existence check inside `issue_partner_session` under the identity row lock, re-establishing atomicity for the session-issuance path.

## User Stories

1. As a developer, I want all constructor parameters across sub-facades to carry concrete type annotations instead of `Any`, so that the codebase satisfies the "No `Any`, type everything" coding standard (coding-standards S3) and static analysis catches misuse at authoring time.
2. As a developer, I want `CredentialValidityPort` and `DirectoryCachePort` protocols defined once in a shared location, so that sub-facades express their dependencies as contracts rather than concrete implementations or untyped placeholders.
3. As a developer, I want the `CredentialIntakeFacade` to use the same `CredentialValidityPort` protocol as the other sub-facades instead of the `ModuleType` annotation, so that all three sub-facades that accept a credential-validity dependency express the same contract.
4. As a developer, I want `PARTNER_SCHEMA` defined in exactly one place (`shared.py`), so that the single-source-of-truth standard (coding-standards S2) is satisfied and schema name drift is impossible.
5. As a developer, I want `PartnerView` to live in `registration_models.py` as the primary owner, with a re-export from the coordinator facade, so that each sub-facade owns its result models (US10) and import paths reflect ownership.
6. As a developer, I want the operator-gate sub-facade to import `PartnerView` from `registration_models.py` rather than `common_models.py`, so that the model is consumed from its canonical location.
7. As a developer, I want the credential-intake sub-facade to import `PartnerView` from `registration_models.py` if it uses it, so that the same canonical path is used across the partner module.
8. As a developer, I want `issue_partner_session` to re-verify partner-profile existence under the identity row lock after receiving an advisory `partner_id`, so that a profile deleted between the route-level pre-check and the mint is caught atomically and does not produce a partner-scoped token for a now-patient-only phone.
9. As a developer, I want the route-level pre-check to remain as an early-rejection optimization, so that the common path (profile exists) is fast and the atomic re-check under lock is only the safety net.
10. As a developer, I want a unit test that exercises the concurrent profile-deletion scenario (profile deleted between route check and mint), so that the atomicity fix is regression-proof.
11. As a developer, I want the coordinator facade to re-export `PartnerView` from `registration_models.py`, so that existing external consumers (routes, other modules) do not need to update their import paths.
12. As a developer, I want the partner module's sub-facades to remain decoupled from each other's concrete implementations, so that the module isolation rule (no cross-schema imports) continues to be enforced through protocol-based dependency injection.

## Implementation Decisions

### F1: Protocol-based typing for sub-facade constructors

- Define two minimal `Protocol` classes in `modules/partner/shared.py`: `CredentialValidityPort` and `DirectoryCachePort`.
- `CredentialValidityPort` captures the three SQL predicates (`provider_visible`, `has_any_credential`, `has_invalid_credential`) and the async `close_out_credentials` method that sub-facades actually call.
- `DirectoryCachePort` captures the three async methods (`get_cached_search`, `set_cached_search`, `directory_visibility_changed`) that the directory sub-facade calls.
- The `Any` annotations on `credential_validity` and `directory_cache` in `DirectoryFacade.__init__` and `OperatorGateFacade.__init__` are replaced with `CredentialValidityPort` and `DirectoryCachePort` respectively.
- The `CredentialIntakeFacade.__init__` parameter `credential_validity: ModuleType` is replaced with `CredentialValidityPort` for consistency across all three sub-facades.
- The coordinator facade (`facade.py`) already passes module-level references that satisfy these protocols implicitly; no changes needed there.

### F2: Single `PARTNER_SCHEMA` constant

- Remove the local `PARTNER_SCHEMA = "partner"` definition from `credential_validity.py` (line 50).
- Add `from modules.partner.shared import PARTNER_SCHEMA` to `credential_validity.py` imports.
- The canonical definition remains in `shared.py` (line 41).

### F3: `PartnerView` ownership

- Move the `PartnerView` class definition from `common_models.py` to `registration_models.py`.
- Delete `common_models.py` entirely (it contains only `PartnerView`, so it becomes empty).
- Update the coordinator facade (`facade.py`) to import `PartnerView` from `registration_models` instead of `common_models`, keeping the re-export for backward compatibility.
- Update `operator_gate_facade.py` to import `PartnerView` from `modules.partner.registration_models`.
- Update `credential_intake_facade.py` to import `PartnerView` from `modules.partner.registration_models` if it uses it (verify during implementation).

### F4: Atomic partner-session issuance

- In `session_facade.py`, inside `issue_partner_session`, after locking the identity row (`SELECT ... FOR UPDATE`) and before minting the JWT: add a SQL re-check that verifies the partner profile still exists for the given `partner_id` and `identity_id` pair.
- The re-check queries the `partner` schema's `partner_profiles` table (via the existing `resolve_partner_id_by_identity` or a direct SQL check) under the same transaction as the identity row lock.
- If the re-check fails (profile no longer exists or `partner_id < 1`), raise `SessionIssuanceError` with a clear message.
- The route-level pre-check in `adapters/routes.py` remains unchanged as an early-rejection optimization.
- A new unit test exercises the scenario: profile exists at route check, gets deleted before mint, and the session issuance returns a 409/403 error.

## Testing Decisions

- **Test philosophy:** Tests exercise external behavior (API contracts, session issuance outcomes) not implementation details. The atomicity test verifies the error response when a profile is deleted mid-flow, not the internal SQL used.
- **Unit tests for F4:** Add tests in `tests/unit/test_iam_session.py` and `tests/unit/test_iam_session_route.py` covering the concurrent profile-deletion scenario. Mock the identity lock and partner-profile lookup to simulate the race.
- **Type-checking for F1/F3:** The mypy strict pass (`npm run typecheck`) will validate that the new protocols are correctly defined and that all sub-facades satisfy them. No additional type tests needed beyond the existing strict mode.
- **Regression tests:** Run the full unit suite (`npm run test:unit:backend`), typecheck, and lint after all four fixes. F4 additionally requires the integration suite with native PostgreSQL to confirm no regressions in the session-issuance happy path.
- **Prior art:** Existing unit tests in `tests/unit/test_iam_session.py` cover session issuance happy paths and error cases; the new test follows the same mocking pattern for the identity/partner resolution seams.

## Out of Scope

- No changes to the partner module's domain layer, schema layer, or outbox events.
- No changes to the IAM module's OTP, MFA, JWT, lockout, or refresh logic.
- No changes to the event bus, dispatcher, or outbox writer.
- No database migrations; all changes are code-level type annotations, import path updates, and a SQL re-check within an existing transaction.
- No changes to the coordinator facade's public API or the route layer's request/response contracts.
- No new sub-facades, modules, or cross-module seams are introduced.

## Further Notes

- The execution order from the plan (F2 first, then F1, F3, F4) is recommended because F2 is a one-line fix that unblocks the type-checking pass for F1.
- F1 and F3 are independent of each other and of F4; F2 should land first as a confidence-building warm-up.
- The `common_models.py` file becomes empty after F3 and should be deleted to avoid a dead import target.
- The `CredentialValidityPort` protocol should be kept minimal - only the methods the sub-facades actually call. Additional methods on the `credential_validity` module that are not called through the protocol boundary should not be added to the protocol.
