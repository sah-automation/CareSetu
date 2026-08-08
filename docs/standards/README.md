# Standards — Hierarchy & No-Conflict Rule

**Scope:** How `docs/standards/*` relate to the project plan, and the rules they must obey.

## Layer order

```
docs/prd/project-prd.md          → WHAT we build (features, NFRs, decisions)
docs/architecture/*              → HOW it is structured (system context, modules)
docs/roadmap/implementation-roadmap.md → IN WHAT ORDER we build it (phases)
docs/standards/*                 → HOW TO SATISFY the above, top-level rules only
```

## Rules

1. **Top-level only.** Standards set _rules_ for satisfying the plan — conventions, contracts, and discipline. They never introduce features, SLAs, or architecture that the plan does not claim.
2. **Never conflict.** Standards reference the plan as upstream (`PRD`/`ARCH`/`NFR` ids) and never override it. If a standard and the plan disagree, the plan wins and the standard must be fixed.
3. **Surface conflicts, don't override.** If a change would contradict the plan or an ADR, call it out explicitly (same rule as `docs/agents/domain.md`) instead of silently editing around it. Resolving a conflict may reopen a PRD decision (`CFL/GAP/AMB`) — never a silent standard tweak.
4. **Reference, don't duplicate.** Standards point at the plan's sections and IDs rather than restating them, so the plan stays the single source of truth.

## Conventions

- One concern per file; keep each under ~80 lines, prescriptive and checkable.
- Update the AGENTS.md "Standards" section when adding/removing a standard file.
