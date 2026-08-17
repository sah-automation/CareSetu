# Brief - 149 T4: Frontend - Marketing homepage

**Ticket:** #149 . **Parent:** #146 . **Refreshed:** 2026-08-17
**Reading surface:** ~3K tokens (budget 10K) - within budget

## Scope

Replace the current root page (`/`) redirect to `/patient` with a public marketing landing page. Server-rendered for fast load and SEO. Contains: CareSetu branding/hero, tagline about voice-based clinical records, 3 feature cards (Longitudinal Records, Consent-Gated Sharing, AI Pre-Summary), and a "Get Started" CTA linking to `/login`.

### Acceptance criteria

- [ ] `/` renders a marketing homepage instead of redirecting to `/patient`
- [ ] Page is a server component (no "use client" directive)
- [ ] Hero section with CareSetu brand name and product tagline
- [ ] 3 feature cards matching PRD features (FEAT-002, FEAT-002/020, FEAT-007)
- [ ] "Get Started" / "Login" CTA button links to `/login`
- [ ] Page uses Tailwind CSS for styling (from Ticket 2 setup, fallback to inline styles if not available)
- [ ] `npm run build` succeeds
- [ ] Page loads without JavaScript (progressive enhancement)

## Read-list (in order)

1. `apps/frontend/src/app/page.tsx` - current redirect implementation, will be replaced (~0.1K)
2. `CONTEXT.md` glossary section - product terms: pre-summary, transcription confidence, consent for accurate feature card descriptions (~0.5K)
3. `apps/frontend/package.json` - verify dependencies, check if Tailwind is installed (~0.1K)
4. `apps/frontend/src/app/layout.tsx` - root layout structure for context (~0.2K)

## Do NOT read

- Backend code, auth components, dashboard components, other modules
- `docs/archive/` directory
- Test files (until implementation is complete)

## Baseline verify (must pass before the first edit)

- `npm run build` in `apps/frontend/` (currently fails because next is not installed - need to install dependencies first)

## Done-verify (acceptance criteria → commands)

- `npm run build` succeeds
- Visit `/` in browser, see marketing homepage with:
  - CareSetu brand name and tagline
  - 3 feature cards
  - "Get Started" button linking to `/login`
- Page renders without JavaScript (server component)

## Handoff notes

- Ticket 2 (Tailwind CSS setup) may not be merged yet. If Tailwind is not available, use inline styles or CSS modules as fallback.
- The existing `PatientAuthWizard` component is not in scope for this ticket.
- This is a purely frontend change - no backend modifications required.
