# Brief - T05 Patient app information architecture

**Ticket:** #183 · **Parent:** #178 Wayfinder map: Top-level UI Blueprint · **Refreshed:** 2026-08-21
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

Decision question (verbatim): Top-level areas of the patient app (home, find care/directory, symptom intake, my record + consent surfaces, bookings/orders tracking, chronic metric logging, notifications inbox, profile completion flow) and how navigation between them works; what the post-first-login "complete your profile" experience is.

Resolution must produce: the patient nav map with each area's key screens at wireframe-description level, the first-login profile-completion flow (what's asked, what's skippable, what gates care actions), and the consent-moment UX pattern. Uses shell conventions from #182 as fixed input.

## Read-list (in order)

1. #182 closing comment - shell conventions (~0.5K)
2. `docs/prd/project-prd.md` §4.1.2 `FEAT-002` Longitudinal Health Record & Per-Action Consent - the record and consent model the UI must express (~2K)
3. `docs/prd/project-prd.md` §4.3 both features (`FEAT-006` voice/text intake, `FEAT-007` pre-summary) - the intake flow screens (~3K)
4. `docs/prd/project-prd.md` §4.9.1 `FEAT-018` Chronic Metric Logging & Follow-Ups - daily BP/sugar logging + due follow-ups (~1.5K)
5. `src/app/(dashboard)/patient/page.tsx` - current placeholder being designed over (~0.2K)

## Do NOT read

- Doctor/partner/operator epics beyond handoff points, backend modules, roadmap, archive docs.

## Baseline verify (must pass before the first edit)

- None - read-only decision session; do not edit code.

## Done-verify (acceptance criteria → commands)

- Resolution comment on #183 with the IA; ticket closed
- Map #178 Decisions-so-far gains one line linking #183

## Handoff notes

- Persona-001: moderate digital literacy, Hindi-first, 4G smartphone - big targets, minimal typing, voice-first where the PRD supports it.
- Per-action consent is the trust core (`FEAT-002`) - every care action names what record access it needs; design the consent moment once, reuse everywhere.
- Out-of-stock / delivery-failure choices arrive from partner flows (`FEAT-013`) - reserve a "decisions needed" surface on patient home.
- WhatsApp is notifications-only at launch; the in-app inbox (`FEAT-019`) is a first-class area.
