// PHASE-5 T1 (#278): operator HTTP client contract. Each function must throw
// ApiError (NETWORK_ERROR on fetch failure, UNEXPECTED_ERROR on bad shape),
// send credentials on protected calls, and encode request bodies as JSON.

import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-errors";
import {
  enrollOperatorMfa,
  fetchVerificationDetail,
  fetchVerificationQueue,
  operatorLogin,
  submitOperatorDecision,
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

describe("operatorLogin", () => {
  it("POSTs phone+code and resolves the session", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        jwt: "abc",
        jti: "j1",
        scope: "operator",
        identity_id: 5,
        expires_in_seconds: 3600,
        refresh_token: "rt",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      operatorLogin({ phone: "9876543210", code: "123456" }),
    ).resolves.toEqual({
      jwt: "abc",
      jti: "j1",
      scope: "operator",
      identity_id: 5,
      expires_in_seconds: 3600,
      refresh_token: "rt",
    });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/v1/auth/operator/login");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      phone: "9876543210",
      code: "123456",
    });
  });

  it("throws ApiError with NETWORK_ERROR on a network failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );
    await expect(
      operatorLogin({ phone: "9876543210", code: "123456" }),
    ).rejects.toMatchObject({
      code: "NETWORK_ERROR",
    });
  });

  it("throws ApiError with the envelope code on an MFA refusal (401)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            code: "SESSION_MFA_REQUIRED",
            message: "mfa",
            trace_id: "t",
            details: {},
          },
          401,
        ),
      ),
    );

    await expect(
      operatorLogin({ phone: "9876543210", code: "000000" }),
    ).rejects.toMatchObject({
      code: "SESSION_MFA_REQUIRED",
    });
  });

  it("throws ApiError with UNEXPECTED_ERROR on a malformed success shape", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ jwt: "abc" })),
    );
    await expect(
      operatorLogin({ phone: "9876543210", code: "123456" }),
    ).rejects.toBeInstanceOf(ApiError);
  });
});

describe("enrollOperatorMfa", () => {
  it("POSTs and resolves the enrollment result", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        identity_id: 5,
        phone_e164: "+919876543210",
        secret: "JBSWY3DP",
        provisioning_uri: "otpauth://totp/CareSetu:op?secret=JBSWY3DP",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(enrollOperatorMfa()).resolves.toEqual({
      identity_id: 5,
      phone_e164: "+919876543210",
      secret: "JBSWY3DP",
      provisioning_uri: "otpauth://totp/CareSetu:op?secret=JBSWY3DP",
    });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/v1/auth/operator/mfa/enroll");
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("include");
  });
});

describe("fetchVerificationQueue", () => {
  it("resolves the queue with default params", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ items: [] }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchVerificationQueue()).resolves.toEqual({ items: [] });
    expect((fetchMock.mock.calls[0] as [string])[0]).toBe(
      "http://localhost:8000/v1/partner/verification-queue",
    );
  });

  it("encodes filter params into the query string", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ items: [] }));
    vi.stubGlobal("fetch", fetchMock);

    await fetchVerificationQueue({
      partner_type: "lab",
      status: "Rejected",
      sort_by: "status",
    });

    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toContain("partner_type=lab");
    expect(url).toContain("status=Rejected");
    expect(url).toContain("sort_by=status");
  });

  it("throws ApiError on a malformed queue shape", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ not_items: true })),
    );
    await expect(fetchVerificationQueue()).rejects.toBeInstanceOf(ApiError);
  });
});

describe("fetchVerificationDetail", () => {
  it("resolves the full detail view", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        partner_id: 7,
        identity_id: 3,
        partner_type: "lab",
        status: "Under Verification",
        practice_name: "Pioneer",
        practice_address: "Court Rd",
        service_area_id: 1,
        created_at: "2026-09-01T00:00:00Z",
        credentials: [],
        verification_history: [],
        audit_events: [],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchVerificationDetail(7)).resolves.toMatchObject({
      partner_id: 7,
    });
    expect((fetchMock.mock.calls[0] as [string])[0]).toBe(
      "http://localhost:8000/v1/partner/verification/7",
    );
  });
});

describe("submitOperatorDecision", () => {
  it("POSTs the decision and resolves the partner view", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        jsonResponse({ partner_id: 7, status: "Active", round: 1 }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await expect(submitOperatorDecision(7, { approve: true })).resolves.toEqual(
      {
        partner_id: 7,
        status: "Active",
        round: 1,
      },
    );

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(
      "http://localhost:8000/v1/partner/verification/7/decision",
    );
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      approve: true,
      reason: undefined,
    });
    expect(init.credentials).toBe("include");
  });

  it("sends the rejection reason", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        jsonResponse({ partner_id: 7, status: "Rejected", round: 2 }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await submitOperatorDecision(7, {
      approve: false,
      reason: "unreadable license",
    });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({
      approve: false,
      reason: "unreadable license",
    });
  });
});
