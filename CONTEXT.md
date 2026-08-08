# CareSetu — Build-Session Navigation Guide

**Read this file first in every session.** It tells you which docs exist, what to read for the work at hand, and what to deliberately skip.

## Doc inventory

| File                                     | Purpose                                                                                                     | Read when                                               | ~Tokens  |
| :--------------------------------------- | :---------------------------------------------------------------------------------------------------------- | :------------------------------------------------------ | :------- |
| `CONTEXT.md` (this file)                 | Navigation guide — what to read/skip                                                                        | Always (first)                                          | ~0.5K    |
| `docs/prd/project-prd.md`                | WHAT we build: epics, features (`FEAT-xxx`), NFRs, risks                                                    | Every build; the §4.x section for the features in scope | ~13K     |
| `docs/architecture/system-context.md`    | External actors (`ACT-xxx`) + third-party integrations (`EXT-001..004`)                                     | When touching integrations, actors, or boundary rules   | ~6K      |
| `docs/architecture/internal-modules.md`  | HOW modules work: per-module specs (`MOD-001..011`), sync matrix §4.1, event registry §4.2, traceability §5 | Every build; specs for the modules you touch            | ~14K     |
| `docs/roadmap/implementation-roadmap.md` | IN WHAT ORDER we build: per-phase specs (`PHASE-0..14`), phased traceability §3                             | Every build; the section for the current phase          | ~16K     |
| `docs/standards/*`                       | Top-level rules per area (coding, api, integrations, errors, security, AI)                                  | The relevant standard before working in its area        | ~2K each |

## Build-session protocol

Follow this order and stop when you have what you need:

1. **`CONTEXT.md`** — this guide.
2. **`docs/roadmap/implementation-roadmap.md`** → the section for the current phase (which modules/features it touches, its dependencies and risks).
3. **`docs/architecture/internal-modules.md`** → the spec(s) of the module(s) in scope.
4. **`docs/prd/project-prd.md`** → the `§4.x` epic / feature sections in scope (acceptance criteria, rules, edge cases).
5. **`docs/architecture/system-context.md`** — only if the phase touches external actors/integrations (its §3/§4).
6. **`docs/standards/*`** — the standard(s) relevant to the area you're editing.

Read only the sections you need. If a task stays confined to one module or phase, do not pull in unrelated sections.

## Cross-reference rule

The cross-reference matrices are **embedded in** `docs/architecture/internal-modules.md` (§4.1 sync, §4.2 events, §5 feature↔module↔storage) and `docs/roadmap/implementation-roadmap.md` (§3.1 feature↔module↔phase, §3.2 actor/interface↔phase, §3.3 module↔primary-build-phase). Read those sections whole when you need to trace an edge — they are the single source of truth for how parts connect. Do not invent new event names or module links; register changes there.

## Do NOT read

- **`docs/archive/`** — superseded by `docs/prd/project-prd.md`. Historical elicitation artifacts (`discovery-register.md`, `rgd.md`, `conflict-gap-report.md`) live there for reference only; the PRD is the single source of requirements.
- No other docs carry authoritative content beyond the files listed above.
