# Brief - 452 FE: case workspace - draft and edit prescription

**Ticket:** #452 · **Parent:** #438 · **Refreshed:** 2026-09-16
**Reading surface:** ~3.4K tokens (budget 10K) - within budget

## Scope

Prescription drafting in the case workspace: request an AI draft, edit the rx items, and save the revision. A hard-refresh of a pending case reloads the in-progress revision from the working-rx read so navigation mistakes are not data loss. Every care mutation from this screen sends the idempotency-key header via the shared helper.

AC:

- [ ] Doctor can request an AI draft for the case and edit the items
- [ ] Saving a revision persists the doctor's edits
- [ ] Refreshing a pending case reloads the in-progress prescription without losing work
- [ ] Care mutations issued from this screen carry the idempotency-key header
- [ ] All new copy is bilingual en/hi

## Read-list (in order)

1. The case workspace page from #451 (review stage) - the shell the drafting stage extends (~400 tokens)
2. Care API client + idempotency-key helper from #446 + the rx draft / revision-save endpoint signatures (existing backend) - the mutations this screen calls (~700 tokens)
3. Working-rx read client (#445 shape) - the reload seam (~300 tokens)
4. `CONTEXT.md` e-prescription / prescription source / draft snapshot / drafting cap glossary (~350 tokens)
5. Page + client vitest patterns + `lib/i18n/dictionaries.ts` doctorConsole block (~700 tokens)
6. Issue #438 user story 18 + "backend delta 5" reload rationale (~400 tokens)

## Do NOT read

- Approval/rejection/closure internals (that is #453), backend route code, patient pick flow, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - currently green (71 files, 801 tests).

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` - workspace and client tests: draft request, item edit, revision save, refresh-reload shows in-progress work, idempotency header asserted on care mutations; parity test passes.

## Handoff notes

- Blockers #445 (working rx read), #446 (prefactor), #451 (workspace) must be merged.
- Editing never touches the immutable draft snapshot - saving persists the working revision; the reload must come back from the working-rx read, not the snapshot.
- Keep the drafting-cap semantics client-visible only as UX; enforcement is backend.
