// Single source for the CareSetu API origin (coding-standards §9.2): every
// frontend HTTP client resolves the base URL through this module instead of
// re-deriving it per file.
export const API_BASE_URL: string =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

const JWT_KEY = "caresetu.access_jwt";

/** Read the access JWT from localStorage. Returns null when absent. */
export function getAccessToken(): string | null {
  return localStorage.getItem(JWT_KEY);
}

/**
 * Fetch wrapper that injects `Authorization: Bearer <jwt>` and sends
 * credentials for cookie transport on split-origin deploys (ADR-0005).
 * Throws the same `ApiError` shape as the existing module-level wrappers
 * on network failure.
 */
export async function authedFetch(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  const jwt = getAccessToken();
  const headers = new Headers(init?.headers);
  if (jwt) {
    headers.set("Authorization", `Bearer ${jwt}`);
  }
  return fetch(input, { ...init, headers, credentials: "include" });
}
