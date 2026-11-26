# Brief - 03 Counterparty display name and resolver seam on the consent read models

**Ticket:** #648 · **Parent:** #645 · **Refreshed:** 2026-10-06
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

The consent module's read models carry an optional, nullable counterparty display name, populated through an injected resolver seam rather than an import. The name is an enrichment of an id, never the authorization: a missing name must never affect whether a grant is live, and the counterparty id stays on the wire so the receipt keeps its precision. The consent module keeps no knowledge of any other module - the seam is optional and keyword-only, so facade unit tests that construct it with only an engine keep working, and the binding that supplies real names lives at the composition root.

Whatever the seam answers, it degrades: unbound resolver, resolver exception, and an unresolvable counterparty all leave the field null, and a failure logs a warning naming the counterparty **type** only - never the id, never PHI.

## Acceptance criteria

- [ ] The consent read model and the egress-log entry model each gain one optional, nullable counterparty display-name field. Neither is required, and neither changes the authorization decision.
- [ ] The consent facade gains an optional keyword-only resolver callable taking a counterparty type and id and returning a nullable name. Constructing the facade with only its engine still works.
- [ ] The consent module imports no other module to obtain the name.
- [ ] With the seam unbound, both reads still answer with the field absent.
- [ ] A resolver exception degrades to the field absent and logs a warning that names the counterparty type only - no counterparty id, no PHI.
- [ ] A resolver that answers puts the name on both the consent read and the egress-log read.
- [ ] Existing grant, revocation, and egress tests continue to pass with the seam unbound.

## Read-list (in order)

1. The `#645` spec's "Consent counterparty display names (MOD-004 + composition root)" block - the nullable-and-optional reasoning, the resolver-seam-not-an-import rule, and the degradation sentence. This ticket builds the seam and the models; the _rules_ that populate it are #649's job. (~900 tokens)
2. `ConsentFacade` - the constructor, and the read methods that produce `ConsentView` (`ConsentDecision`, `ConsentEventView`, `ConsentView`, `ConsentLog`, `CounterpartyGrantView`, `EgressLogEntry`, `EgressLog`), plus `list_egress_log` and the grant / revoke / decline transitions. (~2K)
3. The consent facade unit test module and the consent egress test module - what must keep passing with the seam unbound, and where the new with-resolver cases land. (~1.2K)
4. The consent route test module - the stubbed facade, and the note that the egress-log route currently has no test at all in that file. (~1K)
5. `docs/standards/coding-standards.md` - the module isolation rule: no cross-schema imports, no cross-schema SQL, no cross-schema foreign keys; `facade.py` and outbox events are the only legal seams. (~700 tokens)
6. `docs/architecture/internal-modules.md` - the consent module spec. (~700 tokens)

## Do NOT read

- `docs/archive/`.
- The partner module. Its provider-profile seam is bound in #649; this ticket only defines the shape consent expects - a callable of counterparty type and id returning a nullable name.
- The intake module, including the AI counterparty id constant. The id check that precedes the type parse is #649's and #653's work, not yours.
- The prescription facade and its attribution resolver - the _pattern_ is named in the spec, but you do not need to read the care module to define an optional keyword-only callable.
- The frontend app.
- The consent schema and SQL.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - **currently green: 2867 passed.**
- `npm run typecheck` - **currently green.**

The frontend unit suite has one **pre-existing** failure unrelated to this work: `record/page.test.tsx > RecordPage access history > shows an empty state when there is no access history` cannot find "No access yet.". It fails on the untouched tree; ignore it.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` - new with-resolver / unbound / exception cases green; every existing grant, revocation, and egress test still green.
- `npm run typecheck` - mypy `--strict` catches the optional-callable signature at both the definition and every construction site.
- `npm run lint` - the module-boundary hook is what proves "the consent module imports no other module".

## Handoff notes

- **The seam is optional so existing tests keep working.** Every consent facade construction site in the codebase passes only the engine. Making the resolver a required positional argument would break all of them, which is why the spec calls it keyword-only and optional. Check every construction site in the tree, not just the tests you can see.
- **Nullable and optional are not the same.** Optional means the caller may omit it on the wire; nullable means the value may be absent after resolution. Both are required here: the frontend's three-step fallback depends on the field being _present and null_ rather than sometimes-missing.
- **Degrade at the seam, not at the call site.** The spec puts the try/except around the resolver invocation inside the facade, so every read path degrades identically. Catching per call site is how one surface ends up failing where another degrades.
- **The warning line is an audit surface.** It names the counterparty **type** and nothing else. Adding the id, or the patient id, turns an observability signal into a leak - this is an explicit acceptance criterion, and a reviewer will look for the exact log call.
- **This is not where the resolution rules live.** Do not put the AI check or the doctor-type parse here. Consent receives a callable that already answers; putting the rules in the module is exactly the cross-module coupling the spec forbids. #649 binds them at the composition root.
- **The `counterparty_id` field stays on both models.** The receipt cites lineage id plus version, and the id remains on the wire for that precision. The display name is added beside it, never in place of it.
