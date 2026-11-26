# ADR-0021: Profile save moves the public directory position

**Status:** accepted
**Date:** 2026-09-30
**Decides:** Where a partner's public directory position comes from after registration - it follows the address the doctor declares and saves, rather than freezing at the point captured at sign-up. One entry per `[Active]` partner and one geo point per entry are unchanged; what changes is that the point is correctable.
**Traceability:** `FEAT-004`, `FEAT-005`, `MOD-002`, `MOD-012`, `ADR-0012`, `batch #599`. Implemented by #607 (the one shared directory-entry refresh), #608 (the practice section write as a second caller of it), #609 (the address section write that derives the position) and #611 (retiring the whole-form write that used to be the only path).

## Context

The existing decision in ADR-0012 - "Directory indexed per partner, one geo point - the partner's practice location as recorded at registration" - assumed the public directory position would remain fixed to the point recorded at registration. Under the redesigned doctor profile, the doctor edits their practice address in the Profile surface and saves sections independently. If the directory's geo point never updates after a private save, the public directory can diverge from the declared, correctable practice address, and the "one geo point" decision becomes conflated with "never correctable".

## Decision

A save of the practice/address sections in the doctor profile writes the derived practice position for the public directory entry. The directory entry's geo point reflects the current declared address at the time of the section save, rather than remaining frozen at registration.

Both section writes reach the entry through the one shared refresh (`refresh_directory_entry`, #607), each inside its own transaction:

- the **address** write, which is where the position is derived in the first place - the declared PIN resolves against `partner_pin_centroids` (ADR-0022), and the resolved centroid is both written to the profile row and copied onto the entry;
- the **practice** write, which moves no position but changes the **specialties selection**, so it must copy the selection onto `partner_directory_index.specialty` or directory search keeps filtering on the pre-save value while the doctor's public profile - which reads the profile row - already shows the new one. Two public surfaces disagreeing about one doctor is the failure this closes.

The refresh writes only the position and the selection. It never writes `is_active` and never touches any credential verification: the listed flag stays behind the operator approval transition (ADR-0008), so a doctor editing their own profile cannot list themselves.

Supersedes: the aspect of ADR-0012 that treated the directory's single geo point as immutably "as recorded at registration" for the purpose of post-activation profile edits. ADR-0012's other constraints - one directory entry per `[Active]` partner, one geo point - remain intact. A correctable pin matters more than a frozen one.

## Consequences

- The directory index is updated whenever the declared address changes and is saved, keeping the public directory aligned with the current practice location.
- The selection a doctor declares on the Practice card is published to the directory entry by that same save, so a specialty filter reflects it immediately rather than at the next address save.
- The "one geo point" rule stays; there are no new multiple-location semantics introduced.
- Section saves remain independent; updating the address does not force unrelated sections to save.
- The directory refresh remains gated by activation state: only `[Active]` partners appear in the directory.

## Amendment precedent

This decision follows the supersession/clarification pattern established by ADR-0016 (Traceability noting supersession of the earlier blueprint assumption) and ADR-0005 (documented amendments). ADR-0012's body is left intact and now carries a forward pointer to this ADR, so a reader who starts at ADR-0012 is directed here rather than left reading the pre-redesign rule as current.
