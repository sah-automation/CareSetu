# Brief - 542 Doctor profile backend (private projection)

**Ticket:** #542 · **Parent:** #529 · **Refreshed:** 2026-09-24
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

A doctor gets a complete, private profile projection of their own single partner record - photo, name, specialty, verified state, practice details, languages, experience, about, consultation fee, availability, credential status and notifications - via private GET/PUT guarded to active doctors (US-26, US-29). The public directory projection keeps reading the same partner record (no drift; the public side stays read-only to the doctor in this batch - a preview link, not an editor). The consultation fee keeps its existing patch route (unchanged contract); the profile GET/PUT reads/writes the same fee field so the editor can move into the profile page. New fields (photo, practice details, experience, languages, about, availability, notification prefs) extend the partner record, with the photo stored as a key in the `profile-media` doctor prefix.

AC:

- [ ] Private GET returns the full partner projection (photo, name, specialty, verified state, practice, languages, experience, about, fee, availability, credentials status, notifications) for an active doctor; guarded to active doctors
- [ ] Private PUT updates the editable fields (photo, practice details, experience, languages, about, availability, notification prefs); the consultation fee remains editable through its existing patch route against the same record
- [ ] The public directory projection still reads the same record and is unchanged in contract
- [ ] Facade + route tests (prior art: provider-profile and consultation-fee route tests); `npm run test:unit:backend`, `npm run lint`, `npm run typecheck` green

## Read-list (in order)

1. The partner record + schema: `modules/partner/schema/models.py` (`partner_profiles` fields incl. `consultation_fee_paise`, credential/verification status tables) - the source both projections read (~1K).
2. The partner facade: profile-field accessors + `update_consultation_fee` in `modules/partner/facade.py` (doctor-only + Active-only gate) - the facade patterns for the new GET/PUT (~1.2K).
3. The public projection contract: `get_provider_profile` in `modules/partner/facade.py`/`directory_facade.py` and the read model in `directory_models.py` (`ProviderProfileView`) - the unchanged public shape and the verified derivation (~0.8K).
4. The consultation-fee patch route in `modules/partner/adapters/routes.py` (PATCH with `ConsultationFeeRequest(fee_paise)`) - the unchanged contract the profile fee field reads/writes (~0.5K).
5. The profile-media port from #532 (doctor prefix `doctor/<id>/...`) - the photo key read/write seam (~0.3K).
6. The active-doctor guard pattern (`_require_doctor` style) as registered by #530 for the doctor console seam (~0.2K).
7. Test prior art: `test_consultation_fee_route.py`, `test_provider_profile_route.py`, `test_directory_facade.py` (~1.2K).
8. `docs/adr/0011` + `0012` - credential-expiry/verified derivation and the one-entry-per-partner rules the private projection reflects (~0.5K).

## Do NOT read

- Frontend code, consent/health internals, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - confirmed green 2026-09-24 (2338 passed).
- `npm run lint`, `npm run typecheck` - confirmed green 2026-09-24.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` - private GET/PUT, active-doctor guard, fee-field-shared, and public-projection-unchanged tests green.
- `npm run lint`, `npm run typecheck` - clean.

## Handoff notes

- Requires #532 landed (doctor photo rides the profile-media doctor prefix).
- New partner fields (experience, languages, about, availability, notification prefs, photo key) extend the partner record via an additive migration; the consultation fee stays in the existing `consultation_fee_paise` column - do not add a second fee surface.
- The public `ProviderProfileView` and `search_directory` contract must be byte-unchanged; the private projection is a superset read of the same row (respect ADR-0011: nothing private reaches the public read model).
- No em-dashes anywhere (lint-gated); use simple dashes.
