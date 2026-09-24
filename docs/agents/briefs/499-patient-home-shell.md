# Brief - 499 Patient home shell: greeting strip, responsive two-column layout, remove demos/meter/nudges

**Ticket:** #499 · **Parent:** #498 · **Refreshed:** 2026-09-21
**Reading surface:** ~9K tokens (budget 10K) - at budget

## Scope

A returning patient lands on the reworked dashboard composed around the finalized PROTO-2.7 shell (binding visual spec): a full-width bilingual greeting strip at the top that greets the saved first name in the current language (generic fallback when no name is saved), then a two-column feed on desktop >=1024px (main cards column + a 300px sticky right rail started as an empty styled aside) that stacks into the same single column below 1024px with min-width:0 children so the page never scrolls horizontally from 320-1440px. The light AppShell content column is widened to support the two-column layout. The profile-completion meter, the nudge stack, `ProfileGateDemo` and `LabBookingConsentDemo` leave the home (the components stay defined; `ProfileGate` keeps gating the care-action moments). New home strings land under a `patientHome.*` dictionary surface in en + hi with parity compile-checked and enforced by the dictionary parity test.

- [ ] Greeting shows the saved first name in the current language and falls back to a generic greeting when no name is saved.
- [ ] Home renders the greeting strip above the feed; two-column with sticky right rail above 1024px, single column in the same reading order below 1024px.
- [ ] No meter, nudge stack, `ProfileGateDemo` or `LabBookingConsentDemo` on the home.
- [ ] No page-level horizontal overflow at 320-1440px (children keep min-width:0).
- [ ] `channels.test.tsx` patient case asserts a stable testid-based heading (the literal "Welcome, Patient" is gone); the e2e specs are updated to the same stable selector.
- [ ] Home `page.test.tsx` rewritten to the single composed seam: greets in en and hi, no meter/demo, baseline layout holds.
- [ ] Blueprint patient IA (section 5.1/5.2) amended to describe the reworked home and the demoted profile-completion placement.
- [ ] Dictionary parity test passes with the new `patientHome.*` keys in both locales.

## Read-list (in order)

1. `prototype/PLAN.md` PROTO-PHASE-2.7 entry - the decision log this rework encodes (~0.4K).
2. `prototype/phase-2-6/shell-light.html` - binding spec: greeting strip markup (lines ~196-215), `.home-grid` layout with the 2-col/1-col + rail comment (~217-220, ~504-514), rail aside (~457). CSS lives in the shared prototype stylesheet - grep `.home-grid`, `.home-rail` there. Note the min-width:0 regression rules (~1.5K).
3. `docs/design/ui-blueprint.md` - section 5 patient light shell: 5.1 bottom-tab note, 5.2 Home IA (current vertical stack this shovels over), 5.9 profile-completion placement (~1K).
4. The `AppShell` light branch and the shared `Topbar` light density - where the patient content column sits and why it needs widening for a 2-col feed; `PageHeader` if reused (~1.2K).
5. The `ProfileContext` value surface (`draft`, `savedProfile`, `updateDraft`) and profile state - `name`/`basicsComplete` for the greeting source and fallback (~0.8K).
6. `dictionaries.ts` - `Dictionary = typeof en`, the `home.*` and `doctor.welcome` interpolated-function precedent, the `LangContext` `useLang()`/`STRINGS[lang]` access pattern; read only those slices (~1K).
7. `channels.test.tsx` - the patient heading assertion table that must move to a testid (~0.8K).
8. Home `page.test.tsx` - the existing meter/nudge seam being rewritten to the composed seam (~1K).
9. e2e specs under `tests/e2e/` - grep the literals "Welcome, Patient" and `consent-demo` and update to the stable selector (~0.6K).

## Do NOT read

- Other prototype views, `docs/archive/`, backend modules, `docs/adr/*` (no auth/session work), the Find Care / record / consent pages (later tickets), unrelated dictionary sections.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - confirmed green 2026-09-21 (1119/1119).
- `npm run typecheck:frontend` - confirmed green 2026-09-21.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend` - channels testid heading, home composed-seam greeting en/hi + no-meter/demo, dictionary parity suite all green.
- `npm run typecheck:frontend` - clean (compile-time bilingual parity).
- `npm run lint` - clean.

## Handoff notes

- i18n is typed-per-locale objects, NOT a framework: components call `useLang()` and index `STRINGS[lang].section`. No `t()`. Parameterized strings are functions (`resendIn: (s) => ...`); the new `patientHome.welcome(name)` must exist in both locales with equal arity, and `dictionaries.test.ts` enforces it.
- The `doctor.welcome` function is defined but unused - that is the approved precedent for the patient greeting.
- The greeting reads the profile `name` (first token) via the profile context; fall back to a generic non-interpolated form when absent.
- Keep `AppShell`/`Topbar` structural changes confined to the light (patient) branch; the full density shell is out of scope.
- The meter/nudge components are NOT deleted - they move off the home and remain importable for the profile surface. Only the home stops composing them.
- The prototype regression rule to preserve: single-column `minmax(0,1fr)`, children `min-width:0`, so intrinsic widths never widen the page at 320px and up.
