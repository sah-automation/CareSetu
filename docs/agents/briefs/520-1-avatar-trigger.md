# Brief - 521 Patient avatar trigger (desktop), staff unchanged

**Ticket:** #521 · **Parent:** #520 · **Refreshed:** 2026-09-23
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

As a patient, the desktop top-right account trigger becomes a professional circular avatar instead of the last two phone digits: photo when set, else the first letter of the saved name (Devanagari-safe), else a person icon. No name label sits next to the circle, and the full phone number stays hidden until the menu is opened. Doctor/partner/operator roles keep the existing phone-digit trigger and dropdown verbatim. The photo branch is dormant until a later photo-upload seam.

Acceptance criteria:

- Patient trigger renders the shared avatar precedence chain: `photo_ref` → first letter of name → person icon
- No name label beside the circle; full phone appears only inside the opened menu
- Staff-role trigger and dropdown unchanged, covered by a regression test
- Initial renders correctly in Devanagari
- Existing tests/e2e assertions that pin the old phone digits are updated
- `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` green

## Read-list (in order)

1. Spec #520 - Implementation Decisions ("One shared avatar primitive", "Account menu becomes role-aware", "Masked/full phone display") + stories 1-6 (should already be in context if the implementer holds the ticket; re-fetch if not) (~1K tokens)
2. `docs/design/ui-blueprint.md` §2.6 account-menu - the consolidated account menu conventions this trigger belongs to (~0.5K)
3. The `AccountMenu` account-cluster component - the trigger markup being swapped (circle button, role-aware branch, stale-session `Subject #id` degrade) and how it reads the session identity (`useAuth().user`: `id`, `phone`, `roles`) (~2K)
4. `AccountMenu.test.tsx` - prior-art test seams: real `AuthProvider` + `vi.spyOn(fetch)` `/v1/me` JSON, localStorage session fixture, Radix popper stubs (ResizeObserver/PointerEvent); update digit assertions here (~2K)
5. The optional profile read seam (`useOptionalProfile`) - where name/`photo_ref` come from inside shared chrome; surfaces `StoredPatientProfile` with `name`, `photo_ref` field names (~1K)
6. e2e account-menu digit assertions in `tests/e2e/patient-journey.spec.ts` and `tests/e2e/auth-loop.spec.ts` - what they pin and must be updated to (~0.5K)
7. Icon set (lucide-react) - the person icon available for the fallback branch; the existing `Settings`/`User` icon usage for naming convention

## Do NOT read

- Profile wizard, Profile & Settings page, draft-buffer internals beyond the `name`/`photo_ref` fields
- Nav config, `splitMobileTabs`, BottomTabs / More sheet
- Desktop dropdown enrichment internals (ticket 526 work)
- Backend code, `docs/archive/`

## Baseline verify (must pass before the first edit)

- `npm run typecheck`
- `npm run lint`
- `npm run test:unit:frontend` - note: 1 pre-existing failure in the doctor case pre-summary test (`src/app/(doctor)/doctor/cases/[caseId]/page.test.tsx`) is present on the clean tree at HEAD; unrelated to this ticket

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` with the account-menu suite green
- `npm run lint`, `npm run typecheck`
- e2e account-menu assertions updated (review, do not need to run the full e2e suite if infra is unavailable)

## Handoff notes

- Prior conventions: `docs/agents/briefs/PHASE-2-6-T08-account-menu-conventions.md` (origin of phone + role badge + switch-role + logout cluster).
- The avatar is a shared primitive: ticket 525 (More account card) and 526 (dropdown identity header) consume it. Design it as one component used by all three, not inline markup.
- Devi from em-dashes and non-ascii punctuation in any copy you add (git hook `no-em-dash gate` fails otherwise).
