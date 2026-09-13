# Brief - T395 Voice intake: play-preview button active 'Playing...' state

**Ticket:** #395 · **Parent:** n/a (issue body is the spec) · **Refreshed:** 2026-09-13
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

The "Play preview" control on the voice intake recorder page becomes a playback-state toggle. While the recorded clip plays, the button shows an in-progress state (spinning loader icon, "Playing..." label, emphasized accent fill) and stays clickable so the patient can stop playback early. When playback completes on its own, or is stopped by a second click, re-record, submit, or page teardown, the button reverts to the standard "Play preview" look. The voice intake stage machine (`idle -> recording -> preview -> pending -> poor/done`) is untouched; this is a playback substate of the preview stage only.

Acceptance criteria (synthesized from the ticket's user stories and decisions):

- [ ] Clicking "Play preview" in the preview stage starts playback, swaps the button to an active "Playing..." state (spinner + accent style), and keeps the button enabled
- [ ] Clicking the button again while playing stops playback and reverts it to "Play preview"
- [ ] When the clip ends on its own, the button reverts to "Play preview" without any user action
- [ ] Re-record, submit, and page unmount all stop in-flight playback, clear the active state, and detach listeners - no stale "Playing..." state, no leaked listeners or object URLs
- [ ] The new "playing" label exists in both English and Hindi over the voice dictionary namespace and passes the i18n parity check
- [ ] The playing state is reflected to assistive technology (updated accessible label / busy signal); the button is never disabled by the playing state
- [ ] Playback behavior (toggle on, stop, auto-revert on end, clear on re-record/submit/unmount) is covered by a regression test in the existing voice page suite

## Read-list (in order)

1. The ticket body #395 (this spec) - problem, solution, all user stories, implementation + testing decisions (~3K)
2. The `VoiceIntakePage` component and its playback behavior - the preview-stage playback handler, the object-URL create/revoke teardown path it shares with re-record and submit, the preview controls render block, and the page's unmount handling. Also note the existing in-button spinner convention already used by this page's submit-pending state (~4K)
3. The `Button` component primitive - its variants/sizes and its `loading` prop (renders the in-button spinner AND disables the button). The ticket deliberately does NOT use `loading` because it disables the stop-early click; the spinner is rendered inline instead. The accent classes for the playing-state fill are already used in-page by the mic button (`bg-accent` / `text-on-accent`) - no theme-file reading needed (~1K)
4. The voice dictionary namespace (English + Hindi) - the existing `play` label; add a sibling `playing` string beside it in both languages (~1K)
5. The voice intake constants module - the `VoiceStage` enum and the preview stage semantics the substate refines (~1K)
6. The voice intake page test suite - its existing module-seam mocks (microphone recorder, intake API, language context), its take-recording helper, and the describe blocks the new tests extend. jsdom cannot play audio, so it fakes the recorder; the new tests add an `Audio`/`HTMLMediaElement` fake that records `play`/`pause` calls and lets tests dispatch synthetic end events (~2K)

## Do NOT read

- `docs/archive`, backend internals, or the text-intake / review / pre-summary pages
- The full i18n dictionary file beyond the voice namespace
- Tailwind config or `tokens.css` - the accent styling to reuse already appears in-page on the mic button
- The microphone recorder module (recording-only; playback never touches it)

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - voice intake page suite is 18/18 green; the full suite shows 789-790 pass with 3-4 pre-existing flaky failures in auth/home/choose-role and operator-verification paths that vary run to run and are unrelated to voice intake (re-run if the only failures are those)
- `npm run typecheck:frontend` - clean (verified 2026-09-13)

## Done-verify (acceptance criteria to commands)

- `npm run test:unit:frontend` - the new playback tests pass alongside the existing 18 voice page tests
- `npm run typecheck:frontend`
- `npm run lint:frontend`

## Handoff notes

- Root cause this fixes: the current playback handler starts `play()` and returns without attaching any listeners, so nothing ever knows playback is active or ended - hence the static button.
- Do not use the Button `loading` prop: it disables the button and removes the stop-early affordance the ticket requires. Render the spinner inline in the button children.
- Re-record and submit already share one audio-teardown path (`revokeAudioUrl`); the new `play`/`pause`/`ended` listeners must be detached inside that same path or audio keeps playing after the stage leaves preview. Page unmount needs the same teardown.
- The test must fake `Audio`/`HTMLMediaElement` (jsdom cannot play). Prior art in the suite: the microphone recorder is already faked at the module seam.
