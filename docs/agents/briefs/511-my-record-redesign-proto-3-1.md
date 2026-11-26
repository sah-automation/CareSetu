# Brief - 511 My Record redesign: two-zone mobile/desktop timeline (PROTO-3.1)

**Ticket:** #511 · **Parent:** none (standalone prototype-driven redesign) · **Refreshed:** 2026-09-22
**Reading surface:** ~25K tokens - exceeds the 10K budget; budget gate waived by explicit request 2026-09-22. Re-cut is recommended after this lands (see handoff notes).

## Scope

Rebuild the patient `/patient/record` page to the ratified PROTO-3.1 design (`prototype/phase-3/record.html`): a "snapshot answers what you should know, timeline carries the story" two-zone layout.

- **Below 1024px:** a horizontal snapshot strip of count tiles that double as jump-filters (Everything + Consultations + Prescriptions + Lab results + Metrics), a sticky single-line filter bar, a reverse-chronological timeline grouped by date (Today / Yesterday / month), and collapsed privacy sections below the feed.
- **At/above 1024px:** the same filter bar and timeline in a main column beside a sticky 300px rail (At-a-glance summary, health-tracking nudge, who-accessed accordion, consent-log link).

Key behaviours (from the ticket's user stories + implementation decisions):

- Heading "My Health Record" + one-line explanation (existing `record.title`/`record.description` stay).
- Snapshot and rail counts derived from the record payload only - truthful zero, never hardcoded; "n issued" (prescriptions with non-delivered status) and amber "n flagged" (lab entries whose `results` carries a `below_range`/`above_range` row) micro-labels.
- Single-line filter row, never wrapping; Lab results rendered as a chip at >=720px and folded into the More menu below 720px; Metrics only reachable through More, never a chip. "More" renames to the active filter when Lab/Metrics is active.
- Timeline grouped by local calendar day: Today / Yesterday / otherwise "Month Year" via `Intl` (bilingual). Group headings with hairline rule + entry count.
- Entry cards become whole-card links to `/patient/record/{entry id}`; each card has a type-colored left-edge stripe, tinted circular icon chip, existing title + badge pill, documented subtitle line, chevron. Type tone map reuses the existing shared token palette (warm = consultation, success = prescription, accent = lab, muted = metric and settlement) and the shared `BADGE_TONE` map.
- Payload-driven variant lines (honesty): prescription cards lead with Issued/Delivered + `Rx #id`; lab cards show inline amber out-of-range badges only when `payload.results` carries an out-of-range status (conditional, degrades to nothing); settlement cards show amount + reference; consultation/metric cards stay title + date.
- Desktop rail (lg only): At-a-glance with payload-derived counts, health-tracking Soon nudge (existing `placeholder.health` strings), who-accessed accordion with count reusing the existing access-history list markup + fetch/error/empty/loading states, consent-log link to `/patient/record/consent-log`.
- Mobile privacy section below the feed: same three elements, `lg:hidden`.
- No JS breakpoint detection: responsive zones duplicate nodes toggled by Tailwind (`lg:hidden` / `hidden lg:block`). One set of data-testid hooks per zoned copy of a duplicated section.
- Loading skeletons, error banner with Retry, and honest empty state preserved from today; a failed read never renders as an empty state.
- **Drive-by fix in scope:** the entry detail page links to `/patient/consent-log`; it must point to `/patient/record/consent-log`.
- REQ-006 bilingual parity: every new string exists in both EN and HI with identical shape (Today/Yesterday labels, snapshot labels + micro-labels, rail footnote, "At a glance", access accordion hint, "Open consent log", per-row lab flag composition). Month names come from `Intl`, not dictionaries.
- No new dependencies; existing emoji set, dropdown-menu primitive, PageHeader, EmptyState, ErrorBanner stay.
- New pure helpers `groupTimeline`, `countByType`, `flaggedValues` in the record view-model, unit-tested directly.
- Existing test identifiers preserved where behaviour is unchanged.

## Read-list (in order)

1. The finalized PROTO-3.1 prototype `record.html` - binding visual spec: zone layout, snapshot-tile anatomy, filter-bar breakpoints (720px / 374px), entry-card anatomy, rail/mobile privacy cards, all `rec.*` strings in EN+HI (~6K tokens).
2. The live page component under the patient light shell (the `RecordPage` default export) - what it renders today: existing chip row + More dropdown primitive, `LoadStatus` lifecycle, access-history load chain (needs `timeline.patient_id`), honest empty/error/skeleton states, `placeholder.health` nudge (~2K).
3. The record view-model (`timelineView`) - `RecordFilter`, `RECORD_FILTERS`, `MORE_OVERFLOW_FILTERS`, `BADGE_TONE`, `EntryCard`, `describeEntry`, `formatOccurredAt`; the new helpers land beside these and reuse their shapes. Note `describeEntry` subtitle lines = `Rx #id`, `filed from booking #<order_id>`, settlement ₹amount + `#<order_ref>`, prescription issued/delivered badge - the variant lines the redesign surfaces (~1.2K).
4. The record API contract (`fetchOwnRecord`, `RecordTimeline`, `RecordEntryView`, `RecordEntryType`, `payload: Record<string, unknown>`) - every count/badge/flag is derived from this payload; documented payload keys live in the view-model comment + `adapters/__init__.py` (prescription `prescription_id`/`status`, lab `order_id`/`filename`/`results`, settlement `settlement_id`/`order_ref`/`amount_paise`) (~0.8K).
5. The audit API contract (`fetchAccessHistory`, `AccessHistoryEntry`, `AccessHistoryView`, `guardShape`) - the who-accessed accordion's data source and its existing error/empty/loading handling (~0.4K).
6. The `record.*` dictionary slice + the parity gate - the typed EN/HI key block to extend and the `parityProblems` test that mechanically enforces identical shape (REQ-006) (~0.8K).
7. The existing record page suite + view-model unit tests - the page seam (`@/lib/record/api` + `@/lib/audit/api` mocked at the facade boundary, waiting on `record-timeline`, exercising More dropdown + EN/HI flip), existing testids (`record-loading`, `record-timeline`, `entry-<id>`, `filter-chip-<type>`, `filter-more-*`, `access-history*`, `placeholder-health`), and the `timelineView` test patterns to extend for the new helpers (~2.5K).
8. The entry detail page + its suite - the drive-by consent-log link fix (`href="/patient/consent-log"` -> `/patient/record/consent-log`) and its asserted testid (`consent-log-link`) (~0.8K).
9. Standards: `coding-standards.md` (frontend harness, tests, isolation) and `api-standards.md` only as needed for the error envelope the page already consumes (~0.5K).
10. The blocking/proto process notes in `prototype/PLAN.md` PROTO-3.1 row (status `review`; open questions were answered by the finalized design - counts payload-derived, 5-tile strip confirmed, rail confirmed) (~0.2K).

## Do NOT read

- `docs/archive/`; backend modules (health/audit/consent) - the API contracts above already mirror them; consent screens (`consent-log` page itself is unchanged); Phase 12 metrics/follow-up implementation; home page recent-activity card internals (`describeEntry`/`BADGE_TONE` are shared but need no change - verify only that no existing call site breaks); `docs/roadmap/implementation-roadmap.md` and `docs/prd/project-prd.md` in full (nothing in the roadmap governs a post-PHASE-3 UI polish).

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - 1194 passed on 2026-09-22 baseline.
- `npm run typecheck:frontend` - clean on baseline.
- `npm run lint` - clean.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend` - extended page suite (entry-\* ordering under grouped output; snapshot + rail counts == payload counts with truthful zero; "n issued"/"n flagged" micro-labels; lab flag badges conditional on `results` out-of-range rows; every entry card links to `/patient/record/{id}`; Metrics never a chip and reachable via More; zone-scoped testids isolate duplicate access/nudge nodes; every heading + new Dictionary key flips to Hindi) + extended view-model suite (today/yesterday/month bucketing, EN/HI month labels, `countByType` over mixed timeline, `flaggedValues` over empty/missing/mixed results) + detail-page consent-log link assertion.
- `npm run typecheck:frontend` - clean.
- `npm run lint` - clean.

## Handoff notes

- This ticket was sized at ~25K reading surface against the 10K budget; the gate was waived 2026-09-22. If the implementer hits half a context window before writing, stop and ask for a re-cut (view-model helpers / mobile zone / desktop rail / i18n + drive-by are the natural slices). Re-cut will likely follow this ticket regardless.
- The PROTO-3.1 prototype is `review` status, not yet `finalized` - the ticket body is the ratified contract and overrides any prototype ambiguity (hardcoded prototype counts/strings are demo-bound; live counts must be payload-derived).
- Honesty rules are binding: a failed read never renders as a calm empty state; flagged-lab badges only when `payload.results` carries `below_range`/`above_range`; metric cards never invent readings or advice.
- Accessibility: snapshot tiles carry `aria-pressed`; zone duplication means one testid set per responsive copy; scoping queries to a zone's own testid is part of the ticket's test decisions.
- The `lg` breakpoint (1024px) is the zone switch; 720px is the Lab-chip visibility switch; the grid is `grid-cols-[minmax(0,1fr)_300px]` at lg and above - the shell already constrains content to `max-w-[1040px]`.
- The consent-log page itself is untouched; only the entry detail page's link and its test change.
- Entry ordering must stay reverse-chronological by clinical time under grouped output - existing tests assert the `entry-*` ordering and must keep passing, not be weakened.
