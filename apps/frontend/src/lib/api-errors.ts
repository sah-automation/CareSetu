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

/**
 * One validated field error as the envelope carries it: the field's wire name
 * plus the machine reason it was refused (api-standards §2/§3).
 *
 * `path` is a field identifier, not copy - a client maps it onto its own field
 * names and never renders it, and `reason` is the API's prose, so the message a
 * doctor reads is the client's own (ui-blueprint §9.5).
 */
export interface FieldError {
  path: string;
  reason: string;
}

export class ApiError extends Error {
  readonly code: string;
  readonly traceId: string;
  /**
   * The envelope's `details`, kept rather than dropped.
   *
   * #616: the constructor used to keep only `code` and `traceId`, so `details`
   * died at the throw. That was invisible until a caller needed it: a 422 that
   * names the offending field in `details.errors[].path` - #609's unresolvable
   * practice PIN - is the only thing that lets a form render the problem under
   * that input instead of guessing which one failed, and without this there was
   * nothing left to read. `code` alone cannot say which field.
   */
  readonly details: Record<string, unknown>;

  constructor(envelope: ErrorEnvelope) {
    super(envelope.message);
    this.name = "ApiError";
    this.code = envelope.code;
    this.traceId = envelope.trace_id;
    this.details = envelope.details;
  }

  /**
   * The validated field errors this envelope carries, as `path` plus `reason`.
   *
   * An accessor rather than a bare cast because `details` is typed
   * `Record<string, unknown>` and the wire is not this module's to trust: `errors`
   * is read only when it really is the validated list, and an entry is kept only
   * when it really is a path plus a reason. One malformed entry must not hide the
   * well-formed ones beside it, and a `details` payload that is some other thing
   * entirely - the envelope uses the same field for other payloads - is absence
   * rather than a crash on every caller that inspects a failure.
   */
  get fieldErrors(): FieldError[] {
    const errors = this.details.errors;
    if (!Array.isArray(errors)) return [];
    const fieldErrors: FieldError[] = [];
    for (const entry of errors) {
      if (typeof entry !== "object" || entry === null) continue;
      const { path, reason } = entry as { path?: unknown; reason?: unknown };
      if (typeof path !== "string" || typeof reason !== "string") continue;
      fieldErrors.push({ path, reason });
    }
    return fieldErrors;
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
