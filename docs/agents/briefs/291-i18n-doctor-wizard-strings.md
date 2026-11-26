# Brief - 291 Move doctor landing + wizard strings into i18n dictionaries

**Ticket:** #291 · **Parent:** phase5-frontend-review-fixes.md Fix 3 · **Refreshed:** 2026-09-03
**Reading surface:** ~10K tokens (budget 10K) - at budget

## Scope

Move all hardcoded English strings in the doctor landing page and provider registration wizard into the bilingual `STRINGS` dictionary under new `doctor` and existing `staffAuth.register` sections, with both `en` and `hi` variants.

- [ ] New `doctor` keys added to dictionaries (both `en` and `hi`)
- [ ] Wizard error/submit strings added to dictionaries
- [ ] Doctor page renders from dictionary lookups (not hardcoded English)
- [ ] Wizard uses dictionary lookups for all surfaced strings
- [ ] Dictionary shape tests stay green (compile-time bilingual parity enforced by TypeScript)

## Read-list (in order)

1. `apps/frontend/src/lib/i18n/dictionaries.ts` - Full structure: `STRINGS: Record<Lang, Dictionary>`, `Dictionary = typeof en`. The `en` object has sections: `auth`, `staffAuth`, `home`, `consent`, `profile`, `nav`, `record`, `consentLog`. No `doctor` section exists yet. Lines 75-289: `staffAuth` section with `login`, `pending`, `rejected`, `picker`, `register` sub-sections. (~1100 lines, ~15K tokens - read selectively: focus on the Dictionary type structure and staffAuth.register section)
2. `apps/frontend/src/app/(doctor)/doctor/page.tsx` - All strings hardcoded: "Welcome, ${displayName}", "Your doctor workspace is active.", "Status", "Your profile is active and verified...", "Next Steps", 3 bullet items. (~43 lines, ~800 tokens)
3. `apps/frontend/src/components/auth/staff/ProviderRegisterWizard.tsx` - Search for hardcoded English strings that bypass the dictionary. Focus on submit/error copy. (~950 lines - grep for hardcoded strings, don't read whole file)
4. `apps/frontend/src/lib/i18n/dictionaries.test.ts` - existing dictionary shape tests. (~200 lines, ~3K tokens)
5. `apps/frontend/src/lib/i18n/LangContext.test.tsx` - language context tests.

## Do NOT read

- operator modules, partner API, audit modules, auth modules beyond what the wizard imports
- Backend modules

## Baseline verify (must pass before the first edit)

- `npm run test -w @caresetu/frontend`
- `npm run typecheck -w @caresetu/frontend` (ignore `.next/dev/types/` errors)
- `npm run lint`

## Done-verify (acceptance criteria -> commands)

- `npm run test -w @caresetu/frontend` - dictionary shape tests green, doctor page renders from dict
- `npm run typecheck -w @caresetu/frontend` - no new type errors (compile-time bilingual parity enforced)
- `npm run lint` - clean

## Handoff notes

- The i18n mechanism is NOT a framework - it's typed per-locale objects. Components call `useLang()`, then index directly into `STRINGS[lang].section`. No `t()` function - direct property access.
- For parameterized strings, dictionary entries are functions: `resendIn: (s: number) => \`Resend in ${s}s\``.
- Both `en` and `hi` variants must be added together - TypeScript enforces compile-time bilingual parity via the `Dictionary = typeof en` type.
- The `doctor` section is new - add it alongside existing sections. Follow the naming pattern of existing sections (`auth`, `staffAuth`, etc.).
- For the wizard, check which strings are already in `staffAuth.register` and which are missing.
