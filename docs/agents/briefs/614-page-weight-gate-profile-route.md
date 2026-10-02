# Brief - 614 Add the doctor profile route to the page-weight budget gate

**Ticket:** #614 · **Parent:** #599 · **Refreshed:** 2026-09-30
**Reading surface:** ~4.7K tokens (budget 10K) - within budget

## Scope

The profile page is not currently measured against the page-weight budget, so its cost is invisible. The two Radix dependencies this redesign adopts are the only new client-side runtime weight in the change, so the route joins the existing gate in the same change rather than afterwards.

Acceptance criteria (from ticket):

- [ ] The doctor profile route is added to the existing page-budget gate's channel list.
- [ ] The gate builds, serves and fails on overrun exactly as it does for its existing channels - this is a channel addition, not a new tool.
- [ ] The measured total for the profile route is reported, and if it is already over budget that is recorded as a finding this work fixes rather than as a blocker.

## Read-list (in order)

1. `CONTEXT.md` - the Build-session protocol and the Do NOT read section only, plus the one line of the "Doctor console & care loops" glossary block that names the doctor profile surface and the shared profile source. This is a one-line edit to a constant; the protocol is here so the implementer knows where the docs are and that `docs/archive/` is never read. (~0.9K tokens)
2. `docs/prd/project-prd.md` - the `NFR-003` row of the non-functional-requirements table (initial page load, the 1.5 MB page weight, the 1 Mbps downlink floor, and the explicit "no optimisation below this baseline" clause) and the row format around it. This is the requirement the gate exists to enforce and the number the budget constant must keep matching. (~0.8K tokens)
3. `docs/research/ui-component-library.md` - the Constraints recap carrying the same NFR-003 1.5 MB figure, the "Bundle-to-a11y ratio fits the budget" bullet from the recommendation, and the fourth guardrail that asked for a CI bundle-size check against that budget in the first place. Skip the comparison table and the per-library byte counts; they are settled history. (~0.9K tokens)
4. The page-measurement script, in full - it is under 200 lines and every part of it is either the thing being changed or the thing that must not change:
   - the `CHANNELS` array, the single line to edit, and its header comment recording which ticket added which channel (add yours in the same style);
   - `BUDGET_BYTES` and `BUDGET_LABEL` - the 1.5 MB figure and the label the report prints;
   - `fetchBuffer`, and specifically the two request headers: `Accept-Encoding: identity` (so the byte counts are uncompressed and comparable) and the `Cookie: caresetu_authed=1` guard-hint cookie, whose comment names the constant it must track and the ADR that introduced it;
   - `assetUrls`, the tag parser that finds `<script src>` and `<link rel="stylesheet" href>` and nothing else;
   - `measureChannel` (fetch the HTML, fetch every asset, total HTML plus assets, fail if a route yields zero assets) and `printReport` (the per-channel table and the "every channel within budget" rule);
   - `main` (build, pick a free port, start the server, wait for readiness, measure each channel, kill the tree in a `finally`) and the top-level exit-code handling.
     (~1.6K tokens)
5. The hint-cookie contract the script depends on: the `HINT_COOKIE` constant and its comment in the auth session module (a secret-free presence hint, not a credential), and the edge proxy's read of that cookie, which is what makes the bypass reach a route behind the guard. (~0.5K tokens)

## Do NOT read

- `docs/archive/` - superseded by the PRD.
- `docs/roadmap/implementation-roadmap.md` and `docs/architecture/internal-modules.md` - this ticket adds no module, no phase and no traceability row.
- The doctor profile page, the section shell, the identity band, and every other doctor-console or patient page. The gate measures the route's built output; nothing about what is rendered on it changes here.
- The six adopted shadcn primitives and the frontend bundle internals. You are not diagnosing _what_ is heavy here, only measuring it. If the number is over budget, the fix belongs to whoever owns the page.
- The Lighthouse gate script and the contract-check script. They are sibling gates with their own tickets, and they are not what this ticket changes.
- The Playwright end-to-end specs. The page-weight gate is a static build-and-serve measurement with no browser.

## Baseline verify (must pass before the first edit)

- `npm run lint` - cheap, and it is where the no-em-dash and whitespace rules catch a sloppy one-line edit before it becomes a review comment.
- `npm run typecheck` - no TypeScript changes here, but the script is CommonJS run under Node and the strict frontend check is the cheapest guard that the tree is in the state the brief assumes.

Both were verified green on this tree immediately before this brief was written; re-run only if the tree has moved.

**Deliberately not in the baseline: `npm run check:pages`.** See the first handoff note - the pre-change number is what done-verify produces, and running it twice costs a full production build each time.

## Done-verify (acceptance criteria to commands)

- `npm run check:pages` - the single command that answers all three criteria. It builds the frontend, serves it on a free port, fetches every channel with the guard-hint cookie and `Accept-Encoding: identity`, prints the per-channel table including the new doctor profile row, and exits non-zero if any channel is over budget. Paste the measured total for the profile route into the ticket's closing comment; that is the "reported" in the third criterion.
- Read the printed table, do not just the exit code: an over-budget profile route must be recorded as a finding this work fixes, not filed as a blocker. The parent says so explicitly, and the parent also says the two new Radix packages are the only new client-side runtime weight in the whole change - so an overage here is expected to be traceable to them, and saying so is the useful half of the finding.

## Handoff notes

- **`npm run check:pages` is slow, and it is slower than it looks.** It runs a full production frontend build, then starts the Next server, then polls a readiness probe every 250 ms for up to 60 s before measuring anything, then tears the process tree down. Budget several minutes. Do not run it in a loop while iterating - the edit is one array entry, so make it once, then run the gate once.
- **One blocker, and what it will have landed.** The ticket waits on the shadcn-primitives ticket, **#600**, with the reason spelled out: the measurement must land with the dependencies it is meant to police. By the time this ticket starts, the frontend manifest will carry two new Radix runtime packages (the switch and the toggle group) plus four pure-Tailwind primitives that cost nothing at runtime. The whole point of running the gate in the same change is that the number reported already includes them. If you find yourself measuring before those packages are installed, you have measured the wrong tree and the number is stale.
- **Correction to the shared recon, and it changes the shape of the edit.** The recon handed to the brief writers states that the doctor landing route is already measured. It is not. The live `CHANNELS` array holds the public root, the staff login, and the patient, partner and operator routes - **no doctor route at all**. So the doctor console has never been under this gate, and the profile route is the first doctor surface to join it. Add only the profile route, as the ticket and the parent both say. Adding the doctor landing route at the same time is tempting and defensible, but it is a second channel with its own number that nobody asked for in this batch, and a reviewer cannot tell an in-scope addition from scope creep. Note the gap in the closing comment and let the parent decide.
- **Judgement call, recorded: this is a channel addition, so the diff should be one line plus a comment.** The criteria say so twice. Do not parameterise `CHANNELS`, do not add a per-channel budget, do not split the report, do not add a filter flag, and do not touch `BUDGET_BYTES` - that number is the PRD's `NFR-003` figure and moving it would silently redefine the requirement the other four channels are measured against. If the profile route comes in over budget, the correct response is to record the finding, not to raise the ceiling.
- **Judgement call, recorded: the measured total is a floor, not a ceiling, and it is worth saying so in the report.** The asset parser matches `<script src>` and `<link rel="stylesheet" href>` and nothing else. A `<link rel="preload" as="script">` for a chunk the page will need is therefore not counted, and neither is anything a stylesheet `@import`s. That is a pre-existing property of the gate, identical for all five existing channels, so it is not this ticket's problem to fix - but it does mean a reported number near the budget has less headroom than it looks. Say so rather than presenting the total as exact.
- **The guard-hint cookie is what makes a doctor route measurable at all.** The profile route sits behind the auth guard, and the script sends `Cookie: caresetu_authed=1` precisely so the guard lets a request through. Two consequences: the script's comment naming the constant it must track and the ADR that introduced it is load-bearing, so if the cookie name or the ADR number ever changes, that comment is what fails; and the measurement is of the _guarded_ page served with a bypass cookie, which is the same shape every other channel is measured in. Do not add a real session, a seeded account or a login step to this script - that would change how the other four channels are measured too.
- **Relevant ADRs.** **ADR-0007** is the one this script's own comment cites for the guard-hint cookie, and reading the `HINT_COOKIE` constant's comment is enough to get the relationship; there is no need to open the ADR. The two ADRs this parent work writes are reserved as **0021** (a profile save moves the public directory position) and **0022** (the practice position is a PIN centroid, not a geocode), both owned by **#622**; neither affects a page-weight measurement. The one design decision that bears on the number is recorded precedent rather than an ADR: adoption of the shadcn primitives is strictly lazy and per feature, never a bulk addition, and the research note's guardrail is that every adopted component's cost must be visible at pull-request time - which is what this gate is.
- **Out of scope, do not drift into:** the Lighthouse gate, the contract check, the bundle analyser the research note suggested, any change to the budget figure, any per-route budget, the doctor landing route, and any attempt to reduce the profile page's weight. If the measurement shows an overage, this ticket reports it; the page-owning ticket fixes it.
