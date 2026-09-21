# Brief - 506 Patient home: Recent activity card from record timeline

**Ticket:** #506 · **Parent:** #498 · **Refreshed:** 2026-09-21
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

A "Recent activity" card on the home showing the top 3-4 events of the patient's record timeline rendered through the existing record-timeline describe/format helper - consultations, prescriptions, lab results, metric logs. Access-history reads are never mixed in (a separate data source by construction). A friendly empty state covers a record with no activity yet. "View all" links to My Record so the full timeline is one tap away.

- [ ] Card shows the top 3-4 record-timeline events via the existing describe/format helper.
- [ ] Access-history reads never appear in recent activity.
- [ ] An empty record renders the friendly empty state.
- [ ] View all navigates to My Record.
- [ ] Strings under `patientHome.*`/`recent.*` in en + hi with parity enforced.

## Read-list (in order)

1. The recent-activity card markup, its list rows and the fresh-patient empty state in the binding `shell-light.html` spec (grep `recent`, ~420-452) (~1K).
2. The own-record read client and the record-timeline describe/format helper (`describeEntry`, `sortTimelineDesc`, `formatOccurredAt`) - the entry projection and per-type rendering it returns (~1.5K).
3. Where My Record lives in the patient navigation config (the View all destination) (~0.3K).
4. The `patientHome.*`/`recent.*` dictionary slices and the composed home `page.test.tsx` seam from #499 (~0.8K).
5. The blocking ticket #505 closing comment, if any (~0.2K).

## Do NOT read

- The access-audit client/surface (it must stay separated), the consents surface, backend record modules, unrelated dictionary sections.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` and `npm run typecheck:frontend` (green on 2026-09-21 baseline; #505 may drift them only if broken).

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend` - top-N timeline slice at the composed seam, empty state, View all destination.
- `npm run typecheck:frontend` - clean.
- `npm run lint` - clean.

## Handoff notes

- Access-history is a separate client/surface by construction - the recent-activity slice reads only the record timeline, so "never mixed in" is guaranteed by not importing the audit client at all.
- Render through the existing describe/format helper so per-type badges/copy stay consistent with My Record; take the top 3-4 after the timeline's reverse-chronological sort.
- View all targets the live My Record route from the patient nav config.
