# Brief - #736 Parameterised deep links

**Ticket:** #736 · **Parent:** #717 · **Refreshed:** 2026-10-14
**Reading surface:** ~9K tokens (budget 10K) - within budget

## Scope

Turn three bare base URLs into links that land on the answer: a Grafana dashboard with its time range and template variables set, a Grafana Explore pane for one trace, a Sentry query pre-filtered to this service and error type, and Langfuse views filtered by model and task plus per-actor and per-session views. A vendor with no configured key is absent from the response, never a broken link. Every link carries the same trace identifier the platform stores, so the join key is consistent everywhere.

- [ ] The deep-link read returns parameterised link sets - dashboard with relative time range and variables, Explore pane for a specific trace, Sentry pre-filtered to service and error type, Langfuse by model and task, plus per-actor and per-session views.
- [ ] A vendor with no configured key is absent from the response entirely, never a broken link.
- [ ] Every link carries the same trace identifier the platform stores.
- [ ] The frontend client contract moves with the widened wire shape, and the panel that renders deep links renders an absent vendor as absent.
- [ ] Panels across the existing AI surfaces can link through to the underlying traces using the widened response.
- [ ] The change is a wire change and is called out as one, with the client contract test updated.

## Read-list (in order)

1. Spec #717 - Implementation Decision 21; Implementation Decision 44 (the wire change); the deep-link user stories. (~1K)
2. The deep-link read's pure link builders and the facade method that assembles them - today three optional URL strings, each derived from settings. (~1.2K)
3. The settings fields supplying vendor configuration, and the rule that each key is independently optional. (~0.6K)
4. The frontend deep-link client type, its shape guard, and the panel that renders it - including how an absent vendor is already omitted rather than shown broken. (~1.5K)
5. The frontend wire-test helper pattern the Business lens (#737) introduced - stub fetch, real client, real operator token in the session store. (~0.8K)
6. How the trace identifier is minted, propagated and stored, so every link uses the platform's identifier rather than reconstructing one. (~0.9K)
7. The deep-link unit tests and the read-route round-trip's deep-link cases - extend, do not duplicate. (~0.9K)

## Do NOT read

- The observability read query internals beyond the deep-link read.
- The Grafana dashboard assets - #748 provisions dashboards; this ticket links to them by identifier, it does not create them.
- The langfuse batch pull and evaluators - #750, #751.
- `docs/archive/`, the intake and care modules.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:unit:frontend`
- `npm run test:integration`

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`
- `npm run test:unit:frontend`
- `npm run typecheck`
- `npm run lint`

## Handoff notes

- **Backend and frontend move together.** This is a wire-shape change with no compatibility window - the client contract and the read must land in the same change or the console breaks.
- Absent vendor means absent from the _response_, not a null field the client must interpret. Decide once and apply it to every vendor; the existing all-absent case already answers successfully.
- #748 creates the Grafana dashboards this ticket links to. Agree on the dashboard identifier scheme now (a stable slug the provisioning file also uses) or the links will point at nothing.
- The trace identifier in a link must be the platform's stored one. Reconstructing a trace id client-side produces links that land on an empty trace.
