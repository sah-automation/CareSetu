# Brief - T06 Doctor channel information architecture

**Ticket:** #184 · **Parent:** #178 Wayfinder map: Top-level UI Blueprint · **Refreshed:** 2026-08-21
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

Decision question (verbatim): Top-level areas of the doctor channel: pre-summary review queue, pre-summary review screen (low-confidence forced-review UX), e-prescription drafting/approval, consult handshake marking, own profile/credential display, availability of patient consented-history views.

Resolution must produce: the doctor channel nav map with each area's key screens at wireframe-description level, the forced-review interaction for `low_confidence` pre-summaries, and the rx approval gate UX. Uses shell conventions from #182 as fixed input.

## Read-list (in order)

1. #182 closing comment - shell conventions (~0.5K)
2. `CONTEXT.md` Language section (pre-summary, transcription/structuring confidence, low_confidence flag, forced doctor review) - canonical vocabulary; do not drift (~0.7K)
3. `docs/prd/project-prd.md` §4.4 both features (`FEAT-008` consult handshake, `FEAT-009` e-prescription AI draft + doctor approval) (~3K)
4. `docs/prd/project-prd.md` §4.3.2 `FEAT-007` AI Clinical Pre-Summary Generation - what the doctor receives and the confidence gate (~1.5K)

## Do NOT read

- Patient/partner/operator epics, backend modules, roadmap, archive docs.

## Baseline verify (must pass before the first edit)

- None - read-only decision session; do not edit code.

## Done-verify (acceptance criteria → commands)

- Resolution comment on #184 with the IA; ticket closed
- Map #178 Decisions-so-far gains one line linking #184

## Handoff notes

- Persona-002: time-constrained local physician, prefers voice-note/photo input - queue-first, few-tap flows.
- A `low_confidence` pre-summary is unusable as rx draft input until a timestamped, attributed review is recorded - the UI must make that gate unmissable but not insulting.
- Consultation happens off-platform (`REQ-004`); the platform only marks the handshake - don't design video/chat.
