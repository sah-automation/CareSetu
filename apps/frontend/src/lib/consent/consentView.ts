// PHASE-3 T9 (#218): presentation helpers for consent log view models.
// Pure functions for rendering consent data - separated from the HTTP client
// to keep api.ts focused on transport concerns.

/**
 * Derive a short display label from the counterparty type and id.
 * The backend stores opaque ids; the frontend surfaces them as-is until a
 * partner-name resolution endpoint lands in a later phase.
 */
export function counterpartyLabel(
  counterpartyType: string,
  counterpartyId: string,
): string {
  return counterpartyId || counterpartyType;
}

/**
 * Derive initials (up to 2 chars) from a display label for the avatar circle.
 */
export function counterpartyInitials(label: string): string {
  const parts = label.trim().split(/\s+/);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}
