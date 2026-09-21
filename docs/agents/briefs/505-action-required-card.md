# Brief - 505 Patient home: Action required card from pending consent requests

**Ticket:** #505 · **Parent:** #498 · **Refreshed:** 2026-09-21
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

An "Action required" card on the home that is completely absent when nothing is pending. When pending decisions exist (today: pending patient-consent requests, read from the existing consent-read flow filtered to "requested"), it lists them with Allow / Not now actions wired to the existing grant and decline flows. Rx substitute/refund and booking confirmations are future sources and are not stubbed.

- [ ] Card renders nothing when there are no pending items (no empty card, no placeholder).
- [ ] When pending consent requests exist, the card lists them and Allow / Not now act on them through the existing consent flows.
- [ ] Strings under `patientHome.*`/`actions.*` (or equivalent) in en + hi with parity enforced.

## Read-list (in order)

1. The action-required card markup, badge and consent-row actions in the binding `shell-light.html` spec (grep `actions`, ~404-417) (~0.8K).
2. The consent-read client (`fetchConsentLog`) - its returned shape and status field - and the consent-log surface's pattern for deriving pending items plus its grant/decline handling to reuse (~2K).
3. The `patientHome.*`/`actions.*` dictionary slices and the composed home `page.test.tsx` seam from #499 (~0.8K).
4. The blocking ticket #504 closing comment, if any (~0.2K).

## Do NOT read

- Rx substitute/refund or booking-confirmation code (future sources, deliberately not stubbed), the access-audit surface, backend consent modules, unrelated dictionary sections.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` and `npm run typecheck:frontend` (green on 2026-09-21 baseline; #504 may drift them only if broken).

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend` - absent card (no element) with zero pending; listed items + working actions with pending items.
- `npm run typecheck:frontend` - clean.
- `npm run lint` - clean.

## Handoff notes

- Honest behavior is the spec: hidden when nothing is pending - assert the element is absent, not merely empty.
- Today's only source is pending consent requests derived from the existing consent-read flow (status == "requested"); do not invent a new endpoint or stub Rx/booking sources.
- Reuse the existing grant and decline actions from the consent-log surface rather than duplicating consent logic - wired to the same effects, with post-action reconciliation so the card updates.
