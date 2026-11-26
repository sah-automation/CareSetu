# Brief - 154 Frontend - Dashboard layout with sidebar and topbar

**Ticket:** #154 - **Parent:** #146 - **Refreshed:** 2026-08-18
**Reading surface:** ~3.1K tokens (budget 10K) - within budget

## Scope

A shared dashboard layout with fixed left sidebar and topbar, wrapped around all role dashboard routes via the `(dashboard)` Next.js route group. Sidebar shows role-conditional navigation items with "Soon" badges for unbuilt features. Topbar shows user phone, current role badge, role switcher dropdown (for multi-role users), and logout button. Scaffold pages at `/patient`, `/partner`, `/operator` showing "Welcome, {role}" in the main content area. Vercel/Render-inspired modern aesthetic using Tailwind CSS.

### Acceptance criteria

- [ ] `(dashboard)/layout.tsx` created as shared layout for all role routes
- [ ] Fixed left sidebar: 240px width, collapsible to 64px icon-only on screens < 1024px
- [ ] Sidebar nav items per role:
  - Patient: Home, My Records, Appointments, Medicines, Consent, Notifications
  - Partner: Home, Active Cases, My Profile, Settlements
  - Operator: Home, User Management, Moderation, Audit Trail
- [ ] "Soon" badge displayed on nav items for features not yet built (all except Home)
- [ ] Topbar: user phone display, current role badge, role switcher dropdown (if multi-role), logout button
- [ ] Logout calls AuthContext `logout()` and redirects to `/`
- [ ] `(dashboard)/patient/page.tsx` renders "Welcome, Patient" scaffold
- [ ] `(dashboard)/partner/page.tsx` renders "Welcome, Partner" scaffold
- [ ] `(dashboard)/operator/page.tsx` renders "Welcome, Operator" scaffold
- [ ] Layout uses Tailwind CSS for all styling
- [ ] Layout is responsive: sidebar collapses on tablet, full layout on desktop
- [ ] `npm run build` succeeds
- [ ] Unit tests pass: sidebar renders correct items per role, logout works

## Read-list (in order)

1. `apps/frontend/src/lib/auth/AuthContext.tsx` - AuthContext API: `user` ({id, phone, roles[]}), `selectedRole`, `switchRole()`, `logout()`, `isAuthenticated`, `isLoading`. Must understand loading gates to wrap dashboard routes. (~1.2K tokens)
2. `apps/frontend/src/components/auth/icons.tsx` - 16 existing SVG icon components (IconHome, IconDirectory, IconShield, IconBell, IconChevronLeft, IconChevronRight, IconClose, etc.). Reuse for sidebar nav and topbar. All accept `IconProps: { size?, className? }`. (~900 tokens)
3. `apps/frontend/tailwind.config.ts` - Design tokens: accent (#0e7490), page.bg (#f8fafc), surface (#ffffff), txt/txt.sub/txt.muted, hairline, border-radius (sm: 0.5rem, default: 0.75rem, lg: 1rem), shadows (card, pop). (~400 tokens)
4. `apps/frontend/src/lib/auth/session.ts` - `StoredSession` type: {jwt, refresh_token, jti, scope, identity_id, phone}. (~350 tokens)
5. `apps/frontend/src/app/layout.tsx` - Root layout, minimal (html > body > children). No AuthProvider yet. (~100 tokens)
6. `apps/frontend/package.json` - No UI library. Only Next.js 16.3, React 19, Tailwind 3.4, Vitest, Testing Library. (~180 tokens)

## Do NOT read

- Backend code, auth wizard, OTP state, other modules
- `apps/frontend/src/app/(patient)/patient/page.tsx`, `(partner)/partner/page.tsx`, `(operator)/operator/page.tsx` - these will be replaced by scaffold pages inside `(dashboard)/`
- `docs/archive/` - PRD supersedes it

## Baseline verify (must pass before the first edit)

- `npm run build` in `apps/frontend/` - must succeed (confirmed: 7 routes, 0 errors)
- `npm run test:unit:frontend` in project root - must pass

## Done-verify (acceptance criteria to commands)

- `npm run build` in `apps/frontend/` - no errors
- `npm run test:unit:frontend` in project root - all tests pass
- Manual: login, navigate to `/patient` - see sidebar + topbar with correct nav items
- Manual: verify sidebar collapses on narrow viewport
- Manual: verify "Soon" badges on non-Home nav items
- Manual: verify logout clears session and redirects to `/`

## Handoff notes

- Route restructuring needed: current routes are `(patient)/patient/page.tsx`, `(partner)/partner/page.tsx`, `(operator)/operator/page.tsx`. These need to move inside `(dashboard)/` or be wrapped. The `(dashboard)` layout group wraps all role routes.
- No `AuthProvider` exists yet - the `(dashboard)/layout.tsx` must introduce it (wrapping children).
- All styling must use the existing Tailwind tokens from `tailwind.config.ts`. No inline styles.
- Use existing icon components from `icons.tsx` - do not create new icons or install icon libraries.
- The "Soon" badge is a visual indicator (not functional navigation). Use a small pill/badge styled with Tailwind.
