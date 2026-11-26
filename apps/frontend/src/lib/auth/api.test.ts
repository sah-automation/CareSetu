// DEPLOY-4 (ticket #118): best-effort demo OTP read-back contract.
// fetchDemoOtp must return the code on 200, null on 404/error, and never
// reject into the auth flow.
// PHASE-2.6 T05 (#196): fetchMe mirrors the protected GET /v1/me session
// read - subject id, roles, and the additive E.164 phone.

import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchDemoOtp, fetchMe, partnerLogin, partnerVerify } from "./api";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchDemoOtp", () => {
  it("returns the code on a 200 with a string code", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ code: "424242" })),
    );

    await expect(fetchDemoOtp("+919876543210")).resolves.toBe("424242");
  });

  it("returns null on a 404", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(jsonResponse({ code: "DEV_OTP_UNAVAILABLE" }, 404)),
    );

    await expect(fetchDemoOtp("+919876543210")).resolves.toBeNull();
  });

  it("returns null on any non-ok response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({}, 500)));

    await expect(fetchDemoOtp("+919876543210")).resolves.toBeNull();
  });

  it("returns null when the body has no code", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ code: null })),
    );

    await expect(fetchDemoOtp("+919876543210")).resolves.toBeNull();
  });

  it("returns null on a network error and never rejects", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );

    await expect(fetchDemoOtp("+919876543210")).resolves.toBeNull();
  });

  it("returns null on an unreadable body", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(new Response("<html>oops</html>", { status: 200 })),
    );

    await expect(fetchDemoOtp("+919876543210")).resolves.toBeNull();
  });

  it("encodes the phone into the query string", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ code: "424242" }));
    vi.stubGlobal("fetch", fetchMock);

    await fetchDemoOtp("+919876543210");

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit?];
    expect(url).toContain("/v1/auth/dev/otp?phone=%2B919876543210");
  });
});

describe("fetchMe", () => {
  it("resolves the session identity on a 200", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        subject_id: "7",
        roles: ["patient"],
        phone: "+919876543210",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchMe("test-jwt")).resolves.toEqual({
      subject_id: "7",
      roles: ["patient"],
      phone: "+919876543210",
    });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/v1/me");
    expect(init.headers).toEqual({ Authorization: "Bearer test-jwt" });
  });

  it("rejects on a non-ok response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({}, 401)));

    await expect(fetchMe("expired-jwt")).rejects.toThrow(
      "GET /v1/me returned 401",
    );
  });
});

describe("partnerLogin", () => {
  it("POSTs the phone to /v1/auth/partner/login and resolves the result", async () => {
    const body = {
      outcome: "sent",
      phone_e164: "+919876543210",
      challenge_id: 21,
      expires_in_seconds: 300,
      cooldown_remaining_seconds: 60,
      attempts_left: 5,
      lockout_remaining_seconds: null,
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(body));
    vi.stubGlobal("fetch", fetchMock);

    await expect(partnerLogin("+919876543210")).resolves.toEqual(body);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/v1/auth/partner/login");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({
      phone: "+919876543210",
    });
  });

  it("surfaces a non-ok response as an AuthApiError with the envelope code", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            code: "PHONE_INVALID",
            message: "bad phone",
            trace_id: "t1",
            details: {},
          },
          422,
        ),
      ),
    );

    await expect(partnerLogin("+919876543210")).rejects.toMatchObject({
      code: "PHONE_INVALID",
    });
  });

  it("wraps transport failures as a NETWORK_ERROR AuthApiError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );

    await expect(partnerLogin("+919876543210")).rejects.toMatchObject({
      code: "NETWORK_ERROR",
    });
  });
});

describe("partnerVerify", () => {
  it("POSTs phone and otp to /v1/auth/partner/verify and resolves the result", async () => {
    const body = {
      outcome: "verified",
      phone_e164: "+919876543210",
      identity_id: 7,
      attempts_left: null,
      lockout_remaining_seconds: null,
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(body));
    vi.stubGlobal("fetch", fetchMock);

    await expect(partnerVerify("+919876543210", "123456")).resolves.toEqual(
      body,
    );

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/v1/auth/partner/verify");
    expect(JSON.parse(String(init.body))).toEqual({
      phone: "+919876543210",
      otp: "123456",
    });
  });

  it("surfaces a non-ok response as an AuthApiError with the envelope code", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            code: "CODE_EXPIRED",
            message: "expired",
            trace_id: "t2",
            details: {},
          },
          410,
        ),
      ),
    );

    await expect(
      partnerVerify("+919876543210", "123456"),
    ).rejects.toMatchObject({ code: "CODE_EXPIRED" });
  });
});
