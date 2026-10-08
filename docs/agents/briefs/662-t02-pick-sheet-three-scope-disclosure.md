# Brief - 02 Pick consent sheet discloses the three scopes in both languages

**Ticket:** #664 · **Parent:** #662 · **Refreshed:** 2026-10-08
**Reading surface:** ~4.5K tokens (budget 10K) - within budget

## Scope

The pick consent sheet discloses all three granted record scopes before the patient taps Allow: the consent-scope sentence in both supported languages names consultations, prescriptions, and health background. The flow stays a single Allow action with no extra consent screens, and dictionary key parity between EN and HI stays intact.

Acceptance criteria:

- [ ] The pick consent sheet's scope sentence in English names consultations, prescriptions, and health background
- [ ] The same sentence in Hindi names all three scopes
- [ ] Component tests assert the three-scope disclosure in both languages; the bilingual key-parity test passes
- [ ] The sheet's Allow / Not-now / error anatomy is unchanged (single Allow action preserved)
- [ ] `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` pass

## Read-list (in order)

1. Spec #662 §Solution "Consent-at-pick widening" - the Implementation Decisions bullet on disclosure copy and user stories 5-7 (~1K)
2. `PickConsentSheet` component (apps/frontend/src/components/pick/PickConsentSheet.tsx) - how the sheet renders the `pick.consentScope` dictionary key (title/scope line) and the Allow anatomy (~1.5K)
3. The `pick` blocks of both language dictionaries (apps/frontend/src/lib/i18n/dictionaries.ts) - the EN and HI `consentScope` sentences; keep them aligned in structure (~1K)
4. `PickConsentSheet.test.tsx` - the existing dual-scope disclosure assertions (EN and HI) to widen, plus anatomy tests to preserve (~1K)
5. `dictionaries.test.ts` - the recursive EN/HI key parity gate (run, do not modify) (~0.3K)

## Do NOT read

- Backend intake/consent code (ticket #663 owns the grant widening)
- Pick page test beyond what the sheet test covers
- Unrelated dictionary sections; `docs/archive/`

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - 2148 passed (2026-10-08)
- `npm run lint` - passed
- `npm run typecheck` - passed

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` - sheet three-scope assertions EN+HI green, key parity green, anatomy tests unchanged
- `npm run lint`, `npm run typecheck`

## Handoff notes

- Copy must say the doctor "may consult" the three record areas alongside the symptoms summary (spec story 5) - do not add new consent screens (story 7).
- No new dictionary keys are needed if the sentence is edited in place; if a key IS added/renamed, it must be added to both language blocks or the parity test fails.
- Ticket #663 (backend widen) is independent; landing the copy first briefly claims a grant the backend widens separately - either order keeps CI green.
