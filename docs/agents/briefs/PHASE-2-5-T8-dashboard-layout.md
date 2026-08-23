# Brief - T8 Frontend - Dashboard layout with sidebar and topbar

**Ticket:** #154 · **Parent:** #146 Phase 2.5 · **Refreshed:** 2026-08-17
**Reading surface:** ~4K tokens (budget 10K) - well within budget

## Scope

A shared dashboard layout with fixed left sidebar and topbar, wrapped around all role dashboard routes via the `(dashboard)` Next.js route group. Sidebar shows role-conditional navigation items with "Soon" badges for unbuilt features. Topbar shows user phone, current role badge, role switcher dropdown (for multi-role users), and logout button. Scaffold pages at `/patient`, `/partner`, `/operator` showing "Welcome, {role}" in the main content area. Vercel/Render-inspired modern aesthetic using Tailwind CSS.

Acceptance criteria (verbatim):

- `(dashboard)/layout.tsx` created as shared layout for all role routes
- Fixed left sidebar: 240px width, collapsible to 64px icon-only on screens < 1024px
- Sidebar nav items per role:
  - Patient: Home, My Records, Appointments, Medicines, Consent, Notifications
  - Partner: Home, Active Cases, My Profile, Settlements
  - Operator: Home, User Management, Moderation, Audit Trail
- "Soon" badge displayed on nav items for features not yet built (all except Home)
- Topbar: user phone display, current role badge, role switcher dropdown (if multi-role), logout button
- Logout calls AuthContext `logout()` and redirects to `/`
- `(dashboard)/patient/page.tsx` renders "Welcome, Patient" scaffold
- `(dashboard)/partner/page.tsx` renders "Welcome, Partner" scaffold
- `(dashboard)/operator/page.tsx` renders "Welcome, Operator" scaffold
- Layout uses Tailwind CSS for all styling
- Layout is responsive: sidebar collapses on tablet, full layout on desktop
- `npm run build` succeeds
- Unit tests pass: sidebar renders correct items per role, logout works

## Read-list (in order)

1. AuthContext API (from T3 output) - `user` (id, phone, roles), `selectedRole`, `switchRole(role)`, `logout()`; the layout reads user data and provides logout (~1K tokens)
2. `src/components/auth/icons.tsx` (171 lines) - 15 existing SVG icon components (Home, Heart, Shield, Phone, Lock, Check, Refresh, etc.); reuse for sidebar nav icons (~1.5K tokens)
3. `apps/frontend/tailwind.config.ts` (from T2 output) - design tokens for styling the layout (~0.3K tokens)
4. `src/lib/auth/session.ts` (50 lines) - `StoredSession` type for user data shape (~0.3K tokens)

## Do NOT read

- Backend code, auth wizard (PatientAuthWizard), OTP state, other modules, PRD, roadmap.

## Baseline verify (must pass before the first edit)

- `npm run build` (frontend builds without dashboard layout)

## Done-verify (acceptance criteria → commands)

- `npm run build` - dashboard layout compiles
- `npm run test:unit:frontend` - existing + new layout tests pass
- Manual: login, see sidebar+topbar on `/patient`, verify nav items, test logout

## Handoff notes

- The `(dashboard)` route group is a Next.js convention: parenthesized directory name applies a shared layout without adding a URL segment. All routes under `(dashboard)/` get the layout.
- The current `/patient`, `/partner`, `/operator` pages are in `(patient)/patient/`, `(partner)/partner/`, `(operator)/operator/` directories. You need to restructure them under `(dashboard)/` or create a new `(dashboard)/` group that wraps the existing routes.
- Sidebar nav items: all items except "Home" show a "Soon" badge and are non-clickable (no `href`, styled with reduced opacity). Home links to `/{role}` (the dashboard root).
- Role switcher dropdown: only shown when `user.roles.length > 1`. Uses `switchRole(role)` from AuthContext, which updates `selectedRole` and redirects.
- Logout: calls `logout()` from AuthContext, which clears localStorage, clears cookie, and redirects to `/`.
- Use existing icons from `icons.tsx` where possible (Home, Heart, Shield, etc.); create simple text/emoji fallbacks for icons not yet available.
- Responsive behavior: sidebar full width (240px) on desktop (>= 1024px), collapsed to icon-only (64px) on tablet (< 1024px). Use Tailwind responsive utilities (`lg:` prefix).
