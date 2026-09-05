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
});
