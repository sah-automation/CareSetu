# ADR-0021: Profile save moves the public directory position

**Status:** accepted
**Date:** 2026-09-30
**Traceability:** `FEAT-004`, `FEAT-005`, `MOD-002`, `MOD-012`, `ADR-0012`, `batch #599`.

## Context

The existing decision in ADR-0012 - "Directory indexed per partner, one geo point - the partner's practice location as recorded at registration" - assumed the public directory position would remain fixed to the point recorded at registration. Under the redesigned doctor profile, the doctor edits their practice address in the Profile surface and saves sections independently. If the directory's geo point never updates after a private save, the public directory can diverge from the declared, correctable practice address, and the "one geo point" decision becomes conflated with "never correctable".

## Decision

A save of the practice/address sections in the doctor profile writes the derived practice position for the public directory entry. The directory entry's geo point reflects the current declared address at the time of the section save, rather than remaining frozen at registration.

Supersedes: the aspect of ADR-0012 that treated the directory's single geo point as immutably "as recorded at registration" for the purpose of post-activation profile edits. ADR-0012's other constraints - one directory entry per `[Active]` partner, one geo point - remain intact. A correctable pin matters more than a frozen one.

## Consequences

- The directory index is updated whenever the declared address changes and is saved, keeping the public directory aligned with the current practice location.
- The "one geo point" rule stays; there are no new multiple-location semantics introduced.
- Section saves remain independent; updating the address does not force unrelated sections to save.
- The directory refresh remains gated by activation state: only `[Active]` partners appear in the directory.

## Amendment precedent

This decision follows the supersession/clarification pattern established by ADR-0016 (Traceability noting supersession of the earlier blueprint assumption) and ADR-0005 (documented amendments). ADR-0012's body is left intact; this ADR records the reversal of that specific rule for post-activation profile edits.
