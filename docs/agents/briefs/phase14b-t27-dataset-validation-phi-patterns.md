# Brief - #788 Evaluation dataset validation and PHI-pattern rejection

**Ticket:** #788 - **Parent:** #761 - **Published:** 2026-10-23
**Reading surface:** ~6K

## Scope

Validate dataset examples on create and edit: reject malformed examples, oversized text, and obvious PHI patterns such as phone numbers, email addresses, and government identifiers.

- [ ] Malformed examples are rejected.
- [ ] Oversized text is rejected.
- [ ] Obvious phone, email, and government identifier patterns are rejected.
- [ ] Failures use the shared error envelope and do not partially write.
- [ ] Tests cover each rejection path.

## Blocked by

- #787 - Versioned evaluation dataset API

## Read-list (in order)

1. Spec #761, dataset validation decisions.
2. The dataset models and routes, the validation patterns, and the security PHI standard.

## Do NOT read

- docs/archive/
- The frontend.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend`
- `npm run typecheck`

## Handoff notes

- Keep synthetic data synthetic.
- Do not add a general-purpose sanitizer.
- Read only the named sections and grep for interfaces by name. Do not read whole files, unrelated modules, or generated files.
