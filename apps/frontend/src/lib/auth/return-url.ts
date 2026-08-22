// PHASE-2.6 T07 (#198): the `return` param contract shared by every auth
// entry point. The cookie-presence proxy (src/proxy.ts) attaches the original
// app path+query when bouncing an unauthenticated hit to /login or
// /staff/login; after sign-in the entry surface redirects to it so deep links
// never dead-end (blueprint §2.2).

// Query parameter carrying the post-auth destination.
export const RETURN_PARAM = "return";

// Where a patient-surface sign-in lands without a usable return target.
export const PATIENT_HOME = "/patient";

// Only same-origin relative paths are honored: must start with exactly one
// slash and contain no backslash anywhere (browsers normalize backslashes to
// slashes, so `/\host` can parse as protocol-relative). Absolute URLs,
// scheme-relative URLs, and anything else fall back to PATIENT_HOME.
export function sanitizeReturnTarget(raw: string | null | undefined): string {
  if (!raw) {
    return PATIENT_HOME;
  }
  if (!raw.startsWith("/") || raw.startsWith("//") || raw.includes("\\")) {
    return PATIENT_HOME;
  }
  return raw;
}
