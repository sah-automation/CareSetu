# Brief - #516 Recent activity rows go professional + per-type pills

**Ticket:** #516 · **Parent:** #512 · **Refreshed:** 2026-09-23
**Reading surface:** ~2.5K tokens (budget 10K) - within budget

## Scope

The homepage "Recent activity" rows (`RecentActivityCard`) render the same professional prescription content as the record cards (medicine-name title, dose line, issued-by) and switch from the status pill to the PROTO-2.7 per-type pill (icon + type label, tinted: Consultation / Prescription / Lab result / Metric), while keeping the professional title + subtitle and the right-hand `when` column. Type labels reuse the existing `record.badge.*` dictionary. The recent-activity unit block and the homepage tests update to the new anatomy, including Hindi copy.

Acceptance criteria (from the ticket):

- [ ] Row pill is per-entry-type (type label + icon, tinted background), not the status pill.
- [ ] Prescription rows show the professional title/subtitle from the shared view-model output (medicine name, dose, issued-by).
- [ ] Right-hand `when` column unchanged.
- [ ] Homepage recent-activity tests assert the new anatomy (type pill + professional copy) in both EN and HI.

## Read-list (in order)

1. `RecentActivityCard` - the row renderer: the pill currently renders `card.badge` (status) via `BADGE_TONE`; this becomes a per-type pill (icon from `card.icon`, type label from the `record.badge.*` key for `entry.entry_type`, tinted) (~1K).
2. The homepage recent-activity test block - assertions to update for the type pill + professional copy, EN + HI; the existing describe-helper-copy test proves the seam reuse (~1K).
3. `describeEntry` output shape (`EntryCard`: icon/title/subtitle/badge) from #515's seam - read only; the type pill keys off `entry.entry_type`, not the status badge (~0.5K).

## Do NOT read

- Backend modules, the record page, the entry-detail page, `prototype/`, `docs/archive/`. Do not add new dictionary keys - reuse the #515 keys.

## Baseline verify (must pass before the first edit)

- `npm run typecheck:frontend` - verified green 2026-09-23.
- Targeted: `npm run test -w @caresetu/frontend -- "src/app/(patient)/patient/page.test.tsx"` - verified green. (Full-suite worker-spawn flake under load is unrelated; see #515's brief.)

## Done-verify (acceptance criteria → commands)

- `npm run test -w @caresetu/frontend -- "src/app/(patient)/patient/page.test.tsx"`
- `npm run typecheck:frontend`.

## Handoff notes

- This is a composition change in `RecentActivityCard`, not a view-model change - `describeEntry` already carries the professional title/subtitle once #515 lands. The pill's label changes from status (`Active`/`Delivered`) to type (`Prescription`/`Lab result`/...) via an `entry.entry_type` -> `record.badge.*` mapping plus `card.icon`; no new dictionary keys.
- Keep `RECENT_ACTIVITY_MAX = 3`, reverse-chron sort, non-navigating rows, `omitOccurredAt: true` on the seam call, and the right-hand `formatOccurredAt` `when` column.
- The existing test that asserts rows render "through the My Record describe helper copy" (`/Rx #12/`) needs to extend: professional prescription rows now show the medicine title/dose instead of the bare `Rx #…` subtitle, so `Rx #12` may no longer appear in-row - update to the professional copy and add an "$active/type pill" assertion.
