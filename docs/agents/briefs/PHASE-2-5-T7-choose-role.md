# Brief - T7 Frontend - Choose-role page for multi-role users

**Ticket:** #153 · **Parent:** #146 Phase 2.5 · **Refreshed:** 2026-08-17
**Reading surface:** ~4K tokens (budget 10K) - well within budget

## Scope

A `/choose-role` page for users with multiple roles. Displays available roles as selectable cards. On selection: stores the chosen role in localStorage and a cookie, then redirects to `/{role}` dashboard. Unauthenticated access redirects to `/login`. This page is not actively used yet (only patient role exists), but the infrastructure is in place for Phase 5+ when partner/operator roles are granted.

Acceptance criteria (verbatim):

- `/choose-role` route renders a role selection screen
- Available roles displayed as cards with role name and description
- Clicking a role card stores the selected role and redirects to `/{role}`
- Selected role stored in localStorage (key: `caresetu.selected_role`) and readable by middleware
- If no valid session: redirects to `/login`
- If only one role: redirects directly to `/{role}` (skip selection)
- Unit tests pass: role cards render, selection works, redirect behavior correct

## Read-list (in order)

1. AuthContext API (from T3 output) - the `user.roles` array and `switchRole(role)` function; the choose-role page reads roles from context and calls switchRole on selection (~1K tokens)
2. `src/lib/auth/session.ts` (50 lines) - `saveSession`, `readSession` for the role storage pattern; the selected role is stored alongside session data (~0.5K tokens)
3. Role types from backend (`patient`, `partner`, `operator`) - the three role values; each maps to a route segment (`/patient`, `/partner`, `/operator`) (~0.3K tokens)

## Do NOT read

- Backend code, dashboard components, auth wizard, OTP state, other modules, PRD, roadmap.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` (existing tests pass)

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` - existing + new choose-role tests pass
- New test file covers: role cards render for multi-role user, single-role user skips selection, unauthenticated redirects to login

## Handoff notes

- The page should check AuthContext on mount: if `user.roles.length === 1`, redirect directly to `/{role}` without showing the selection UI.
- Role cards should display: role name (e.g., "Patient", "Doctor", "Operator") and a brief description (e.g., "View your health records", "Manage consultations", "Platform administration").
- On role selection: store `caresetu.selected_role` in localStorage (matching the key middleware T5 reads), then call `switchRole(role)` from AuthContext, then `router.push("/{role}")`.
- The page is a client component (`"use client"`) since it uses hooks and navigation.
- This page is infrastructure-only - only the patient role is currently active. The UI should gracefully handle the single-role case (auto-redirect).
