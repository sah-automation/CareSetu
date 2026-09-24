// #501: the patient-side service-area model. The launch beachhead is a single
// city (REQ-008) - a closed enum that grows to more cities later, never free
// text. The profile draft stores a free-text `area` (ward/mohalla/landmark),
// so the location picker maps the chosen city into `draft.area` and the chip
// resolves the persisted value back for display, falling back to the beachhead
// when nothing is saved. With a single city the directory result set is
// unchanged (Daltonganj = the whole service area) - there is deliberately no
// multi-city or distance behaviour here.
//
// The enum id is the single source of truth for a service area; its display
// label lives in the locale dictionaries, keyed by that id (see `loc.cities`).
// Known ids localize; any other persisted value is free-text user data and is
// shown verbatim.

/** The service areas CareSetu serves today. One city; widen the tuple later. */
export const SERVICE_AREAS = ["Daltonganj"] as const;

export type ServiceArea = (typeof SERVICE_AREAS)[number];

/** The launch beachhead - shown whenever no area is persisted. */
export const DEFAULT_SERVICE_AREA: ServiceArea = "Daltonganj";

/** The known service area a persisted value names, or null when the value is
 * free text (a ward/landmark the picker never produced). */
export function asServiceArea(
  area: string | null | undefined,
): ServiceArea | null {
  const trimmed = area?.trim();
  return trimmed && (SERVICE_AREAS as readonly string[]).includes(trimmed)
    ? (trimmed as ServiceArea)
    : null;
}

/** The area to treat as selected: the persisted known area, else the beachhead. */
export function resolveServiceArea(
  area: string | null | undefined,
): ServiceArea {
  return asServiceArea(area) ?? DEFAULT_SERVICE_AREA;
}

/**
 * The label for the chip and Find Care's location indicator: the localized
 * label when the persisted value names a known service area, otherwise the
 * free-text user value verbatim, otherwise the localized beachhead.
 */
export function serviceAreaLabel(
  area: string | null | undefined,
  labels: Record<ServiceArea, string>,
): string {
  const known = asServiceArea(area);
  if (known) return labels[known];
  const trimmed = area?.trim();
  return trimmed ? trimmed : labels[DEFAULT_SERVICE_AREA];
}
