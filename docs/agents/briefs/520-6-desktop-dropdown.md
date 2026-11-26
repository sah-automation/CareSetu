# Brief - 526 Desktop dropdown identity header + profile CTA + Log out

**Ticket:** #526 · **Parent:** #520 · **Refreshed:** 2026-09-23
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

The patient desktop dropdown becomes a real account menu: an identity header (avatar, name or masked phone like `+91 XXXXXX1234`, full E.164 phone), a live Profile & Settings link, a "Complete your profile" call-to-action shown only while basics (name, age, gender) are missing that vanishes once saved, role switching for multi-role accounts with no clutter for single-role, and a red dictionary-driven "Log out" in English and Hindi. Stale/degraded sessions fall back to a stable `Subject #id` identity without crashing. Hardcoded menu strings become i18n keys.

Acceptance criteria:

- Identity header shows avatar, name or masked phone, full E.164
- Live Profile & Settings entry opens the page
- "Complete your profile" CTA only while basics missing; disappears after basics save; navigates to the page
- Role switching preserved for multi-role accounts; single-role menu stays uncluttered
- Red "Log out" dictionary-driven in both locales (no hardcoded strings)
- Stale session renders `Subject #id` fallback and Log out still works
- Axe scan clean; `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` green

## Read-list (in order)

1. Spec #520 - Implementation Decisions (role-aware menu, masked phone, CTA gating, i18n/vocabulary) + stories 5-16, 28-29 (re-fetch if not held) (~1.5K tokens)
2. `docs/design/ui-blueprint.md` §2.6 account-menu conventions (~0.5K)
3. The account menu component - dropdown structure (identity label row, role-switch items, Logout row), the stale-session `Subject #id` degrade, and how to branch it by selected role; it already reads `useAuth()` for `user`/`selectedRole`/`switchRole`/`logout` (~2K)
4. The shared avatar primitive from #521 and how to consume its precedence chain (~0.3K)
5. Profile context - the basics-complete signal (name, age, gender) that gates the CTA; the optional profile read seam for shared chrome (~1K)
6. i18n dictionary structure (`profile`, `auth`, `nav` surface groups) + the EN/HI parity test; move the currently hardcoded Logout/role strings into dictionaries (~1K)
7. `AccountMenu.test.tsx` prior art: real `AuthProvider` + `/v1/me` fetch mock, localStorage session fixture, stale-session and keyboard/aria suites; extend for the new items (~2K)

## Do NOT read

- More sheet / account card (Ticket 525)
- Profile & Settings form internals (Ticket 522)
- Backend code, `docs/archive/`

## Baseline verify (must pass before the first edit)

- `npm run typecheck`
- `npm run lint`
- `npm run test:unit:frontend` - note: 1 pre-existing failure in the doctor case pre-summary test at HEAD, unrelated to this ticket

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` with the account-menu suite green
- `npm run lint`, `npm run typecheck`

## Handoff notes

- Vocabulary lock from spec: UI copy uses "Profile & Settings" and "Log out"; never "My Account". Model language keeps `identity` and `patient profile`.
- The CTA navigates to `/patient/profile`; it is gated on absent/incomplete basics and must disappear once those save.
- Keep the staff-role branch of this menu byte-identical to today; only the patient branch changes.
- E.164 comes from the session payload server-side; the client only formats the masked display string.
- Avoid em-dashes and non-ascii punctuation in copy (git hook `no-em-dash gate`).
