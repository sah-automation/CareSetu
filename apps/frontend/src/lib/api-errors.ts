// Shared HTTP client error types for frontend API surfaces. Extracted from
// record/api.ts so that consent/api.ts (and any future module client) can
// reuse the same error envelope + error class without cross-module coupling
// (coding-standards section 2, hexagonal isolation).

export interface ErrorEnvelope {
  code: string;
  message: string;
  trace_id: string;
  details: Record<string, unknown>;
}

export class ApiError extends Error {
  readonly code: string;
  readonly traceId: string;

  constructor(envelope: ErrorEnvelope) {
    super(envelope.message);
    this.name = "ApiError";
    this.code = envelope.code;
    this.traceId = envelope.trace_id;
  }
}

/**
 * Extract the trace id from a fetch Response, falling back to empty string
 * when the header is absent (e.g. network-level failures before any HTTP
 * response arrived).
 */
export function extractTraceId(response: Response): string {
  return response.headers.get("x-trace-id") ?? "";
}

/**
 * Parse an ErrorEnvelope from a non-ok Response. Returns a fallback
 * envelope when the body is not valid JSON (error-handling-observability
 * section 1: every failure is classified, never swallowed).
 */
export async function parseErrorEnvelope(
  response: Response,
): Promise<ErrorEnvelope> {
  try {
    return (await response.json()) as ErrorEnvelope;
  } catch {
    return {
      code: "UNEXPECTED_ERROR",
      message: "The API answered with an unreadable response",
      trace_id: extractTraceId(response),
      details: {},
    };
  }
}
