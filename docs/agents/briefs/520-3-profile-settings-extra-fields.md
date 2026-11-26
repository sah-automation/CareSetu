# Brief - 523 Profile & Settings: language, emergency contact, area

**Ticket:** #523 · **Parent:** #520 · **Refreshed:** 2026-09-23
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

The Profile & Settings page gains its remaining §5.8 sections: language preference (mirroring the existing header language toggle's profile field), emergency contact, and area - all editable, pre-filled, and saved through the same gated profile-finish path with bilingual success/error notices.

Acceptance criteria:

- Language preference, emergency contact, and area sections render and pre-fill
- Edits save through the existing finish path; bilingual notice on success/error
- Basics gate still blocks incomplete saves
- New strings in both locales; axe scan clean
- Page tests extended; `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` green

## Read-list (in order)

1. The Profile & Settings page from #522 - the §5.8 page structure to extend; its save plumbing to reuse (~2K tokens)
2. Profile draft/state helpers - the draft fields for `preferred_language`/`language`, `emergency_contact`/`emergencyContact`, `area`, their null-optional payload mapping and completeness contribution (`areaComplete`) (~0.7K)
3. i18n dictionary structure (`profile.language`, `profile.area`, emergency-contact keys) + the EN/HI parity test (~0.5K)
4. Header language toggle relationship: the client language store (`LangContext`) vs the profile `preferred_language` field are separate stores; the page field writes the profile field, per spec story 24 (~0.3K)
5. UI blueprint §5.8 for the section layout (~0.5K)

## Do NOT read

- Account menu, nav config, More sheet (tickets 521/524/525/526)
- Profile-completion wizard internals beyond shared helpers
- Backend code, `docs/archive/`

## Baseline verify (must pass before the first edit)

- `npm run typecheck`
- `npm run lint`
- `npm run test:unit:frontend` - note: 1 pre-existing failure in the doctor case pre-summary test at HEAD, unrelated to this ticket

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` with the page test suite green
- `npm run lint`, `npm run typecheck`

## Handoff notes

- #522 must be merged first: its page, save plumbing, and test patterns are the base this slice extends.
- The page's save path is gated on complete basics by the shared gate - this ticket only slots new fields into the existing draft/save flow.
- Avoid em-dashes and non-ascii punctuation in copy (git hook `no-em-dash gate`).
