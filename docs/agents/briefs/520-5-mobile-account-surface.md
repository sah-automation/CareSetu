# Brief - 525 Mobile account surface: More account card + Log out, hide phone trigger

**Ticket:** #525 · **Parent:** #520 · **Refreshed:** 2026-09-23
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

On phones, a patient finds their account in exactly one place: the More sheet. The top-right circle is hidden for the patient role below the `lg` breakpoint; the More sheet opens with an account card at the top (avatar, name or masked phone, full E.164 phone, Profile & Settings) that navigates to the page and closes the sheet, plus a red Log out row that ends the session, clears stored credentials and the presence-hint cookie, and returns home. Other roles keep their existing trigger visibility and More behavior.

Acceptance criteria:

- Patient trigger hidden below `lg`; staff roles unaffected
- More sheet shows the account card first; tapping it opens Profile & Settings and closes the sheet
- Card shows avatar, name or masked phone, full E.164 phone
- Red Log out row ends session, clears stored credentials + presence hint, redirects home
- Sheet closes on navigation and on Log out
- 44px targets, visible focus, correct labels; `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` green

## Read-list (in order)

1. Spec #520 - "Mobile placement" and "Logout stays client-side" decisions + stories 16-21, 30 (re-fetch if not held) (~1K tokens)
2. The shared avatar primitive from #521 - the component the account card embeds, and its props (name, `photo_ref`) (~0.3K)
3. The bottom tab bar + More sheet components - the sheet body structure, existing overflow rows, testids, the close-on-navigate pattern (~1.5K)
4. The account trigger component's responsive behavior - where the top-right circle is rendered, how to hide it below `lg` for the patient role only (~0.8K)
5. Client-side logout/session clearing - the stored session and presence-hint cookie cleanup + home redirect (ADR-0005/0007 invariants: split-origin transport untouched, no new logout endpoint) (~0.8K)
6. Masked-phone display format from spec (`+91 XXXXXX1234`); profile name/`photo_ref` seam (~0.5K)
7. Optional: the stale-session `Subject #id` fallback convention from the account menu (share it so the card never crashes) (~0.3K)

## Do NOT read

- Desktop dropdown enrichment internals (Ticket 526)
- Profile & Settings form internals (Ticket 522)
- Backend code, `docs/archive/`

## Baseline verify (must pass before the first edit)

- `npm run typecheck`
- `npm run lint`
- `npm run test:unit:frontend` - note: 1 pre-existing failure in the doctor case pre-summary test at HEAD, unrelated to this ticket

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` with shell/account suite green
- `npm run lint`, `npm run typecheck`

## Handoff notes

- 44px touch targets apply to the Log out row and the account card.
- The account card navigates via the existing router to `/patient/profile`; no new routing logic.
- Keep log out behavior identical to the existing client-side path - do not add revocation API calls.
- Hidden trigger means the avatar used by the card must not rely on the top-right button being present.
- Avoid em-dashes and non-ascii punctuation in copy (git hook `no-em-dash gate`).
