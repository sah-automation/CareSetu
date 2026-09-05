# ADR-0012: Directory indexed per partner, one geo point - multi-location deferred

**Status:** accepted
**Date:** 2026-09-05
**Traceability:** `FEAT-004`, `FEAT-005`, `MOD-002`, `REQ-008`.

## Context

The directory's unit of search needs a canonical shape. Two shapes are possible: index the partner once using their practice location (the `practice_latitude`/`practice_longitude` already collected at registration), or index the partner once per practice location so a doctor with two clinics appears twice. Phase 5 stores exactly one practice location and one credential set per partner, and Phase 6 has no secondary-location data source.

## Decision

**One directory entry per `[Active]` partner, keyed by `partner_id`, carrying a single geo point** - the partner's practice location as recorded at registration. Multi-location (one partner, several entries/practice points) is a deliberate future extension, not a Phase 6 shape.

## Consequences

- Search, profile, and expired-credential handling all key on one `partner_id`; there is no per-location credential logic Phase 6 must build.
- A future multi-location launch extends the schema (a locations table and one entry per location) without renames: the directory entry pointed at a partner already models "one accessible face of a partner".
- The patient currently sees the truth available today - a partner has one address, one specialty, one credential set.
