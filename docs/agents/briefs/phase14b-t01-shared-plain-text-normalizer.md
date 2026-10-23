# Brief - #762 Shared plain-text normalizer and no-new-HTML-sink rule

**Ticket:** #762 - **Parent:** #761 - **Published:** 2026-10-23
**Reading surface:** ~7K

## Scope

Deliver one shared normalizer for free-text writes: Unicode NFKC normalization, control-character removal, whitespace collapse, and a maximum length. Apply it at the operator and partner free-text write boundaries touched by this batch, and record that no new HTML sink may be added except the existing static chart path.

- [ ] The normalizer performs NFKC normalization, removes control characters, collapses whitespace, and enforces a maximum length.
- [ ] Unit tests cover normalization, control characters, whitespace, maximum length, and idempotence.
- [ ] The operator and partner free-text write boundaries touched by this batch use the shared normalizer.
- [ ] A short design note records the no-new-HTML-sink rule and the existing static chart exception.
- [ ] No HTML parser or blanket sanitizer is added; React escaping remains the display rule.

## Blocked by

None - can start immediately.

## Read-list (in order)

1. docs/standards/security-phii-standards.md
2. docs/standards/coding-standards.md
3. The partner operator free-text request models and the care decision reasons.
4. The existing error envelope and validation patterns.

## Do NOT read

- docs/archive/
- The frontend chart internals.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend`
- `npm run lint`
- `npm run typecheck`

## Handoff notes

- Do not alter clinical meaning beyond normalization.
- Do not add a sanitizer library.
- Keep the helper small and pure so later write tickets can reuse it.
- Read only the named sections and grep for interfaces by name. Do not read whole files, unrelated modules, or generated files.
