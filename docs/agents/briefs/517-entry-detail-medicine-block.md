# Brief - #517 Medicine block + doctor attribution + Rx ref on the entry detail page

**Ticket:** #517 · **Parent:** #512 · **Refreshed:** 2026-09-23
**Reading surface:** ~3K tokens (budget 10K) - within budget

## Scope

The single-entry detail page (`/patient/record/[entryId]`) for a prescription entry renders a medicine-item block listing every line (name · dose · frequency · duration), the prescribing doctor, and the Rx reference, alongside the existing header, source card, and egress trail. Pre-enrichment payloads with no `items` degrade honestly (no invented fields). Hindi copy asserted.

Acceptance criteria (from the ticket):

- [ ] Detail page shows one line per medicine item (name · dose · frequency · duration); a multi-item prescription lists every item.
- [ ] Page shows the prescribing doctor attribution and the Rx reference.
- [ ] Legacy payload without `items` degrades without empty/phantom fields.
- [ ] Detail-page tests updated for the medical block in both EN and HI.

## Read-list (in order)

1. The entry-detail page - how it builds `card` via `describeEntry` for the header, its local `payloadResults` parser (lab table prior art), and `payloadNumber`/`payloadString` usage - add the prescription block beside the lab-results block with the same conditional (`entry_type === "prescription"` and `items` present) (~1.5K).
2. The detail-page test - existing describe blocks (header/source, lab table, egress, EN/HI) to extend with the medical-block cases (~1K).
3. The `items`/`attributed_doctor_name` payload contract + the new dictionary keys landed by #515 (`issuedBy`/`prescribedBy`/`moreItems`, neutral attribution) - read only; the block renders from those keys (~0.5K).

## Do NOT read

- Backend modules, `RecentActivityCard`, the record timeline page internals, `prototype/`, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run typecheck:frontend` - verified green 2026-09-23.
- Targeted: `npm run test -w @caresetu/frontend -- "src/app/(patient)/patient/record/[entryId]/page.test.tsx"` - verified green. (Full-suite worker-spawn flake under load is unrelated; see #515's brief.)

## Done-verify (acceptance criteria → commands)

- `npm run test -w @caresetu/frontend -- "src/app/(patient)/patient/record/[entryId]/page.test.tsx"`
- `npm run typecheck:frontend`.

## Handoff notes

- The block renders only from what the payload documents (REQ-033 honesty rule): condition on `entry_type === "prescription"` and `Array.isArray(items)`; a legacy entry (no `items`, or empty `attributed_doctor_name`) simply skips the block - no placeholder rows.
- One line per item with `name` always rendered; `dose`/`frequency`/`duration` joined with `·` only when present (same ascription style as the card's dose line).
- Doctor attribution renders the translated `issuedBy`/`prescribedBy` prefix with the payload `attributed_doctor_name`; `null` -> neutral copy (or omit), never an invented name. Rx reference renders `Rx #<prescription_id>`.
- All new copy comes from the #515 dictionary keys - no re-keying in this ticket.
- Tests assert rendered external copy (medicine lines, doctor, Rx ref, absence on legacy), not implementation internals.
