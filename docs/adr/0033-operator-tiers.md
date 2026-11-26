# ADR-0033: Operator tiers - admin vs operator distinction with JWT claim and RBAC

**Status:** accepted
**Date:** 2026-10-29
**Decides:** That the operator group is split into two tiers - `admin` and `operator` - carried as a JWT claim, derived on refresh, exposed on the gateway principal, and enforced by an admin guard. New invites default to `operator`. The last admin cannot be demoted or deactivated.
**Traceability:** `plan-phase14-observability.md` §13; spec #761; parent #761; tickets #762, #763, #766, #767, #768, #769, #770. Related: `ADR-0007` (split-origin deployment), `ADR-0030` (SLOs), `ADR-0031` (accepted risk), `internal-modules.md` §3.1 (MOD-001), §3.15 (MOD-014).

## Context

The Phase 14 observability plan (§13) and PHASE-14B Batch 2 scope name operator tiering as a deferred item from Batch 3: "Operator admin/non-admin (`operator_tier`) schema, JWT claim, and tier RBAC decorator. Batch 3 shipped the navigation shell only." The operator console currently has flat `require_operator` RBAC with no tier distinction. The settings page (AI config, notification config, feature flags, user management) requires admin-gated writes, and the operator list/invite/promote/deactivate flows need tier-aware permissions.

## Decision

### D1 - Two-tier model in the IAM operator profile

A new `iam_operator_profiles` table (added by #763 in the `iam` schema) stores per-operator metadata keyed by `identity_id`:

- `tier` - `admin` | `operator` (default `operator`)
- `active` - boolean (default true)
- `mfa_failed_attempts` - counter for TOTP lockout (#778)
- `mfa_lockout_until` - timestamp
- `created_by` - identity_id of the inviting admin
- `updated_by` - identity_id of the last modifier

The migration backfills every existing identity with an active `admin` role grant as `admin` tier so the current operator group is not locked out.

### D2 - JWT claim and gateway principal

- The tier is included in the operator access JWT as `operator_tier` claim.
- On token refresh, the tier is re-derived from the `iam_operator_profiles` table (not cached in the refresh token).
- The gateway principal (`app/gateway/principal.py`) exposes `operator_tier: str | None` for operator callers.
- Missing or unknown tiers fail admin routes closed (the admin guard rejects `operator`, `None`, and unknown values with the shared 403 envelope).

### D3 - Admin guard

A new RBAC decorator `require_admin` (in `app/gateway/rbac.py`) wraps `require_operator` and additionally checks `principal.operator_tier == "admin"`. Admin-gated routes:

- `PUT /v1/operator/feature-flags/{flag_key}` (runtime flag writes)
- `PUT /v1/operator/settings` (allowlisted setting writes)
- `GET /v1/operator/settings/effective` (effective settings read - source/allowlist visibility)
- `GET /v1/operator/settings/history` (setting history)
- Operator list, invite, promote/demote, deactivate/reactivate (Settings Users section, #801)

The existing `require_operator` remains for operator-visible reads (feature flag list/history, observability lenses, security page).

### D4 - Tier change guards

- An operator cannot change their own tier or active state (enforced in the Settings Users section write handler).
- The last admin cannot be demoted or deactivated (enforced by a pre-write check that counts active admins).
- New operator invites default to `operator` tier (the invite API accepts an optional `tier` parameter; if omitted, `operator` is used).

### D5 - First-admin CLI promotion

A CLI command `python -m scripts.promote_first_admin --phone +91XXXXXXXXXX` exists for bootstrapping the very first admin when no operator exists yet. It creates the operator profile with `admin` tier if the identity exists, or guides through the operator MFA enrollment flow. This is a one-time bootstrap tool, not a runtime API.

## Considered options

- **Single flat operator role with a separate admin flag.** Rejected - a tier enum is more explicit, extensible (future tiers like `super_admin` or `read_only` are possible), and maps cleanly to a JWT claim.
- **Tier stored only in JWT, not in DB.** Rejected - the tier must be re-derived on refresh and survive token rotation; it is authoritative in the DB.
- **Allow self-demotion/self-deactivation.** Rejected - would allow the last admin to lock themselves out. The guard prevents this.
- **No CLI bootstrap.** Rejected - the first admin must be created before any operator can invite another.

## Consequences

- The operator console Settings tab splits into admin-visible (AI, Notifications, Feature Flags, Users) and operator-visible (read-only observability lenses, security page) sections.
- The `operator_tier` JWT claim is a new field in the operator token; the patient and partner tokens are unchanged.
- The admin guard is a new RBAC primitive that other phases can compose.
- The `iam_operator_profiles` table is the source of truth for tier and active state; the JWT claim is a derived snapshot at issuance.
