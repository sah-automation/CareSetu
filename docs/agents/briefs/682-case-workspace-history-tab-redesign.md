# Brief - 682 Case workspace History tab redesign

**Ticket:** #682 · **Parent:** #673 · **Refreshed:** 2026-10-09
**Reading surface:** ~5.2K tokens (budget 10K) - within budget

## Scope

The case workspace History tab renders two stacked sections: the detailed consultation history via the shared record-entry renderer, and a patient medical-history (health background) section via the shared health-background block. The existing best-effort console-detail read is widened to return the whole detail projection (consultation history plus health background) instead of only the consultation history, preserving the one-read invariant between the patient-detail page and the workspace. A null health background renders the calm not-shared card, never an error. Consent gating is unchanged: entry history on `consultations`, health background on `health_background`.

Approved scope decision: the shared record-entry renderer is adopted inside `ConsentedHistory`, so the review page (its other consumer) also gains the richer per-type history. That upgrade is in scope and the review page's tests are updated accordingly.

## Acceptance criteria

- [ ] The History tab renders the detailed consultation history via the shared record-entry renderer, identical to the patient-detail page
- [ ] The History tab renders the patient medical-history (health background) section via the shared health-background block
- [ ] The best-effort console-detail read returns the whole detail projection (history plus health background); one read feeds both sections
- [ ] A null or denied health background renders the not-shared card, never an error; an empty background renders the quiet empty state
- [ ] A failed projection read still degrades to the workspace's existing fail-closed consented read fallback
- [ ] Existing workspace test hooks are preserved and new assertions cover both sections
- [ ] Adopting the renderer inside `ConsentedHistory` upgrades the review page too; its tests are updated and stay green
- [ ] Every new string ships in both English and Hindi (parity preserved)
- [ ] `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` pass

## Read-list (in order)

1. The shared record-entry renderer and the shared health-background block interfaces (from #677 and #679) - what the workspace feeds each. (~500 tokens)
2. `ConsentedHistory` - its three-state `timeline` prop contract (`undefined` self-fetch, array render-given, `null` not-shared) and its current tag+date entry markup, which the shared renderer replaces. Its other consumer is the review page, which is why this change reaches that surface. (~1.2K)
3. The case-workspace History tab region, the `readConsoleConsultationHistory` helper, the `patientHistory`/`historyLoadState` state and the load wiring that fires it. Widen the helper to return the whole detail projection rather than only `consultation_history`. (~1.2K)
4. `DoctorPatientDetailView` and `HealthBackgroundView` in the doctor API client - the projection fields the widened read exposes. (~300)
5. The workspace test blocks for the History tab and the review page test blocks that render `ConsentedHistory`. (~1.5K)
6. The `caseWorkspace` and `doctorPatients` i18n namespaces in both locales. (~500)

## Do NOT read

- The rest of the large workspace page beyond the History tab, the read helper and the state/load wiring.
- The backend. `fetchDoctorPatientDetail` already returns both `consultation_history` and `health_background`.
- `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - confirmed green 2026-10-09 (134 files / 2157 tests passed).
- `npm run typecheck:frontend` - confirmed green 2026-10-09.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend` - workspace History-tab assertions for both sections, the updated `ConsentedHistory` and review-page suites.
- `npm run lint`
- `npm run typecheck`

## Handoff notes

- **`ConsentedHistory` is shared.** It is rendered by the workspace and by the review page. Adopting the renderer inside it is the approved way to keep the workspace and review surfaces consistent; update the review page's tests rather than leaving them asserting tag-only markup.
- **Preserve the three-state contract.** `null` stays the calm not-shared card; the propless self-fetch path is untouched. Only the rendered-entry markup changes to the shared renderer.
- **Widen, do not duplicate, the read.** Keep the one best-effort console-detail read and have it return the whole projection; the medical-history section and the history section must share it so the patient-detail page and workspace cannot disagree (one-read invariant).
- **Best-effort degradation is load-bearing.** A failed projection read still answers `undefined` and falls back to `ConsentedHistory`'s own fail-closed consented read; a denied health background is a calm lock, never a page error.
- **Null health background is not-shared, not empty.** A null/denied background renders the not-shared card; a set-but-empty background renders the quiet "none recorded" chips.
- **No em-dashes anywhere** (lint-gated) - use simple dashes.
