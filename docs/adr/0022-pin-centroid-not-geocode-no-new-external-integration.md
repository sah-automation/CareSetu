# ADR-0022: Practice position is a PIN centroid, not a geocode

**Status:** accepted
**Date:** 2026-09-30
**Traceability:** `FEAT-004`, `FEAT-005`, `MOD-002`, `MOD-012`, `ADR-0021`, `batch #599`.

## Context

The redesigned profile collects a structured practice address and a PIN. The directory requires a single reproducible geo point for each active partner. Possible approaches include interactive map pin selection, reverse/forward geocoding services, address autocomplete, and browser geolocation - each introduces an external dependency, potential cost, and privacy/accuracy variability, particularly in peri-urban areas like Daltonganj. The platform's integration discipline (see `docs/standards/third-party-integration-standards.md`) requires that adding an external integration update the whitebox registry and is not introduced silently.

## Decision

The practice position is stored as a **PIN centroid** derived from the declared PIN (using the bundled centroid dataset), not as a live geocode from an external service. The directory's single geo point is the derived centroid corresponding to the declared PIN at save time.

## Rejected alternatives

- **Interactive map pins:** adds UI complexity, client-side map weight, and a map provider dependency without addressing the core need for a reproducible, testable position.
- **Geocoding services:** creates a new external integration (`EXT-xxx`), network latency, quota/cost, and cache consistency; requires registry updates and is not justified for this scope.
- **Address autocomplete:** external API dependency with similar integration/cost implications and does not by itself yield a canonical centroid.
- **Browser geolocation:** device-reported position is non-deterministic, permission-dependent, and unreliable in peri-urban environments; cannot be treated as the canonical practice location.

## Reasoning

- **No new external integration created.** Consistent with integration discipline: avoiding a new `EXT` entry means no change to the external registry and keeps the integration surface unchanged.
- **Reproducible and testable.** A PIN centroid is deterministic from the dataset and the declared PIN; tests can assert the derived point without hitting external APIs.
- **Defensible for peri-urban Daltonganj.** As recorded in the roadmap (PHASE-5 mitigation), geo accuracy in peri-urban Daltonganj must not rely on precise reverse geocoding. Using a PIN centroid keeps the search radius constraint (25 km peri-urban) meaningful without introducing external geocoding variability.
- **Simplicity and cost.** Stays within the cost floor (`NFR-001`); no new paid provider, no quota management, and no new webhook surface.
- **Seam consistency.** Aligns with the existing pattern where the directory uses a single derived geo point and the profile save is the trigger to update it.

## Consequences

- The directory index uses the derived PIN centroid when the address/PIN changes; the centroid source is the bundled dataset (already present), not a runtime external lookup.
- No new external integration is added; no `EXT-xxx` is registered for geocoding as part of this change.
- The structured address parts (locality, clinic name, etc.) are stored and displayed; the geo point remains the single centroid.
- If a declared PIN cannot be resolved to a centroid, the save path records the resolution outcome and the user can correct the PIN (as validated by integration tests/proofs in the batch).
