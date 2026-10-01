// PHASE-6 T06 (#312): provider profile client contract. `fetchProviderProfile`
// must GET the public unauthenticated path /v1/directory/providers/{id},
// resolve a found profile on a valid payload, map the backend 404
// (PROVIDER_PROFILE_NOT_FOUND) to the dedicated not-found result, and throw
// ApiError (NETWORK_ERROR on fetch failure, UNEXPECTED_ERROR on bad shape) on
// any other failure.

import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-errors";
import { fetchProviderProfile } from "./profile";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function doctorProfile() {
  return {
    partner_id: 7,
    practice_name: "Dr. Rakesh Sharma",
    partner_type: "doctor",
    specialty: "General Physician",
    area: "Daltonganj",
    verified: true,
    credentials: [
      {
        credential_type: "medical_registration",
        status: "verified",
        expires_at: "2030-04-30T00:00:00Z",
      },
      {
        credential_type: "qualification_certificate",
        status: "verified",
        expires_at: null,
      },
    ],
    clinic_name: "Sharma Clinic",
    specialties: ["General Physician", "Pediatrician"],
    languages: ["English", "Hindi"],
    consulting_days: ["Monday", "Saturday"],
    consulting_hours: "9am-5pm",
    about: "Twelve years in general practice.",
    experience_years: 12,
    address_line: "Main Road",
    landmark: null,
    locality: "Daltonganj",
    city: "Daltonganj",
    pin_code: "826001",
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchProviderProfile", () => {
  it("GETs the provider profile path and resolves the found profile", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(doctorProfile()));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchProviderProfile(7)).resolves.toEqual({
      status: "found",
      profile: doctorProfile(),
    });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/v1/directory/providers/7");
    // Public read - no method override, credentials ride through authedFetch.
    expect(init.method).toBeUndefined();
  });

  it("maps the backend 404 (PROVIDER_PROFILE_NOT_FOUND) to not-found", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            code: "PROVIDER_PROFILE_NOT_FOUND",
            message: "provider 7 not found or not active",
            trace_id: "t",
            details: {},
          },
          404,
        ),
      ),
    );

    await expect(fetchProviderProfile(7)).resolves.toEqual({
      status: "not-found",
    });
  });

  it("throws ApiError with NETWORK_ERROR on a network failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );

    await expect(fetchProviderProfile(7)).rejects.toMatchObject({
      code: "NETWORK_ERROR",
    });
  });

  it("throws ApiError with the envelope code on a non-404 non-ok response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            code: "INTERNAL_ERROR",
            message: "boom",
            trace_id: "t",
            details: {},
          },
          500,
        ),
      ),
    );

    await expect(fetchProviderProfile(7)).rejects.toMatchObject({
      code: "INTERNAL_ERROR",
    });
  });

  it("throws ApiError with UNEXPECTED_ERROR on a malformed success shape", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(jsonResponse({ partner_id: 7, verified: true })),
    );

    await expect(fetchProviderProfile(7)).rejects.toBeInstanceOf(ApiError);
  });

  it("rejects a credential with an unexpected credential_type or status", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({
          ...doctorProfile(),
          credentials: [
            { credential_type: 42, status: "verified", expires_at: null },
          ],
        }),
      ),
    );

    await expect(fetchProviderProfile(7)).rejects.toBeInstanceOf(ApiError);
  });

  // #619 (FEAT-005, MOD-002): the guard widened with the payload. A declared field
  // that arrives as the wrong type, or a selection that is not a list of strings,
  // has to fail the shape rather than reach a page that would render it - the
  // whole point of guarding is that a server which quietly changed its answer
  // produces a visible failure instead of a profile that is silently short. And a
  // profile that is short is a page where a patient cannot tell the difference
  // between "the provider declared nothing" and "the platform dropped it".
  const declaredRejections: [
    string,
    (payload: Record<string, unknown>) => void,
  ][] = [
    ["a missing declared field", (payload) => void delete payload.about],
    ["a non-string declared text", (payload) => void (payload.about = 42)],
    [
      "a non-numeric experience",
      (payload) => void (payload.experience_years = "12"),
    ],
    [
      "a selection that is not a list",
      (payload) => void (payload.languages = "Hindi"),
    ],
    [
      "a selection holding a non-string",
      (payload) => void (payload.consulting_days = ["Monday", 7]),
    ],
  ];

  for (const [name, corrupt] of declaredRejections) {
    it(`rejects ${name}`, async () => {
      const payload: Record<string, unknown> = { ...doctorProfile() };
      corrupt(payload);
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(payload)));

      await expect(fetchProviderProfile(7)).rejects.toBeInstanceOf(ApiError);
    });
  }

  it("accepts a provider that has declared nothing at all", async () => {
    // FEAT-005, the other side of the same coin: a half-finished profile is a
    // state a provider can legitimately hold, so a payload of nulls and empty
    // lists is a FOUND profile and not a bad shape. The guard has to let it
    // through, because refusing it would turn "this doctor has not written an
    // about page yet" into an error page - and an error page looks like something
    // is wrong with the doctor's practice rather than something they have not
    // filled in yet.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({
          ...doctorProfile(),
          clinic_name: null,
          specialties: [],
          languages: [],
          consulting_days: [],
          consulting_hours: null,
          about: null,
          experience_years: null,
          address_line: null,
          locality: null,
          city: null,
          pin_code: null,
        }),
      ),
    );

    await expect(fetchProviderProfile(7)).resolves.toMatchObject({
      status: "found",
    });
  });

  it("accepts a selection holding a blank member, which the renderer drops", async () => {
    // The same argument as above, one level down. A blank member is CONTENT, and
    // the renderer already answers it - a member no label map holds renders as
    // nothing - so the guard has no business failing the profile over it. Failing
    // here would trade a dropped chip for a patient looking at an error page.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({
          ...doctorProfile(),
          specialties: ["", "Pediatrician"],
        }),
      ),
    );

    await expect(fetchProviderProfile(7)).resolves.toMatchObject({
      status: "found",
    });
  });
});
