// PHASE-8.1 T11 (#449): patient pick-a-doctor client contract. The mutation
// must POST to /v1/intake/{id}/pick-doctor with the chosen partner id in the
// body, emit the shared Idempotency-Key header (api-standards A5) like every
// care mutation, and resolve/guard the PickDoctorResult shape. Throws ApiError
// on network failure and malformed shapes.

import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-errors";
import { IDEMPOTENCY_KEY_HEADER } from "@/lib/idempotency";
import { pickDoctor } from "./api";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const pickResult = {
  intake_id: 42,
  assigned_partner_id: 7,
  consent_id: 3,
  consent_lineage_ref: "C-42-001",
  consent_version: 1,
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("pickDoctor", () => {
  it("POSTs the partner id and resolves the atomic pick+consent result", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(pickResult));
    vi.stubGlobal("fetch", fetchMock);

    await expect(pickDoctor(42, 7)).resolves.toEqual(pickResult);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/v1/intake/42/pick-doctor");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ partner_id: 7 });
  });

  it("sends the shared Idempotency-Key header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(pickResult));
    vi.stubGlobal("fetch", fetchMock);

    await pickDoctor(42, 7);

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(headers.get(IDEMPOTENCY_KEY_HEADER)).toBeTruthy();
  });

  it("reuses a caller-supplied key so a retry is deduplicated", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(pickResult));
    vi.stubGlobal("fetch", fetchMock);

    const key = "retry-abc";
    await pickDoctor(42, 7, key);

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new Headers(init.headers).get(IDEMPOTENCY_KEY_HEADER)).toBe(key);
  });

  it("throws ApiError with NETWORK_ERROR on a network failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );

    await expect(pickDoctor(42, 7)).rejects.toMatchObject({
      code: "NETWORK_ERROR",
    });
  });

  it("throws ApiError with the envelope code on a non-ok response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            code: "INTAKE_ALREADY_ASSIGNED",
            message: "This visit already has a doctor",
            trace_id: "t",
            details: {},
          },
          409,
        ),
      ),
    );

    await expect(pickDoctor(42, 7)).rejects.toMatchObject({
      code: "INTAKE_ALREADY_ASSIGNED",
    });
  });

  it("throws ApiError with UNEXPECTED_ERROR on a malformed success shape", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ intake_id: 42 })),
    );

    await expect(pickDoctor(42, 7)).rejects.toBeInstanceOf(ApiError);
  });
});
