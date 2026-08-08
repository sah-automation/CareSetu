# Unit tests — backend domain core

Pure domain-logic tests: state machines, validation, business rules. No I/O, no FastAPI, no database.

- Naming traces to the PRD: test names carry the `FEAT-xxx` id (coding-standards §6).
- One test per state-machine transition (happy + edge), using the PRD BDD scenarios.
- Run with `npm run test:unit:backend` (pytest) or `npm run test:unit:frontend` (vitest) from the repo root.

Populated from `PHASE-1` onward.
