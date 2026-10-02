# Brief - 602 Own the closed vocabularies for specialty, languages and consulting days

**Ticket:** #602 · **Parent:** #599 · **Refreshed:** 2026-09-30
**Reading surface:** ~6.9K tokens (budget 10K) - within budget

## Scope

Specialty stops being a four-value internal enum nobody writes, and the two free-text fields stop being free text. This ticket owns the closed vocabularies in the domain layer: a roughly twenty-value specialty list covering the specialties that account for most small-town practice, a scheduled-languages-of-India list, and the seven consulting days - each with the validation that refuses a value outside its list.

Acceptance criteria (from ticket):

- [ ] The specialty closed list holds roughly twenty values, doctors-only, and never free-form - the previous four remain members so no existing meaning is lost.
- [ ] A language list over the scheduled languages of India and a seven-day consulting-day list exist as domain-owned vocabularies.
- [ ] One validation entry point per vocabulary rejects a value that is not a member, and a multi-valued selection is validated member by member.
- [ ] A unit suite pins membership for a known-good value, rejection of an unknown value, and rejection of a malformed value for each of the three vocabularies.
- [ ] The glossary entry for specialty no longer implies a single value, and the avoided synonyms consultation type and expertise are unchanged.

## Read-list (in order)

1. `CONTEXT.md` - the build-session protocol, the cross-reference rule and the "Do NOT read" section, then the "Provider directory & credential validity" glossary section, which carries the canonical **specialty**, **directory entry**, **verified** and **wider-area fallback** entries. The fifth acceptance criterion is a surgical edit to the **specialty** entry: drop the single-value implication, keep the doctors-only and never-free-form clauses, and leave the `_Avoid_` list (`consultation type`, `expertise`) byte-for-byte as it is. (~1.4K tokens)
2. `docs/prd/project-prd.md` §4.2.1, Feature 4.2.1 `FEAT-004` Provider Directory & Search. The feature the specialty filter serves, its business rules, and the `directory_search` telemetry event whose `filters` payload the closed list has to stay renderable into. (~0.6K tokens)
3. `docs/standards/coding-standards.md` §2 Module Structure, §3 Typing & Naming, §6 Tests, §8 Readability & Debuggability. The rule this ticket exists to satisfy: a closed vocabulary is domain language, not a model constant - it lives in the domain, the schema mirrors it, and pre-conditions are validated in the domain core, never in the router. (~0.7K tokens)
4. The partner domain credentials module - `Specialty` with its four current values and its "mirrors the directory-index CHECK constraint, doctors only, never free-form" docstring, plus its three neighbours `CredentialType`, `ALLOWED_CREDENTIAL_TYPES_BY_PARTNER` and `CredentialInvalidatedReason`. These are the house style for a closed vocabulary: a `StrEnum`, a docstring naming the constraint it mirrors, and a `#:` comment on anything a caller should import by name. (~0.75K tokens)
5. `evaluate_submission`, `PrefilterOutcome`, `PrefilterReason` and the private `_credential_type` helper in the Step-1 pre-filter, plus the named `PartnerError` subclasses such as `InvalidQueueSortError` and `InvalidQueueStatusError`. The two precedents for a pure domain rejection: a typed outcome value for a decision with a small closed set of failure reasons, and a named `PartnerError` subclass for a single validation failure. Pick the shape that matches each vocabulary rather than inventing a third. (~1.1K tokens)
6. `test_specialty_is_a_closed_strenum`, `test_specialty_matches_directory_index_check` and the `_constraint_text` introspection helper in the existing directory-schema unit suite. This is the suite that goes red the moment the list grows, and the helper that ties the enum to the schema CHECK. See Handoff notes before editing it. (~0.4K tokens)
7. `ck_partner_directory_index_specialty` and the `specialty` column on the directory-index table, with the comment above it. The DB-side closed list, currently the same four values, and the doctors-only clause. (~0.3K tokens)
8. The `specialty` query parameter on the public directory-search route, typed as `Annotated[Specialty | None, Query()]`. The only runtime consumer of the enum today, and the one that must keep accepting every existing value after the list grows. (~0.2K tokens)
9. The module header of the credential-validity unit suite plus one of its tests. The precedent the ticket names: pin the pure decision with no database, and say in the docstring that the SQL side is deferred to the integration tier. (~0.4K tokens)
10. `DIRECTORIES_SPECIALTIES` and the `Specialty` type alias in the frontend directory-search client, with the source comment above it. The duplicated four-value list whose comment claims lockstep with the domain enum. Read only to make the defer-or-update decision recorded in Handoff notes. (~1.0K tokens)

## Do NOT read

- `docs/archive/` - superseded by the PRD.
- `docs/roadmap/implementation-roadmap.md` and `docs/architecture/internal-modules.md` - the traceability rows these vocabularies gain are owned by **#622**.
- `lib/i18n/dictionaries.ts`. It is a 200KB single dictionary and the display labels for the new values are not this ticket's job. The vocabulary values must be stable, machine-readable keys that a later ticket can label in both locales; the labels themselves land with the section tickets.
- `modules/partner/facade.py`, `directory_facade.py` and the profile models, except the one existing validator named in Handoff notes. No facade reads the new vocabularies yet.
- The doctor profile page, the public profile renderer, `DirectoryBrowser` and the pick-a-doctor page. Their duplicated `SPECIALTY_LABEL_KEY` maps and `chipClass` factories are downstream consumers, consolidated by other tickets.
- `modules/intake/domain/events.py` beyond the one line named in Handoff notes. It has a language vocabulary of its own that means something else entirely.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - 2628 passing on this tree. This is the real baseline: two tests inside the existing directory-schema suite pin the four-value specialty set, and they are the ones this change will move.
- `npm run typecheck` - `mypy --strict` over the backend, which is what will catch a new `StrEnum` used where a plain `str` is declared.

Not needed here: `npm run test:integration` (no schema change, no database in this slice), `npm run test:unit:frontend` and `npm run test:e2e` (no frontend change), `npm run migration-check` (no migration), `npm run check:pages`.

## Done-verify (acceptance criteria to commands)

- `npm run test:unit:backend` - proves the new suite's three cases per vocabulary (known-good accepted, unknown rejected, malformed rejected) and, just as importantly, that the two pre-existing specialty tests you reconciled are green. A red `test_specialty_is_a_closed_strenum` is the single most likely way this ticket lands broken.
- `npm run typecheck` - the three vocabularies and their validation entry points typecheck under `mypy --strict`, with no untyped escape hatch around the member check.
- `npm run lint` - ruff plus the no-em-dash gate. The specialty list is twenty prose values and is a prime spot for a stray dash character.
- Grep sanity before closing: the previous four values still appear in the domain enum, and the `_Avoid_` list under the glossary's **specialty** entry still reads exactly `consultation type` and `expertise`. Those two greps answer the first and last acceptance criteria directly.

## Handoff notes

- **No blockers.** The ticket's Blocked by section is "None - can start immediately", and that is correct. This ticket is the widest blocker in the batch - **four** siblings name it explicitly and cannot start without it:
  - **#607** (extract the shared directory-entry refresh operation) - the refresh carries the specialties, so it needs a list-shaped source of truth.
  - **#608** (the practice section write that replaces the whole-form write) - writes the multi-valued specialties.
  - **#610** (the about and notification section writes) - writes the languages and the consulting days.
  - **#612** (make specialty search an overlap match and serve area from declared locality) - the overlap match is a membership test against exactly this list.
- **The two existing tests that will go red, and the judgement call about them.** `test_specialty_is_a_closed_strenum` asserts the enum is _exactly_ the four values, and `test_specialty_matches_directory_index_check` asserts every enum value's text appears inside the `ck_partner_directory_index_specialty` constraint. Growing the list breaks both. The constraint is the harder half: it was baked into an already-applied revision, and ADR-0003 makes a migration immutable, so it cannot be edited - only replaced by a new migration. Replacing that column and dropping that constraint is **#606**'s slice, not this ticket's. So this ticket owns reconciling the two tests, and the recommended resolution is: keep the four legacy values in the list (the first acceptance criterion already requires it), and narrow the lockstep test from "every enum value is in the constraint" to "the four legacy values are still accepted by the constraint" with a comment naming **#606** as the ticket that retires the constraint. Widening the constraint here instead is defensible but pulls a schema migration into a domain ticket, and it would then have to be a _new_ revision anyway, so it buys nothing.
- **Why the domain widening is safe against the still-four-value constraint.** Nothing has ever written a specialty at runtime - the column is always NULL, because the only runtime writer of the directory entry never sets it. So the sixteen new values cannot reach the database through any existing path. That is exactly why this ticket can be domain-only. The safety argument evaporates the moment **#606** lands a writable multi-valued column, which is why **#606** must not skip the constraint replacement.
- **Judgement call, recorded: the existing Pydantic validator is left alone.** `DoctorProfileUpdate.validate_languages` is the current validation entry point for the languages field, and it only strips whitespace, bounds each name at 50 characters and rejects duplicates - it has no notion of membership. The acceptance criteria ask for a _domain_ entry point, and the model this validator belongs to is the whole-form write that **#611** retires outright. Landing a domain entry point and leaving the model untouched is therefore in scope and complete. If rewiring the validator to call the new entry point is cheap, it is a nice bonus, but do not restructure that model here: it is a dead route within two tickets.
- **Do not conflate the two language vocabularies in this repo.** The intake module defines `IntakeLanguage` as a two-value literal for the interface language of a patient session. That is a different concept from the languages a doctor consults in and must not be reused, extended, or placed next to the new list without a comment saying why they differ.
- **Judgement call, recorded: the frontend value list is deferred, not updated.** `DIRECTORIES_SPECIALTIES` holds the same four values and its comment claims lockstep with the domain enum, so it becomes stale the moment this lands. Two of the five places that duplicate the specialty label map are the ones **#612** rewrites anyway. Recommendation: leave the frontend untouched so this ticket stays backend-only and its done-verify stays the backend suite, and let **#612** reconcile the list and the label maps once, in one place. If you do touch it, update the stale comment at minimum - but do not start the i18n work.
- **Doctrinal point the ticket is really enforcing.** The house rule, visible in the `Specialty` docstring itself, is that the domain never names a value the schema cannot hold. This ticket deliberately breaks that lockstep for sixteen values for one release of tickets, and says so out loud rather than pretending. A comment on the enum saying the constraint is retired by **#606** is the honest form of that.
- **Relevant ADRs.** **ADR-0003** (db-per-module isolation) governs the constraint question, since a migration is immutable and the CHECK can only be replaced, never edited. **ADR-0012** (directory entry, one unit per partner) is adjacent context for why specialty lives on the directory entry at all. Neither is a read-list item for this slice; both are one-screen files if a reviewer disputes the constraint decision. The ADRs this parent work writes are reserved as **0021** and **0022** and are owned by **#622**; do not write either here.
- **On "doctors-only".** Keep that clause where it already lives, on the enum's docstring and on the directory-index column. It is a statement about which partner types carry a specialty, not a second validation rule, and there is no non-doctor specialty list to validate against.
