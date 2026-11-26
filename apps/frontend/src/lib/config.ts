// Shared client-side configuration constants.
// Each reads from a NEXT_PUBLIC_* env var (Next.js build-time inlining) with a
// safe default so local dev works without a .env entry.

/** Poll interval (ms) for partner-status screens that re-check verification state. */
export const STATUS_POLL_INTERVAL_MS =
  Number(process.env.NEXT_PUBLIC_STATUS_POLL_INTERVAL_MS) || 10_000;

/** Canonical access-token lifetime (seconds); must match the backend default. */
export const ACCESS_TOKEN_TTL_SECONDS =
  Number(process.env.NEXT_PUBLIC_ACCESS_TOKEN_TTL_SECONDS) || 900;

/** Fraction of the access-token lifetime at which a proactive refresh runs. */
export const PROACTIVE_REFRESH_RATIO =
  Number(process.env.NEXT_PUBLIC_PROACTIVE_REFRESH_RATIO) || 0.8;
