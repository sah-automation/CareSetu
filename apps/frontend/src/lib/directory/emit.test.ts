// PHASE-6 T6 (#328): the fire-and-forget `partner.selected` client emitter
// suite. Verifies the emitter POSTs the anonymous pick-only facts to the
// public directory pick route and - true to fire-and-forget - never throws
// and never surfaces a network failure (degrade-gracefully).

import { afterEach, describe, expect, it, vi } from "vitest";

import { emitPartnerSelected } from "./emit";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("emitPartnerSelected", () => {
  it("POSTs the anonymous pick to the public select route", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    emitPartnerSelected({
      partner_id: 7,
      partner_type: "doctor",
      source: "search_card",
    });

    // Fire-and-forget is async-voided; yield the microtask queue so the POST
    // lands before we assert.
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    const [input, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(input).toBe("http://localhost:8000/v1/directory/select");
    expect(init?.method).toBe("POST");
    const headers = new Headers(init?.headers);
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(JSON.parse(String(init?.body))).toEqual({
      partner_id: 7,
      partner_type: "doctor",
      source: "search_card",
    });
  });

  it("carries the anonymous pick-only facts for a profile open", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}));
    vi.stubGlobal("fetch", fetchMock);

    emitPartnerSelected({
      partner_id: 9,
      partner_type: null,
      source: "provider_profile",
    });

    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init?.body))).toEqual({
      partner_id: 9,
      partner_type: null,
      source: "provider_profile",
    });
  });

  it("never throws or surfaces a network failure (fire-and-forget)", async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetchMock);

    // A rejected POST is swallowed silently - no unhandled rejection.
    emitPartnerSelected({
      partner_id: 1,
      partner_type: "lab",
      source: "search_card",
    });

    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  });

  it("does not throw on a non-ok response either", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}, 500));
    vi.stubGlobal("fetch", fetchMock);

    emitPartnerSelected({
      partner_id: 2,
      partner_type: "chemist",
      source: "search_card",
    });

    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  });
});
