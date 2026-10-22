# Brief - 678 Dashboard: time-based greeting and profile-status card

**Ticket:** #678 · **Parent:** #673 · **Refreshed:** 2026-10-09
**Reading surface:** ~2.6K tokens (budget 10K) - within budget

## Scope

The dashboard opens with a personal, time-based greeting using the doctor's own name from the profile projection (honorifics stripped for the first-name form; a name-free greeting while the profile is still loading, never a blank or skeleton heading) and today's date beneath it. A profile-status card shows the verified indicator, specialties and fee, and calls out anything missing or incomplete (unverified, no fee, no about text, no clinic name), linking to the doctor profile to fix it. Both read from one widened profile read - the existing dashboard read currently used only for the fee.

## Acceptance criteria

- [ ] The greeting is time-based (morning/afternoon/evening) and uses the doctor's name from the profile
- [ ] Honorifics are stripped for the first-name form; a name-free greeting shows while the profile is loading
- [ ] Today's date renders under the greeting
- [ ] The profile-status card shows the verified indicator, specialties and fee
- [ ] The profile-status card lists completeness hints for unverified / no fee / no about text / no clinic name
- [ ] The profile-status card links to the doctor profile
- [ ] The greeting and the card share the dashboard's single profile read
- [ ] Every new string ships in both English and Hindi (parity preserved)
- [ ] `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` pass

## Read-list (in order)

1. The dashboard page's profile read effect and fee state - the isolated `fetchDoctorProfile` read currently feeding only the fee; widen it to hold the whole `DoctorProfileView`. (~400 tokens)
2. `DoctorProfileView` in the doctor API client - the fields used: `practice_name` (the doctor's own name despite the column name), `clinic_name`, `specialties`, `verified`, `about`, `consultation_fee`. (~400)
3. The doctor-profile page and the profile-completeness banner as prior art - the existing verified/specialties/fee presentation and the completeness-hint idiom to match. (~600)
4. `DoctorProfileContext` (`useDoctorProfile`/`useOptionalDoctorProfile`) - understand the layout-level source, but the spec keeps the dashboard's own read; do not adopt the context here. (~300)
5. The `doctorConsole` and `doctorProfile` i18n namespaces in both locales. (~400)
6. The dashboard test blocks. (~500)

## Do NOT read

- The backend.
- The profile write sections (`components/doctor/profile/*`) beyond the completeness banner as prior art.
- `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - confirmed green 2026-10-09 (134 files / 2157 tests passed).
- `npm run typecheck:frontend` - confirmed green 2026-10-09.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend` - greeting, date and profile-status card assertions.
- `npm run lint`
- `npm run typecheck`

## Handoff notes

- **One profile read on the dashboard.** The spec explicitly reuses the dashboard's existing profile read (not `DoctorProfileContext`) so the greeting, the status card and the fee tile share one request. Widen the existing effect rather than adding a second read.
- **Honorific stripping is deliberate.** `practice_name` is the doctor's own name; strip "Dr."/"Dr" and similar honorifics for the first-name form. While the profile is still loading, render a name-free greeting - never a blank line or a skeleton heading.
- **Completeness hints are additive guidance**, not errors: unverified, no fee, no about text, no clinic name each get a hint and the card links to `/doctor/profile`.
- **No em-dashes anywhere** (lint-gated) - use simple dashes.
