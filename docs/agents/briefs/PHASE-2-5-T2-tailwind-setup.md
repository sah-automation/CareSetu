# Brief - T2 Frontend - Tailwind CSS setup

**Ticket:** #148 · **Parent:** #146 Phase 2.5 · **Refreshed:** 2026-08-17
**Reading surface:** ~3K tokens (budget 10K) - well within budget

## Scope

Install and configure Tailwind CSS alongside the existing CSS Modules approach. Create a global `globals.css` with Tailwind directives and map existing design tokens (colors, radii, shadows) from `otpShared.module.css` into `tailwind.config.ts` so dashboard components can use Tailwind utilities while the auth wizard retains its CSS Modules styling.

Acceptance criteria (verbatim):

- Tailwind CSS installed as dev dependency
- `tailwind.config.ts` created with content paths pointing to `src/` for class scanning
- Design tokens from `otpShared.module.css` mapped to Tailwind theme (accent: #0e7490, success: #10b981, danger: #b91c1c, radii, shadows)
- `src/app/globals.css` created with `@tailwind base/components/utilities` directives
- Root layout imports `globals.css`
- `npm run build` succeeds (Tailwind compiles without errors)
- Existing auth wizard CSS Modules styling unaffected

## Read-list (in order)

1. `apps/frontend/package.json` - current dependencies, check Tailwind is not already installed, note the package manager (npm workspaces) (~0.5K tokens)
2. `src/components/auth/otp/otpShared.module.css` (241 lines) - the design tokens to map: CSS custom properties for colors (--accent, --success, --danger), border-radius values, shadow values (~2K tokens)
3. `src/app/layout.tsx` (15 lines) - the root layout where `globals.css` must be imported; currently bare HTML shell (~0.2K tokens)

## Do NOT read

- Backend code, auth wizard component logic (PatientAuthWizard.tsx), OTP state machine, icons, PRD, roadmap.

## Baseline verify (must pass before the first edit)

- `npm run build` (frontend builds without Tailwind)

## Done-verify (acceptance criteria → commands)

- `npm run build` - Tailwind compiles without errors
- Visual check: auth wizard styling unchanged (CSS Modules still work alongside Tailwind)
- `tailwind.config.ts` exists with correct content paths and theme extensions

## Handoff notes

- The root `layout.tsx` is a bare `<html><body>{children}</body></html>` with no imports. Add `import './globals.css'` as the first import.
- The auth wizard uses CSS Modules exclusively (`otpShared.module.css`); Tailwind must not interfere. The `@tailwind base` reset is the main risk - test that the wizard still renders correctly after adding it.
- Keep Tailwind as a dev dependency (build-time only, zero runtime cost).
- Design tokens from `otpShared.module.css`: `--accent: #0e7490` (primary teal), `--success: #10b981`, `--danger: #b91c1c`, `--radius-sm/md/lg`, `--shadow-sm/md`. Map these into `theme.extend.colors` and `theme.extend.borderRadius`/`theme.extend.boxShadow`.
