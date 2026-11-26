# Brief - 549 Patient profile Health background zone + consent interstitial

**Ticket:** #549 · **Parent:** #529 · **Refreshed:** 2026-09-24
**Reading surface:** ~3.5K tokens (budget 10K) - within budget

## Scope

The patient profile's Health background zone goes live inside the three-zone page: a snapshot form (blood group, conditions, allergies, current medications, immunizations, family history) and a height/weight time-series entry list, with the first-save consent confirmation that this PHI becomes visible to the patient's verified-relationship doctors (US-21, US-22, US-23). The confirmation is required once; later edits save without it. Denied/missing data renders empty states. All copy EN/HI; desktop and mobile.

AC:

- [ ] Health background zone renders the snapshot form and the height/weight series (append + list) bound to the snapshot + metrics APIs
- [ ] First save shows and requires the consent confirmation; later edits do not re-prompt and persist the ack
- [ ] Empty/loading/error states for the zone; EN/HI parity
- [ ] Component tests + `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` green

## Read-list (in order)

1. The three-zone patient profile page from #548 (the Identity/Settings zone seam and where the Health background placeholder sits) - the structure this zone slots into (~1K).
2. The health-background snapshot + metrics API shapes from #534/#535 (GET/PUT snapshot endpoint + first-save acknowledgement flag; append/list metrics) - the wire contracts the form and series bind to (~0.5K).
3. An existing consent-confirmation interstitial precedent - the pick-consent sheet (`components/consent/ConsentSheet.tsx`) or the pick-doctor consent step copy - for the first-save confirmation wording/structure (~0.5K).
4. The i18n `profile`/`patientHome` dictionary blocks + parity test for the new zone copy (~0.5K).
5. Test prior art: the patient profile `page.test.tsx` and the empty/loading/error-state patterns (~0.8K).

## Do NOT read

- Backend internals beyond the #534/#535 API contracts, doctor console pages, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - confirmed green 2026-09-24 (1288 passed, 89 files).
- `npm run lint`, `npm run typecheck` - confirmed green 2026-09-24.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend` - health-background zone tests (first-save confirmation required once, series append/list, empty states) + parity green.
- `npm run typecheck` - clean.

## Handoff notes

- Requires #534 + #535 + #548 landed (APIs + the zone shell). The first-save acknowledgement is sent once with the snapshot PUT; later edits omit it, matching the backend ack contract from #534.
- Missing/denied data on read renders empty/loading states - the backend never returns the snapshot to a doctor through this surface (that is #540), and the client must not fabricate it.
- No em-dashes anywhere (lint-gated); use simple dashes.
