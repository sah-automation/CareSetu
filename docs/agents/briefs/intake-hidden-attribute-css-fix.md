# Brief - Fix intake pages hidden attribute CSS conflict

**Ticket:** #372 · **Refreshed:** 2026-09-09
**Reading surface:** ~3K tokens (budget 10K) - within budget

## Scope

Replace the HTML `hidden` attribute with conditional rendering (`{condition && <div>}`) on both voice and text intake pages to fix a CSS specificity conflict where Tailwind's `display: flex` overrides the native `hidden` attribute's `display: none` in the browser.

**Acceptance criteria:**

- Voice page: only mic button + duration counter visible on idle load
- Voice page: Pause/Stop appear only during recording
- Voice page: Play/Record Again/Submit appear only during preview
- Voice page: Structuring spinner appears only during pending
- Text page: textarea + voice-note attach visible on idle load
- Text page: Submit zone visible but button disabled when text is empty
- Text page: note recording/preview zones appear only at their respective stages
- Text page: Structuring spinner appears only during pending
- All 37 existing intake unit tests pass

## Read-list (in order)

1. Voice intake page component - the `hidden={condition}` pattern on control group divs that needs to change to conditional rendering (~553 lines)
2. Text intake page component - same pattern on control group divs (~463 lines)
3. Voice intake page tests - verify existing tests assert correct visibility behavior (~575 lines)
4. Text intake page tests - same verification (~592 lines)

## Do NOT read

- `lib/intake/voice.ts`, `lib/intake/api.ts`, `lib/intake/recorder.ts` - shared logic, unchanged
- `components/ui/button.tsx` - shared component, unchanged
- Backend code - no changes
- `docs/archive/` - superseded by PRD
- Prototype files - binding copy spec, not implementation

## Baseline verify (must pass before the first edit)

```bash
cd apps/frontend
npx vitest run --reporter=verbose "intake/voice/page" "intake/text/page"
# Expected: 2 passed (2), 37 passed (37)
```

## Done-verify (acceptance criteria -> commands)

```bash
cd apps/frontend
npx vitest run --reporter=verbose "intake/voice/page" "intake/text/page"
# Expected: 2 passed (2), 37 passed (37) - no regressions
```

## Handoff notes

- The fix is straightforward: replace `hidden={condition}` with `{condition && <element>}` on 8 control group wrappers across both files
- Voice page has 3 wrappers: `ctrl-record` (line ~418), `ctrl-preview` (line ~444), `ctrl-pending` (line ~480)
- Text page has 5 wrappers: `note-attach` button (line ~338), `note-recording` div (line ~354), `note-preview` div (line ~381), `submit-zone` div (line ~415), `ctrl-pending` div (line ~441)
- Tests use `expectVisible` helper which checks `not.toHaveAttribute("hidden")` - this still works after switching to conditional rendering (elements present = not hidden)
- The `note-attach` button on the text page is special: it uses `hidden={noteStage !== "idle"}` directly on the button element, not on a wrapper div. Wrap it with `{noteStage === "idle" && <button>}`
