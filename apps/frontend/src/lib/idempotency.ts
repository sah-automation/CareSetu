// Shared idempotency-key header helper (PHASE-8.1 T10, #446). The backend
// gateway's ``run_idempotent`` (app/gateway/idempotency.py, api-standards A5)
// dedupes a mutation by its ``Idempotency-Key`` header, namespaced per request
// path, so a client retry that replays the same key cannot double-issue a
// mutation. Care mutations send this header through this helper so no page
// re-implements the header itself.

export const IDEMPOTENCY_KEY_HEADER = "Idempotency-Key";

/**
 * Resolve the Idempotency-Key value for a mutation.
 *
 * A fresh mutation gets a new key; a caller retrying the same mutation after a
 * lost response passes the key of the failed attempt back via ``retryKey`` so
 * the backend returns the original result instead of re-executing.
 */
export function idempotencyKey(retryKey?: string): string {
  if (retryKey !== undefined && retryKey.trim() !== "") {
    return retryKey.trim();
  }
  return crypto.randomUUID();
}
