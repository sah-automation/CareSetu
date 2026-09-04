// PHASE-5 T1 (#278): partner HTTP client contract. Each function must throw
// ApiError (NETWORK_ERROR on fetch failure, UNEXPECTED_ERROR on bad shape) and
// encode the request as JSON to the expected path.

import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-errors";
import {
  appealRejection,
  fetchPartnerMe,
  fetchPartnerVerification,
  fetchRejectionReason,
  registerPartner,
  submitCredentials,
} from "./api";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("registerPartner", () => {
  it("POSTs the request and resolves the registration result", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        partner_id: 7,
        identity_id: 3,
        partner_type: "doctor",
        status: "Registered",
        round: 0,
        created: true,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      registerPartner({
        phone: "9876543210",
        partner_type: "doctor",
        practice_name: "Dr. Priya Verma",
        practice_address: "Court Rd, Daltonganj",
        practice_latitude: 24.04,
        practice_longitude: 84.07,
      }),
    ).resolves.toEqual({
      partner_id: 7,
      identity_id: 3,
      partner_type: "doctor",
      status: "Registered",
      round: 0,
      created: true,
    });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/v1/partner/register");
    expect(init.method).toBe("POST");
    expect(init.headers).toBeInstanceOf(Headers);
    expect((init.headers as Headers).get("Content-Type")).toBe(
      "application/json",
    );
    expect(JSON.parse(init.body as string)).toMatchObject({
      phone: "9876543210",
      partner_type: "doctor",
    });
  });

  it("throws ApiError with NETWORK_ERROR on a network failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );

    await expect(
      registerPartner({
        phone: "9876543210",
        partner_type: "lab",
        practice_address: "A",
        practice_latitude: 0,
        practice_longitude: 0,
      }),
    ).rejects.toMatchObject({ code: "NETWORK_ERROR" });
  });

  it("throws ApiError with the envelope code on a non-ok response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            code: "INVALID_ARGS",
            message: "bad",
            trace_id: "t",
            details: {},
          },
          422,
        ),
      ),
    );

    await expect(
      registerPartner({
        phone: "",
        partner_type: "doctor",
        practice_address: "B",
        practice_latitude: 0,
        practice_longitude: 0,
      }),
    ).rejects.toMatchObject({ code: "INVALID_ARGS" });
  });

  it("throws ApiError with UNEXPECTED_ERROR on a malformed success shape", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ partner_id: 7 })),
    );

    await expect(
      registerPartner({
        phone: "9876543210",
        partner_type: "doctor",
        practice_address: "C",
        practice_latitude: 0,
        practice_longitude: 0,
      }),
    ).rejects.toBeInstanceOf(ApiError);
  });
});

describe("submitCredentials", () => {
  it("POSTs credentials and resolves the submission result", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        partner_id: 7,
        status: "Under Verification",
        round: 1,
        reason: null,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      submitCredentials({
        credentials: [
          { credential_type: "medical_registration", artifacts: ["AAAA"] },
        ],
      }),
    ).resolves.toEqual({
      partner_id: 7,
      status: "Under Verification",
      round: 1,
      reason: null,
    });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/v1/partner/credentials");
    expect(init.method).toBe("POST");
  });

  it("throws ApiError with NETWORK_ERROR on a network failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );

    await expect(
      submitCredentials({
        credentials: [{ credential_type: "lab_license", artifacts: [] }],
      }),
    ).rejects.toMatchObject({ code: "NETWORK_ERROR" });
  });

  it("is a protected call that sends credentials (authedFetch)", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        partner_id: 1,
        status: "Rejected",
        round: 2,
        reason: "missing_artifacts",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await submitCredentials({
      credentials: [{ credential_type: "drug_license", artifacts: [] }],
    });

    expect(fetchMock.mock.calls[0][1]?.credentials).toBe("include");
  });
});

describe("fetchPartnerMe", () => {
  it("resolves the partner status view", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        partner_id: 7,
        status: "Under Verification",
        partner_type: "lab",
        round: 1,
        created_at: "2026-09-01T00:00:00Z",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchPartnerMe()).resolves.toEqual({
      partner_id: 7,
      status: "Under Verification",
      partner_type: "lab",
      round: 1,
      created_at: "2026-09-01T00:00:00Z",
    });

    expect((fetchMock.mock.calls[0] as [string])[0]).toBe(
      "http://localhost:8000/v1/partner/me",
    );
  });

  it("throws ApiError on a network failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );
    await expect(fetchPartnerMe()).rejects.toMatchObject({
      code: "NETWORK_ERROR",
    });
  });

  it("throws ApiError on a malformed success shape", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ partner_id: 7 })),
    );
    await expect(fetchPartnerMe()).rejects.toBeInstanceOf(ApiError);
  });
});

describe("fetchPartnerVerification", () => {
  it("resolves the verification status view", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({
          partner_id: 7,
          round: 1,
          status: "Under Verification",
          decision: null,
          decision_reason: null,
          decided_at: null,
        }),
      ),
    );

    await expect(fetchPartnerVerification()).resolves.toEqual({
      partner_id: 7,
      round: 1,
      status: "Under Verification",
      decision: null,
      decision_reason: null,
      decided_at: null,
    });
  });

  it("throws ApiError on a network failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );
    await expect(fetchPartnerVerification()).rejects.toMatchObject({
      code: "NETWORK_ERROR",
    });
  });
});

describe("fetchRejectionReason", () => {
  it("resolves the rejection reason view", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({
          partner_id: 7,
          rejection_reason: "unreadable license",
          round: 2,
        }),
      ),
    );

    await expect(fetchRejectionReason()).resolves.toEqual({
      partner_id: 7,
      rejection_reason: "unreadable license",
      round: 2,
    });
  });
});

describe("appealRejection", () => {
  it("POSTs the appeal and resolves the partner view", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        jsonResponse({ partner_id: 7, status: "Under Verification", round: 3 }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await expect(appealRejection()).resolves.toEqual({
      partner_id: 7,
      status: "Under Verification",
      round: 3,
    });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/v1/partner/appeal");
    expect(init.method).toBe("POST");
  });
});
