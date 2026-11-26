# Brief - #623 Combined two-axis code review across the profile redesign tickets

**Ticket:** #623 · **Parent:** #599 · **Refreshed:** 2026-09-30
**Reading surface:** ~102.8K tokens as literally specified (budget 10K) - **OVER budget by ~93K. This is the one ticket in the batch where the gate verdict is a re-cut of the _process_, not the ticket: run the review ticket-slice by ticket-slice. See Handoff notes for the working read-list, which lands at ~9.6K.**

## Scope

Every ticket in this batch has been reviewed on its own, against its own brief. This reviews them together: two axes, standards and spec, over the whole change at once, with fixes for anything found. The cross-ticket failures this catches are the ones no single ticket can see - a section that saves but a preview that does not update, a schema that widened but a constraint that still assumes single-valued, a string that shipped in one locale only.

Acceptance criteria:

- [ ] A two-axis review runs over every ticket in the parent batch together, not ticket by ticket.
- [ ] Every finding is fixed, and the fixes are verified by the repository's own gates.
- [ ] The full harness passes: backend and frontend unit suites, integration, end-to-end, lint, strict type check, migration check, the module boundary check, and the page-weight gate.

## Read-list (in order)

The list below is the ticket's literal reading surface, sized honestly. It is ~102.8K against a 10K budget, and it cannot be made to fit - item 6 alone is ~71K. Read Handoff notes for the sliced working list that replaces this one.

1. `CONTEXT.md` build-session protocol, cross-reference rule and do-not-read gate - the doc map, and the rule that the cross-reference matrices are the single source of truth for how parts connect (~0.6K tokens)
2. All six standards in `docs/standards/`, whole - `coding-standards.md` (~2.5K), `api-standards.md` (~0.9K), `third-party-integration-standards.md` (~1.2K), `error-handling-observability.md` (~1.0K), `security-phii-standards.md` (~0.8K), `ai-engineering-standards.md` (~1.7K). The standards axis cannot be run against a summary: this change touches schema, API contracts, frontend, security and no new AI seam, and each standard has a rule the diff could violate that no other standard restates (~8.1K)
3. `docs/architecture/internal-modules.md` sections 4.1 (sync matrix) and 4.2 (event registry) and 5 (end-to-end traceability matrix), read whole - the edges this change moved are the thing under review: four routes replaced one, a new table appeared, the directory entry's write semantics changed, and the search read path lost a join (~10.3K)
4. `docs/architecture/internal-modules.md` sections 3.2 (`MOD-002` Partner Lifecycle & Directory) and 3.12 (`MOD-012` Doctor Console) - the module specs the edges in item 3 point at, and the two that this change edited (~2.0K)
5. `docs/roadmap/implementation-roadmap.md` section 3, whole - same reason as item 3: the feature to module to phase matrix is where a moved edge becomes a stale row (~4.9K)
6. The fifteen sibling briefs of the parent batch - the contract each was implemented against (~70.9K). **Do not read these as a block.** See Handoff notes.
7. The parent #599 body, whole - the spec axis reference: problem statement, all 47 user stories, the implementation decisions, the nine testing seams, the out-of-scope list, and the acceptance criteria no individual ticket was given (~6.0K)

**Working replacement for item 6** (this is the list to actually follow):

6'. The `code-review` skill workflow at the tooling config root - the two-axis (standards vs spec) parallel-sub-agent procedure, run over one ticket-slice at a time against a fixed point, reporting both axes side by side (~0.8K)
6''. The batch's fixed point and ticket list - the merge-base of the first batch ticket, plus the ordered ticket numbers, so each slice has an unambiguous diff (~0.3K)
6'''. Per slice, and **only during that slice**: that one ticket's own brief (~1.5K each) and that one ticket's diff (~2K each), released as the previous slice closes

## Do NOT read

- The batch briefs as a block. Fifteen briefs total ~71K tokens; loading them all up front is the single largest overage in this batch and it is unnecessary. Each is a per-ticket contract, and each ticket has already been reviewed against its own.
- `docs/archive/` - superseded by the PRD.
- Unrelated modules, other doctor-console pages, the patient profile pages, the patient journey and auth-loop e2e specs.
- `docs/architecture/system-context.md` - no actor or `EXT-xxx` change in this batch; ADR-0022 explicitly creates no new external integration.
- The other ten module specs in section 3, and roadmap sections 2.0 through 2.14.
- Frontend or backend source beyond what a specific finding points at. Grep by symbol.

## Baseline verify (must pass before the first edit)

- `npm run lint`
- `npm run typecheck`
- `npm run test:unit:backend`
- `npm run test:unit:frontend`
- `npm run migration-check`

All five were verified green on this tree before the batch started, so any failure now is attributable to the batch. Also run and record, as the _starting truth_ rather than a gate:

- `npm run test:integration` - **expected to report skipped, not passed**, in this environment. There is no local native PostgreSQL, so the tier skips from its reachability fixtures. Record the skip count now, so a later "it passed" can be told apart from "it skipped again".
- `npm run test:e2e` - needs the shared Playwright browser cache under `D:\Dev\tools\`. Slow (boots a Next dev server plus a real backend).
- `npm run check:pages` - builds and serves the Next app on a free port, then measures each channel against the 1.5 MB budget. #614 added `/doctor/profile` to the channel list, so this is the gate the redesign has to fit inside.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend`
- `npm run test:unit:frontend`
- `npm run test:integration` - read the pytest summary line verbatim, including the skip count. A skip is not a pass; the integration tier is where the batch's central guarantees were proven, and if it skipped, say so rather than reporting the harness green.
- `npm run test:e2e`
- `npm run lint`
- `npm run typecheck`
- `npm run migration-check`
- `npm run check:boundaries` - the module boundary check named in the acceptance criteria. The new PIN centroid table is `partner`-schema (ADR-0003) and `MOD-012` still owns no schema; the boundary checker is what proves neither slipped.
- `npm run check:pages` - the page-weight gate, now including the profile route.
- The two-axis review recorded per slice: both axes reported for every ticket-slice, and every finding either fixed with its own commit or explicitly declined with a reason.

## Handoff notes

- **Blocker.** This ticket waits on **#622 (ordinal #23)**, the documentation closeout, so it runs last. #622 is also what makes the spec axis checkable: the two new ADRs (0021 and 0022), the glossary revisions, the PRD delivery notes, the `MOD-002` spec edits, the roadmap row and the research note are the written record of what this batch decided. Read #622's output before judging any slice against intent - several "the spec says X" findings are resolved by a doc #622 just wrote.
- **Run the review ticket-slice by ticket-slice. Do not load the whole batch up front.** The literal read-list is ~102.8K against a 10K budget, and the overage is structural: the fifteen batch briefs alone are ~71K, and the standards plus the three matrices add another ~27K. No amount of trimming makes the literal list fit, because a combined review is by definition a review of the union, and the union's written contracts do not compress. The fix is to change the _unit of work_, not the unit of reading:
  1. Fix the review's fixed point (the merge-base of the first batch ticket) and the ordered ticket list, once.
  2. For each ticket in order, run the `code-review` skill over **that ticket's diff only**, with both axes. Load **that one ticket's brief** immediately before its slice and drop it when the slice closes. That is ~3.5K per slice, and the context is fresh at exactly the moment it is used.
  3. Carry a running findings ledger across slices. Cross-ticket findings are the point of this ticket, so a finding raised in slice 4 must still be live when slice 11 exposes its other half. Write the ledger to a file, not to reasoning.
  4. Only after every slice closes, run one union pass over the two matrices (items 3 and 5) plus item 2's standards, with the ledger in hand. That final pass is where an edge that moved in slice 3 and a row added in slice 9 are caught as inconsistent, and it is the only moment the matrices need to be resident.
- **The four cross-ticket seams to look for by name.** The ticket body names the classes of failure; these are the concrete instances in this batch, and each has an owner ticket whose brief carries the detail:
  - **The section-write contract against the page's four independent buffers.** #609's address write, #608's practice write and #610's about and notification writes each own a section; #605 owns the per-section edit-buffer rule (seeded once per distinct server answer, a dirty buffer never reseeded by a late answer, a save's own reply never discarding keystrokes). The failure to look for: a section whose save reply reseeds a buffer the doctor is still typing in, or a page-level buffer quietly reintroduced around the four section buffers. Asserted at the page suite (#617) and, end to end, at the "can still save another section after a failed PIN" criterion in #621.
  - **The widened specialty storage against everything that still assumes single-valued.** #606 widens the profile column to multi-valued and drops the directory index's single-valued check constraint in favour of application-level validation. The failure to look for: a surviving equality predicate, a surviving `is None` guard, a surviving single-value schema field, or a Python `str` annotation where a collection now lives. #612 owns the overlap predicate; the homepage specialty chips and the pick-a-doctor suggested-specialty pre-filter are the two consumers that were silently returning nothing and that only a real query proves.
  - **The bilingual parity of every new and changed string.** #602 adds three closed vocabularies, #604 changes the doctor landing label to Dashboard and gives the account menu its own key, #615/#616/#617 add the whole page's copy. The failure to look for: a key present in one locale and missing from the other. The existing parity suite walks both locales recursively, so run it and treat a green run as necessary but not sufficient - confirm the new keys are actually asserted on, not merely absent from the failure list.
  - **The shared directory-refresh operation against the operator approval path.** #607 extracts the refresh that both the operator approval path and the address write call, and it must refresh only position, specialties and locality - never the listed flag, never any part of the verified derivation. The failure to look for: a refresh that grew a write, or a second copy of the index upsert SQL left behind in the approval path. This is the safety property the operator stories depend on, and it is asserted at the unit seam (#607), the integration seam (#620) and, in the docs, in ADR-0021.
- **A green unit suite is not a spec pass.** Three of the batch's own findings were live production defects with a passing test: the pick-a-doctor flow's unit test passes because it mocks the directory client and never reaches the real query; the coordinates a doctor saves are never read by search; the area shown on every profile and card is a platform default rather than the doctor's locality. So when the spec axis says "the flow works", verify it against a real query or a real request before accepting a green suite as evidence. Specifically: check whether any suite in the diff mocks the directory client, the PIN resolver, or the profile client.
- **The docstring `FEAT-xxx` trace is a gate, not a convention.** The coding standard makes PRD acceptance criteria the source of test names with the `FEAT-xxx` id in the test docstring. New test files in this batch must carry it, and the review should check it - a suite that proves the guarantee but does not name the criterion will not be found by the next person tracing the PRD.
- **Any fix landed here must stay inside the declared scope.** The parent's out-of-scope list is long and deliberate: per-specialty services, council registration numbers, gender and consultation modes, any change to the partner registration wizard, a booking system, interactive map pins and geocoding, multiple practice locations, a directory card redesign, retiring the service-area table, operator console changes beyond calling the shared refresh, a profile completion meter, and a design prototype. If a finding can only be fixed by crossing one of those lines, that is a spec decision, not a review finding: escalate to #599 rather than silently expanding the change. The one thing that is explicitly in scope and must be fixed if it is broken is the no-drift property - the live preview and the public profile rendering through one shared presentational component (#618).
- **Relevant ADRs.** Read the two new ones first, because they are the batch's own rulings: **ADR-0021** (a profile save moves the public directory position, superseding the "as recorded at registration" rule in ADR-0012) and **ADR-0022** (the practice position is a PIN centroid, not a geocode, and no new external integration is created). Then the ones the batch sits on: **ADR-0003** (db per module isolation - the new table is `partner`-schema and no cross-schema FK may exist), **ADR-0012** (one directory entry per partner, one geo point - amended, not replaced), **ADR-0002** (transactional outbox - the directory entry is written in the operator-approval transaction, which constrains the shared refresh), **ADR-0008** (the partner verification gate - why a profile save must not substitute for a verification round), **ADR-0005** and **ADR-0007** (dual JWT storage and the split-origin session invariants - the profile page's photo and session surfaces), **ADR-0019** (the schema-less-seam exception `MOD-012` stands on), **ADR-0020** (the private profile-media bucket the photo path rides).
- **Judgement call while mapping the surface.** The ticket body asks for "the briefs of every ticket in the parent batch" as a read-list item. On the live tree those fifteen briefs total ~277 KB (~71K tokens), which is seven times the whole budget on its own; and the batch's briefs for the schema, directory-refresh and PIN-decision tickets run 23-35 KB each, so they are dense prose rather than stubs. I have kept the item in the list and sized it honestly rather than quietly dropping it, and replaced it in the working list with a per-slice read. A combined review genuinely does need every ticket's contract - just not all of them at once.
