# Brief - 564 Design-token gate: extend to class attributes, correct the orphan token names

**Ticket:** #564 · **Parent:** #560 · **Refreshed:** 2026-09-27
**Reading surface:** ~6.7K tokens (budget 10K) - within budget

## Scope

Extend the repository-wide design-token contract gate so it also inspects **class attributes**, not just stylesheet files, and land it on a clean tree.

The hole: `design-tokens.test.ts` walks `src/` but every one of its five describes reads `.css` files (plus `layout.tsx` for the next/font assertions). It reads **no `className` string and holds no rule mapping a Tailwind utility to a token.** So a component can name a colour token that does not exist, no utility is emitted, and the text silently falls back to the browser default against whatever surface is behind it. That is how the revocation confirmation became dark-on-dark.

The rule: **every colour utility named in a component class list must resolve to a resolved design token.** A `text-` utility whose argument is not a font size is treated as a colour utility. A colour utility naming a framework-default palette entry, or an arbitrary inline colour value, is likewise rejected. The rule asserts only that every colour a component asks for is one the design system actually defines - it does not try to guess whether a class was a typo.

A scan of the current tree shows this goes red on four orphan token names across **fifteen** class sites (not one, and not fourteen - see the corrected counts below). All four are corrected in this ticket, so the gate lands on a clean tree with **no allowlist debt**.

### THE CRITICAL GATE-DESIGN FACT - do not get this wrong

**Resolution must be strict, full-path against the theme colour tree. A suffix/leaf match is BLIND to the reported defect.**

The reported bug's token is `on-txt`. It ends in the segment `txt`, which **is** a real token (`txt.DEFAULT` = `var(--txt)`). A leaf-matching gate resolves `on-txt` to `txt` and passes the exact bug the gate exists to catch. The same trap fires on the other three:

| orphan       | trailing segment that IS a real token                        | what a leaf-matching gate would do |
| ------------ | ------------------------------------------------------------ | ---------------------------------- |
| `on-txt`     | `txt`                                                        | matches `txt.DEFAULT` - pass       |
| `txt-strong` | `strong` (`accent.strong` exists, and `txt` has no `strong`) | matches `accent.strong` - pass     |
| `warm-text`  | `text` (`success.text`, `warn.text` exist)                   | matches `success.text` - pass      |
| `on-surface` | `surface`                                                    | matches `surface` - pass           |

So `text-on-txt` must resolve by walking the colour tree **path by path** (`accent.DEFAULT` / `accent.strong` / `page.bg` / `txt.sub` ...), and a path whose final segment is unknown is a failure even when its last segment alone is known. The self-test in the acceptance criteria exists to prove this: plant a token that merely shares a trailing segment with a real one and the gate must reject it.

### Spec excerpt - the rule being enforced

`docs/design/ui-blueprint.md` **§1.2 Palette** (heading at line 38), the closing sentence of the direction paragraph at line 40:

> All colors keep the existing token vocabulary in `apps/frontend/tailwind.config.ts`; component code references token names only.

That is the enforceable sentence. **There is no sentence anywhere in the blueprint that names or forbids "the framework default palette"** - do not go looking for one and do not cite a section that does not exist. The stock-palette prohibition is delivered mechanically instead: the project declares **only** `theme.extend.colors`, so the stock Tailwind palette is never part of the declared token vocabulary, and the gate enforces exactly that vocabulary. The `Tailwind ref` column of the §1.2 token table (e.g. `accent.DEFAULT` = teal-700) records which stock step each token was chosen from; it does not authorise naming the stock step directly.

Secondary source for the font-size carve-out, same file **§1.3 Typography** line 60 - the legal `text-*` size steps: `text-xs`, `text-sm`, `text-base`, `text-lg`, `text-xl`, `text-2xl`, `text-3xl`, `text-4xl`, `text-5xl`.

## The corrected site list (grep-confirmed 2026-09-27)

**Fifteen live class sites across four orphan names.** Every path is relative to the repo root; every line is a `className` / class-map value, never a comment or a doc string.

`text-on-txt` (2 sites) - the reported defect. `on-txt` exists in neither the colour tree nor `tokens.css`; only `on-accent` does. The surface is `bg-txt` (`#0f172a`), so today the text renders at the browser default against near-black. These two are the only `bg-txt` sites in the tree, and they are the only dark-surface toasts - `text-on-accent` (`#ffffff`) is the established dark-surface ink (24 existing uses; the operator sign-in submit button pairs `bg-primary` with it).

| file                                                                  | line | symbol                                                  | class                                                                                                      |
| --------------------------------------------------------------------- | ---- | ------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `apps/frontend/src/components/patient/profile/ConsentGrantsPanel.tsx` | 274  | `flash()` toast block, `data-testid="ps-consent-toast"` | `fixed bottom-20 left-1/2 z-50 -translate-x-1/2 rounded-lg bg-txt px-4 py-2 text-sm text-on-txt shadow-lg` |
| `apps/frontend/src/app/(patient)/patient/record/consent-log/page.tsx` | 359  | `{toast && (...)}` block, `data-testid="toast"`         | (identical class string)                                                                                   |

`text-on-surface` (**10** sites - the ground-truth estimate said ~9; it is 10). `on-surface` is not a token in either source. Concentrated in the staff sign-in form and the partner registration wizard, **both of which later tickets rewrite** - correct the class now, expect churn later.

| file                                                                 | lines              | class (abbreviated)                                          |
| -------------------------------------------------------------------- | ------------------ | ------------------------------------------------------------ |
| `apps/frontend/src/components/auth/staff/StaffLoginForm.tsx`         | 450                | `mb-4 text-sm text-on-surface`                               |
|                                                                      | 618                | `text-sm text-on-surface`                                    |
|                                                                      | 677, 695, 704, 723 | `mb-2 text-sm text-on-surface`                               |
| `apps/frontend/src/components/auth/staff/ProviderRegisterWizard.tsx` | 748                | `text-sm text-on-surface` (`data-testid="pr-confirm-phone"`) |
|                                                                      | 801, 818, 837      | `mb-2 text-sm text-on-surface`                               |

`text-warm-text` (2 sites) - there is no `warm-text`; the `warm` ramp is `DEFAULT` / `mid` / `soft` only. Both values sit in the same module-level map, adjacent to the one entry that already resolves.

| file                                                                | lines | symbol                    | class                         |
| ------------------------------------------------------------------- | ----- | ------------------------- | ----------------------------- |
| `apps/frontend/src/app/(patient)/patient/record/[entryId]/page.tsx` | 71    | `STATUS_TONE.below_range` | `bg-warm-soft text-warm-text` |
|                                                                     | 72    | `STATUS_TONE.above_range` | `bg-warm-soft text-warm-text` |

(`STATUS_TONE.in_range` at line 70 is `bg-success-soft text-success-text` - a **legit** pair, because `success.text` is a real token. It is the reason `warm-text` reads as plausible at a glance.)

`text-txt-strong` (1 site) - `txt` is `DEFAULT` / `sub` / `muted`; there is no `txt.strong`. (`accent.strong` is a different ramp.)

| file                                                       | line | symbol                        | class                                                                           |
| ---------------------------------------------------------- | ---- | ----------------------------- | ------------------------------------------------------------------------------- |
| `apps/frontend/src/components/patient/home/SearchCard.tsx` | 77   | `activeClass(active)` ternary | `bg-surface font-semibold text-txt-strong shadow-[0_1px_3px_rgba(2,6,23,0.12)]` |

**Correction rule for all fifteen:** substitute an **existing resolved token** that matches the site's contrast intent. **No token may be added, renamed, or given a new value** - the palette and typography in `tokens.css` and the colour tree in the tailwind config are untouched by this ticket. If no existing token expresses the intent, pick the nearest existing one; do not mint one.

### Out of the rule's reach - RECORD, do not fix

Four further orphans of the same class, seven sites. They are **not** `text-` utilities, the specified rule is deliberately `text-`-scoped, and widening it needs a decision that is not this ticket's to make. List them on the ticket as findings.

| orphan                  | sites                                                                                              | why it is an orphan                                    |
| ----------------------- | -------------------------------------------------------------------------------------------------- | ------------------------------------------------------ |
| `bg-bg-subtle`          | 3 - `apps/frontend/src/app/(patient)/patient/intake/[intakeId]/pre-summary/page.tsx:421, 648, 681` | no `bg` colour group; the theme spells it `background` |
| `bg-page`               | 2 - `apps/frontend/src/components/auth/staff/ProviderRegisterWizard.tsx:511, 644`                  | `page` has only `page.bg`                              |
| `border-warn-border`    | 1 - `apps/frontend/src/app/(patient)/patient/intake/[intakeId]/pick/page.tsx:173`                  | `warn` has only `warn.soft` and `warn.text`            |
| `border-success-border` | 1 - `apps/frontend/src/app/(partner)/partner/status/rejected/page.tsx:154`                         | `success` has only `DEFAULT` / `soft` / `text`         |

Also worth recording, same category, and also invisible to a `text-`-scoped rule: **`bg-black/80`** (1 site) and **`bg-white/20`** (1 site) are live framework-default palette entries. The `text-` scoping is exactly what keeps them out of this ticket; the detector must still be capable of rejecting a stock-palette colour (see the self-test), so that a future widening of the rule inherits a working check rather than a new one.

## Precedence risks - a blind regex will fail this ticket

Class-attribute scanning is a prefix-namespace problem, not a substring problem. These are the live false positives, with counts measured on the current tree:

1. **`shadow-*` is not a colour prefix.** `shadow-card` (x40) and `shadow-pop` (x1) come from `theme.extend.boxShadow`, not the colour tree. `shadow-sm` (x13), `shadow-md` (x1), `shadow-lg` (x4) are stock Tailwind. A colour-only resolution that claims the `shadow-` namespace fires on 59 sites.
2. **The radius scale is not a colour prefix.** `theme.extend.borderRadius` supplies `sm` / `DEFAULT` / `lg`; `rounded-md` (x123), `rounded-lg` (x153), `rounded-full` (x111) and the side variants (`rounded-l-md`, `rounded-t-lg`, ...) are the stock scale.
3. **Tailwind's `text-` prefix is overloaded.** Beyond font size it also carries **text alignment** - `text-center` (x24), `text-left` (x17), `text-right` (x12) - and, in the default v3 config, `text-transform`, `text-overflow`, `text-decoration`, `text-indent`, `text-shadow`, `text-opacity`. Aligning text is not naming a colour. Only `text-<something>` whose argument is not a font size and not one of these non-colour utilities is a colour utility.
4. **Stock Tailwind side/scale utilities under the border and ring prefixes.** `border-b` (x22), `border-t` (x29), `border-l` (x4), `border-r` (x3), `border-2` (x10), `border-dashed` (x8) are not colour utilities. `outline-none` (x4) and `divide-y` (x1) are not either.
5. **But `border`, `input` and `ring` ARE real colour aliases** in the tree (the shadcn bridge: `border` = `var(--hairline)`, `input` = `var(--hairline)`, `ring` = `var(--accent-border)`), and they are used live (`border-input` x7, `ring-accent-soft`, `ring-offset-background`). Do not blanket-exclude the `border-` / `ring-` namespaces to dodge risk 4.
6. **Comments and prose carry class-like tokens.** `apps/frontend/src/components/ui/button.tsx:10` and `apps/frontend/src/components/ui/dropdown-menu.tsx:12` both contain the literal phrase `bg-accent/text-accent-foreground` inside a `//` comment explaining a shadcn deviation. `text-accent-foreground` **is not a live class** and `accent.foreground` is **not** in the tree - so a detector that greps the whole file for `text-` tokens will false-flag these two comments. This is a live trap in the tree today; scope the scan to class-attribute strings (or make it comment-tolerant) and do not "fix" either comment. `NavItemLink.tsx:3, 9` similarly contain `text-bearing` in prose.
7. **Prefix shadowing: a candidate is a prefix of a real token.** `bg-page` is a prefix of the legitimate `bg-page-bg` (`page.bg`). Any candidate test that ends at a non-alphanumeric boundary will match the wrong one. Match on the full utility argument, not a prefix of it.
8. **Alpha modifiers and arbitrary values are separate axes.** `bg-primary/10`, `bg-hairline-soft/40`, `hover:bg-primary/90` and `shadow-[0_1px_3px_rgba(2,6,23,0.12)]` are all live. A colour utility may carry an opacity suffix; an arbitrary-value form (`text-[...]`, `text-[#fff]`, `text-[rgb(...)]`) is a rejection case, not a resolution case.

## Read-list (in order)

1. **The existing gate** - `apps/frontend/src/app/design-tokens.test.ts`, whole file. The pieces you must reuse or extend: `walkSources` / `sourceFiles` / `allSourceFiles` / `SELF` / `cssFiles` (the recursive discovery; note `allSourceFiles()` already matches `.css|tsx?` and `cssFiles()` deliberately excludes `tokens.css`), `colorLeaves` (the `theme.extend.colors` flattener - extend it into a path-preserving resolver rather than writing a second one), `definedVarNames` (the existing `--var` regex), and the `single palette source` describe's `every var() reference ... resolves` rule, which is the closest prior art for the shape of the assertion you are adding (~2.0K tokens).
2. **The resolved colour tree** - `apps/frontend/tailwind.config.ts`, `theme.extend.colors`, whole. Enumerate the paths: `accent.{DEFAULT,strong,soft,border}`, `warm.{DEFAULT,mid,soft}`, `success.{DEFAULT,soft,text}`, `warn.{soft,text}`, `danger.{DEFAULT,soft,border}`, `page.bg`, `surface`, `hairline.{DEFAULT,soft}`, `on-accent`, `txt.{DEFAULT,sub,muted}`, `scrim`, `background`, `foreground`, `popover.{DEFAULT,foreground}`, `primary.{DEFAULT,foreground}`, `secondary.{DEFAULT,foreground}`, `muted.{DEFAULT,foreground}`, `destructive.{DEFAULT,foreground}`, `border`, `input`, `ring`. Also read `theme.extend.borderRadius` and `theme.extend.boxShadow` - they are the reason risks 1 and 2 exist. Note the gate already imports this file directly (~0.9K).
3. **The single token source** - `apps/frontend/src/app/tokens.css`, whole (71 lines). Confirms the absence of `--on-txt`, `--on-surface`, `--warm-text`, `--txt-strong`, and shows the `ui-*` HSL triplet bridge (~0.8K).
4. **The rule being enforced** - `docs/design/ui-blueprint.md` §1.2 Palette, lines 38-52: the direction paragraph with the token-names-only clause, the token table (the authority on which tokens exist and which stock step each was picked from), and the migration note. Then line 60 only, for the legal `text-*` font-size steps (~0.6K).
5. **Prior art for self-testing a detector** - `apps/frontend/src/lib/i18n/dictionaries.test.ts`: the hand-rolled recursive differ `parityProblems` (returns a `string[]` of `"<path>: <reason>"` findings rather than throwing) and the `parity detector self-test (#194 red/green proof)` describe, which feeds five deliberately broken copies through the _same_ checker and asserts the exact finding string. **Your detector's self-test must follow this pattern** - same function, planted broken input, asserted exact message - so the failure mode stays demonstrable on demand rather than only in the moment it was caught (~1.2K).
6. **How class strings actually arrive** - the `cn` helper at `apps/frontend/src/lib/utils.ts` and the `cva(...)` variant block in `apps/frontend/src/components/ui/button.tsx` (the `buttonVariants` base string plus the `variant` / `size` maps). These are the carriers: a bare `className="..."`, a `cn("...", className)` composition, a `cva` variant string, and a module-level `Record<string, string>` class map like `STATUS_TONE`. Your scan has to see all four, because two of the fifteen orphan sites live in a class _map_ rather than a `className` attribute (~0.7K).
7. **The fifteen sites themselves** - already itemised above with file, line, and exact class string. Grep each of the four names to re-confirm the line numbers on the current tree; do not read the surrounding components (~0.5K).

## Do NOT read

- `docs/archive/` - the PRD supersedes it.
- `docs/prd/project-prd.md`, `docs/architecture/*`, `docs/roadmap/*`, `docs/adr/*` - this ticket touches no module, no event, no API, no schema, and no ADR. Nothing there constrains the work.
- The rest of the blueprint. §1.2 and the single §1.3 line above are the whole slice.
- The **bodies** of `StaffLoginForm.tsx` and `ProviderRegisterWizard.tsx` beyond the four and six class lines named above. You are changing a class name, not a form; later tickets rewrite both files. Do not read the tests for either.
- `ConsentGrantsPanel.tsx`, the consent-log page, the record entry page and `SearchCard.tsx` beyond the class lines and their immediate enclosing map / ternary.
- Every other `apps/frontend/src` file. The gate is a repository-wide rule; you do not need to have read the tree to write it.
- Backend code, migrations, e2e specs, `docs/standards/*` (no standard in this repo covers a frontend test gate).
- `components/ui/*` beyond `button.tsx`'s variant block. In particular do not go "fixing" the `text-accent-foreground` mentions in the `button.tsx` / `dropdown-menu.tsx` comments - they are prose about a deviation, not classes.

## Baseline verify (must pass before the first edit)

The suite is **red on the untouched tree at brief time** - do not assume a green starting point.

- `npx vitest run src/app/design-tokens.test.ts --root apps/frontend` - the fast loop for this ticket alone. **Confirmed green 2026-09-27: 1 file, 10 tests passed, 3.4s.** This is the loop you iterate in; use it, not the full suite.
- `npm run test:unit:frontend` - **confirmed RED 2026-09-27: 13 failed, 1519 passed (1532), 3 files, 286s.** The failures are the two blockers, plus one flake:
  - `src/components/auth/staff/StaffLoginForm.test.tsx` - 10 failures (mock hygiene / dead-mock contract). **This is #562.**
  - `src/components/auth/otp/PatientAuthWizard.test.tsx` - 2 failures (done-screen countdown). **This is #563.**
  - **One third-file failure, and its identity moves.** It is a load flake - a 5s `Test timed out` under a parallel full-suite run - and **not covered by #562 or #563**. Do not treat any one file as _the_ flake. Re-measured 2026-09-27 at the same commit (`b6864ea`): run 1 timed out in `src/app/(doctor)/doctor/cases/[caseId]/page.test.tsx` (_"renders the case stage chip for the pre-summary stage"_), run 2 in `src/app/(patient)/patient/profile/page.test.tsx` (_"previews the stored photo rather than showing the opaque ref"_), and an earlier run in `HealthBackgroundZone.test.tsx`. The total is a stable 13; the third file is not. Name whatever is red, by file and test, in the baseline you record - and if anything from that set is still red after the blockers land, say so on the ticket rather than absorbing it here.
- **Gate:** #562 and #563 are the blockers and must be closed before the first edit, because "the full frontend unit suite green" is a done-verify for this ticket and you cannot attribute a red suite to your own change on a red baseline. The token gate file itself is green now, so the _new_ rule can be written and iterated on immediately; do not confuse "the fast loop is green" with "the blockers are done".
- `npm run lint` - confirmed green 2026-09-27 (all 17 pre-commit hooks pass, including the no-em-dash gate).
- `npm run typecheck` - confirmed green 2026-09-27 (mypy strict: 251 files; `tsc --noEmit`: clean).

## Done-verify (acceptance criteria -> commands)

- `npx vitest run src/app/design-tokens.test.ts --root apps/frontend` - the gate suite, green.
- `npm run test:unit:frontend` - the full frontend unit suite, green (#562 + #563 closed).
- `npm run lint`, `npm run typecheck`.

### Acceptance criteria as a checklist

- [ ] The gate fails on every one of the four orphan token names **as they stand today**, and the failure names the file, the utility, and the token that was expected. (Prove it: land the detector first, run it against the uncorrected tree, capture the red output on the ticket, _then_ fix the sites.)
- [ ] The gate passes once all four orphans are corrected at **every** class site, with **no allowlist** of known-bad entries. No `KNOWN_BAD`, no `skip`, no inline suppression comment.
- [ ] Resolution is **strict full-path** against the resolved design tokens. A deliberately planted token that merely shares a trailing segment with a real one is rejected - `on-txt` is the canonical shape to plant, since its trailing `txt` is real. The detector must also reject a `text-` colour utility naming a framework-default palette entry and one carrying an arbitrary inline colour value.
- [ ] The gate's own detector is **self-tested the way the bilingual parity gate's is**: the same checker function, fed deliberately broken input, asserting the exact finding string - not a parallel reimplementation and not a hand-written expectation.
- [ ] Tokens outside the colour tree that are legitimately resolved are **not** flagged: the card and pop elevation shadows, the radius scale. The rule is about colour and must not fire on the rest of the token set.
- [ ] The fifteen sites are corrected by substituting an **existing resolved token**. No token is added, renamed, or given a new value; the palette and typography in `tokens.css` and the colour tree are byte-identical afterwards.
- [ ] The blueprint's token-names-only rule is cited **by section** (`docs/design/ui-blueprint.md` §1.2 Palette) in the gate's header comment, alongside the `#564` ticket reference, matching the existing `#193` / `#195` citation style in the file.
- [ ] The four out-of-reach orphans (`bg-bg-subtle`, `bg-page`, `border-warn-border`, `border-success-border`) and the two live stock-palette colours (`bg-black/80`, `bg-white/20`) are **recorded on the ticket as findings**, not fixed, not allowlisted, and the rule is not widened to cover them.

## Handoff notes

- **The strict-resolution fact is the whole ticket.** Three of the four orphans have a trailing segment that is a real token, so any leaf- or suffix-matching implementation produces a gate that passes the reported bug. If your first detector version passes on `on-txt`, it is wrong regardless of how clean the suite looks.
- **Prove red before green.** The site list is small and mechanical, so the temptation is to fix the classes first and then write the detector against a clean tree - which yields a gate with no evidence it ever detects anything. Write the detector, run it, capture the four failures on the ticket, then correct.
- **The self-test is the acceptance criterion that cannot be faked.** A detector with no self-test can be green for the wrong reason (leaf matching, over-broad scope, or a scope so narrow it reads nothing). The planted-token self-test plus the four negative self-tests from the parity gate's pattern are what make the green meaningful. Follow `parityProblems` structurally: a pure function returning `string[]` findings, exercised by both the positive and the negative tests.
- **Class maps, not just `className` attributes.** Two of the fifteen sites are values in a module-level `Record<string, string>` (`STATUS_TONE`), one is inside an `activeClass(active)` ternary, and eight are in `cva` variant strings in the shadcn primitives. A scan that only matches `className="..."` will miss three of the four names' sites and land green on a broken tree.
- **Do not touch the two shadcn comment lines.** `button.tsx:10` and `dropdown-menu.tsx:12` mention `text-accent-foreground`, which is neither a live class nor a real token. They are prose explaining why the app deviates from upstream. If your detector flags them, the detector is over-broad - fix the detector, not the comments.
- **The two `bg-txt` toasts are the only dark-surface toasts in the tree**, and `text-on-accent` (`#ffffff`) is the only resolved ink meant for a dark surface (the operator sign-in submit already pairs `bg-primary` with it). That is the obvious substitution for `text-on-txt`; the other thirteen sites are secondary/muted body text, so the existing `txt.sub` / `txt-muted` / `hairline` family is where their replacements live. Judge each on contrast intent, not by symmetry.
- **`text-txt-strong` at `SearchCard.tsx:77` is an active-tab style on `bg-surface`**, so the replacement is a resolved `txt.*` or `accent.*` token that reads on a white surface - not a muted one.
- **Record, do not fix, the non-`text-` orphans.** Seven sites across four names plus two stock-palette `bg-` utilities. Widening the rule to `bg-` / `border-` is a real decision with real consequences (`border-b` vs the real `border` colour alias, `bg-page` vs `bg-page-bg`) and it is not this ticket's call. Post them as findings and let the parent spec decide.
- **Two blockers, still open at brief time** (#562, #563). The gate file is green independently, so the detector work can proceed; the full-suite done-verify waits on them.
- **A third failing file is not in scope**: one suite times out at 5s under full-suite load. Pre-existing, unrelated, and flaky - and its identity moves between runs, so name whatever is red by file and test rather than expecting a particular one. Mention it if it survives the blockers.
- **No em-dashes anywhere** (lint-gated by the `no-em-dash gate` pre-commit hook) - use simple dashes. Comments in the repo follow this too.
- **This brief is the contract.** Read it, not the world. Grep for line numbers; do not read the components.
