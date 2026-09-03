// Shared fetch helper and shape-guard utility for frontend API clients.
// Extracts the duplicated NETWORK_ERROR-catch + parseEnvelope + shape-guard
// pattern across partner, operator, audit, and consent API modules
// (coding-standards section 2, hexagonal isolation).

import { API_BASE_URL, authedFetch } from "@/lib/api-base";
import { ApiError, parseErrorEnvelope } from "@/lib/api-errors";

/**
 * Fetch wrapper that injects `Authorization: Bearer <jwt>` and handles
 * network errors, non-ok responses, and JSON parsing. Returns the parsed
 * JSON payload as type `T`.
 *
 * Throws `ApiError` with:
 * - `NETWORK_ERROR` when the fetch itself fails (no HTTP response)
 * - The error envelope code when the response is non-ok
 */
export async function request<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  let response: Response;
  try {
    response = await authedFetch(`${API_BASE_URL}${path}`, options);
  } catch {
    throw new ApiError({
      code: "NETWORK_ERROR",
      message: "Could not reach the CareSetu API",
      trace_id: "",
      details: {},
    });
  }

  if (!response.ok) {
    throw new ApiError(await parseErrorEnvelope(response));
  }

  return (await response.json()) as T;
}

/**
 * Validate that a value matches an expected shape using a type guard.
 * Throws `ApiError` with `UNEXPECTED_ERROR` when the guard fails.
 *
 * @param value - The value to validate
 * @param guard - The type guard function
 * @param message - Error message for the thrown ApiError
 */
export function guardShape<T>(
  value: unknown,
  guard: (value: unknown) => value is T,
  message: string,
): T {
  if (!guard(value)) {
    throw new ApiError({
      code: "UNEXPECTED_ERROR",
      message,
      trace_id: "",
      details: {},
    });
  }
  return value;
}
