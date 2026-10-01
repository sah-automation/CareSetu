// #616: the shared error module's own suite.
//
// `ApiError` used to keep only `code` and `traceId`, so `details` died at the
// throw: a 422 that names the offending field in `details.errors[].path` (#609's
// unresolvable PIN) could not be rendered under that input by anyone. These
// tests pin the preservation itself rather than only one consumer's use of it,
// because `details` is the envelope's contract (api-standards §2) and every
// client that throws through this class inherits whatever survives here.

import { describe, expect, it } from "vitest";

import { ApiError, parseErrorEnvelope, type ErrorEnvelope } from "./api-errors";

function envelope(overrides: Partial<ErrorEnvelope> = {}): ErrorEnvelope {
  return {
    code: "DOCTOR_PROFILE_ADDRESS_PIN_UNRESOLVED",
    message: "the declared PIN code does not resolve to a practice position",
    trace_id: "trace-616",
    details: {},
    ...overrides,
  };
}

describe("ApiError", () => {
  it("keeps the code, the message and the trace id it always kept", () => {
    const error = new ApiError(envelope());

    expect(error).toBeInstanceOf(Error);
    expect(error.name).toBe("ApiError");
    expect(error.code).toBe("DOCTOR_PROFILE_ADDRESS_PIN_UNRESOLVED");
    expect(error.message).toBe(
      "the declared PIN code does not resolve to a practice position",
    );
    expect(error.traceId).toBe("trace-616");
  });

  it("preserves `details` across the throw", () => {
    // The gap this ticket closes: the envelope declares `details` and the class
    // used to drop it, which left a client with a code it could not act on.
    const details = {
      errors: [{ path: "pin_code", reason: "the PIN code must be six digits" }],
    };

    expect(new ApiError(envelope({ details })).details).toEqual(details);
  });

  it("narrows the validated field errors to path plus reason", () => {
    const error = new ApiError(
      envelope({
        details: {
          errors: [
            {
              path: "pin_code",
              reason: "this PIN code is not one we can place yet",
            },
          ],
        },
      }),
    );

    // Only the two keys the API standard promises, and only from the `errors`
    // list: a caller maps `path` onto its own field names and never renders the
    // reason, which is the API's prose rather than client copy (§2, ui-blueprint
    // §9.5 - user-visible copy lives in the client).
    expect(error.fieldErrors).toEqual([
      {
        path: "pin_code",
        reason: "this PIN code is not one we can place yet",
      },
    ]);
  });

  it("reads no field errors from an envelope that carries none", () => {
    expect(new ApiError(envelope()).fieldErrors).toEqual([]);
    expect(new ApiError(envelope({ details: {} })).fieldErrors).toEqual([]);
    // A detail that is not the validated list at all - the envelope also uses
    // `details` for other payloads - is absence, not a crash.
    expect(
      new ApiError(envelope({ details: { cause: "upstream timeout" } }))
        .fieldErrors,
    ).toEqual([]);
  });

  it("skips an entry that is not a path plus a reason", () => {
    // Defensive on purpose: `details` is typed `Record<string, unknown>` and the
    // wire is not this module's to trust, so one malformed entry must not hide
    // the well-formed ones beside it.
    const error = new ApiError(
      envelope({
        details: {
          errors: [
            { path: "pin_code", reason: "six digits" },
            { path: 7 },
            "not an object",
            { reason: "no path" },
          ],
        },
      }),
    );

    expect(error.fieldErrors).toEqual([
      { path: "pin_code", reason: "six digits" },
    ]);
  });
});

describe("parseErrorEnvelope", () => {
  it("hands the parsed envelope over with its details intact", async () => {
    // The round trip a 422 actually takes: parse, then throw. Asserted through
    // `parseErrorEnvelope` so the class's constructor is proven against the
    // envelope a real response produces rather than a hand-built one.
    const body = envelope({
      details: { errors: [{ path: "pin_code", reason: "six digits" }] },
    });
    const response = new Response(JSON.stringify(body), { status: 422 });

    const parsed = await parseErrorEnvelope(response);

    expect(new ApiError(parsed).fieldErrors).toEqual([
      { path: "pin_code", reason: "six digits" },
    ]);
  });

  it("still falls back to an empty-details envelope on an unreadable body", async () => {
    const response = new Response("<html>502</html>", { status: 502 });

    const parsed = await parseErrorEnvelope(response);

    expect(parsed.code).toBe("UNEXPECTED_ERROR");
    expect(new ApiError(parsed).fieldErrors).toEqual([]);
  });
});
