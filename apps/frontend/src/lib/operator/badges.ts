// PHASE-5 (#293): Shared operator badge maps and status-key normalizer.
// Extracted from the queue list and verification detail pages (Fix 4) to
// remove two byte-identical copies.
//
// Backend status strings are inconsistent in casing ("Under Verification"
// Title Case vs "verified"/"rejected" lowercase). statusKey() normalizes any
// backend status value to a stable lowercase key so badge lookups never leak
// casing differences into the render path.

const STATUS_KEY: Record<string, string> = {
  "Under Verification": "under_verification",
};

const STATUS_BADGE: Record<string, string> = {
  under_verification: "bg-warn-soft text-warn-text",
  verified: "bg-success-soft text-success-text",
  rejected: "bg-danger-soft text-danger",
};

export const TYPE_BADGE: Record<string, string> = {
  doctor: "bg-accent-soft text-accent-strong",
  lab: "bg-success-soft text-success-text",
  chemist: "bg-warm-soft text-txt-sub",
};

export { STATUS_BADGE };

export function statusKey(status: string): string {
  return STATUS_KEY[status] ?? status.toLowerCase();
}
