# Brief - #721 Composer-opened funnel entry step

**Ticket:** #721 · **Parent:** #717 · **Refreshed:** 2026-10-14
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

The intake-started event fires in the same transaction as intake capture, so a patient who opens the recorder and abandons without submitting is invisible and the funnel has no real entry. Emit a distinct entry step when the patient opens the composer, before any capture happens. The existing intake-started event is retained as-is for compatibility but stops being the funnel's entry.

- [ ] Opening the intake composer publishes the funnel's entry step, carrying the patient, a session key and the trace id.
- [ ] An abandon (composer opened, nothing submitted) is distinguishable from a submit, because the two steps are separate events.
- [ ] The existing intake-started event still fires at capture time, unchanged, with its existing payload.
- [ ] The new event is registered in the event registry with its payload fields.
- [ ] The composer call is authenticated and consent-safe; it writes no clinical content.

## Read-list (in order)

1. Spec #717 - Problem Statement hole 4; Implementation Decision 4. (~0.8K)
2. `docs/architecture/internal-modules.md` §4.2 - the intake event rows and the naming convention. (~0.7K)
3. The intake facade's capture entry point `submit_intake` - where `intake.started` is published inside the capture transaction, and why it therefore cannot serve as the funnel entry. (~1.2K)
4. The intake module's route module - how its routes are declared, authenticated and permission-gated; find the nearest read-only "something exists here" route as the shape for this endpoint. (~1.5K)
5. The intake outbox writer and the existing intake envelope builders, including `intake_started_envelope`. (~0.8K)
6. How a session key is obtained today: the trace context accessor, and whether the session identity the frontend already holds is the session key the product ledger will use. (~0.6K)
7. `tests/unit/test_intake_events.py` and the capture-facade tests - where a new publish site is asserted. (~0.8K)

## Do NOT read

- The product event ledger and funnel registry - #739 consumes this event; do not build them here.
- Frontend composer components beyond deciding whether a client call is needed at all.
- `docs/archive/`, the observability consumer internals, the care and partner modules.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:integration`

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run lint`, `npm run typecheck`

## Handoff notes

- **Do not repurpose `intake.started`.** It stays exactly as it is, on the capture transaction. The new event is a separate step in the funnel vocabulary.
- The endpoint carries no clinical content - no audio reference, no transcript, no free text. It records that a person arrived.
- Session key: decide whether the client holds a stable session identity today. If it does not, define the key here as the platform trace context's session scope rather than inventing client state - and say which you chose in the payload docstring.
- Downstream, #739 registers this as the funnel's first step and #740 counts it. If you pick a step name, keep it stable; the funnel vocabulary is a registry keyed on that name.
