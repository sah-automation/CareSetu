# Brief - 507 Patient home: Health snapshot right rail

**Ticket:** #507 · **Parent:** #498 · **Refreshed:** 2026-09-21
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

A health snapshot card in the sticky right rail showing the patient's last logged metric and latest report when they exist (derived from the record timeline), and honest "Soon" teasers when they do not - never fabricated numbers. The teasers tie to the metrics and lab-report phasing. The rail stays visible while the main feed scrolls on desktop.

- [ ] Rail shows the last logged metric and latest report when present in the record.
- [ ] When either is absent, the card shows an honest Soon teaser (no fabricated values).
- [ ] The rail is sticky on desktop (stays visible while the feed scrolls).
- [ ] Strings under `patientHome.*`/`health.*` in en + hi with parity enforced.

## Read-list (in order)

1. The health-snapshot returning vs fresh states in the binding `shell-light.html` spec (grep `health`, ~457-499) including the rail asides and Soon teasers (~1.2K).
2. The own-record read client and how the newest metric and lab-report entries are distinguishable by entry type in the timeline (`entry_type === "metric" | "lab_report"`, newest first) - derive, never invent (~1.2K).
3. The 300px sticky right-rail slot and its `min-width:0` rules created by #499 - what the rail already renders structurally (~0.5K).
4. The `patientHome.*`/`health.*` dictionary slices and the composed home `page.test.tsx` seam from #499 (~0.8K).
5. The blocking ticket #506 closing comment, if any (~0.2K).

## Do NOT read

- The metrics feature and lab-report module internals (teasers stand in for them until P12/P9), the audit surface, backend modules, unrelated dictionary sections.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` and `npm run typecheck:frontend` (green on 2026-09-21 baseline; #506 may drift them only if broken).

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend` - real values when present, teasers when absent (record states), rail sticky on desktop.
- `npm run typecheck:frontend` - clean.
- `npm run lint` - clean.

## Handoff notes

- Honesty is the spec: the rail must never render fabricated numbers. Pick the newest `metric` and newest `lab_report` from the record timeline when they exist; otherwise render the Soon teaser keyed to the future phase.
- The rail is the sticky aside from the shell; this ticket fills it. Keep the desktop >=1024px sticky behavior intact.
