// #904: the /v1/me session check becomes a cached TanStack query. These tests
// pin the caching contract at the seam: one network fetch per JWT within the
// stale window, key isolation between JWTs, explicit cache clearing, and the
// ADR-0005 credentials discipline every other authed call follows.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ACCESS_TOKEN_TTL_SECONDS,
  PROACTIVE_REFRESH_RATIO,
} from "@/lib/config";
import { makeTestQueryClient } from "@/test/query-client";

import {
  SESSION_ME_QUERY_KEY_ROOT,
  SESSION_ME_STALE_TIME,
  clearCachedSessionMe,
  fetchMe,
  fetchSessionMe,
  sessionMeQueryKey,
} from "./sessionQuery";

const ME_RESPONSE = {
  subject_id: "42",
  phone: "+911234567890",
  roles: ["patient"],
  tier: null,
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

let fetchMock: ReturnType<typeof vi.fn>;
let queryClient: ReturnType<typeof makeTestQueryClient>;

beforeEach(() => {
  // A fresh Response per call: a mocked Response's body can be read once, and
  // the tests below consume the mock from several cache-miss paths.
  fetchMock = vi
    .fn()
    .mockImplementation(() => Promise.resolve(jsonResponse(ME_RESPONSE)));
  vi.stubGlobal("fetch", fetchMock);
  queryClient = makeTestQueryClient();
});

afterEach(() => {
  vi.unstubAllGlobals();
  queryClient.clear();
});

describe("fetchMe", () => {
  it("GETs /v1/me with bearer auth and ADR-0005 credentials", async () => {
    await expect(fetchMe("jwt-1")).resolves.toEqual(ME_RESPONSE);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/v1/me");
    expect(init.credentials).toBe("include");
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer jwt-1");
  });

  it("throws on a non-ok answer without parsing a body", async () => {
    fetchMock.mockResolvedValue(jsonResponse({}, 401));
    await expect(fetchMe("jwt-1")).rejects.toThrow("GET /v1/me returned 401");
  });
});

describe("sessionMeQueryKey", () => {
  it("scopes the cached answer to the JWT it was resolved with", () => {
    expect(sessionMeQueryKey("jwt-1")).toEqual(["session", "me", "jwt-1"]);
    expect(sessionMeQueryKey("jwt-2")).not.toEqual(sessionMeQueryKey("jwt-1"));
  });

  it("matches the published root so cache-wide clears catch every JWT", () => {
    expect(sessionMeQueryKey("jwt-1")).toEqual([
      ...SESSION_ME_QUERY_KEY_ROOT,
      "jwt-1",
    ]);
  });
});

describe("SESSION_ME_STALE_TIME", () => {
  it("stays fresh until the central proactive refresh rotates the token", () => {
    expect(SESSION_ME_STALE_TIME).toBe(
      ACCESS_TOKEN_TTL_SECONDS * 1000 * PROACTIVE_REFRESH_RATIO,
    );
  });
});

describe("fetchSessionMe", () => {
  it("answers a repeat call from the stale-window cache without refetching", async () => {
    await expect(fetchSessionMe(queryClient, "jwt-1")).resolves.toEqual(
      ME_RESPONSE,
    );
    await expect(fetchSessionMe(queryClient, "jwt-1")).resolves.toEqual(
      ME_RESPONSE,
    );

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("refetches once per distinct JWT, not per consumer", async () => {
    await fetchSessionMe(queryClient, "jwt-1");
    await fetchSessionMe(queryClient, "jwt-2");

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect((fetchMock.mock.calls[1] as unknown[])[0]).toBe(
      "http://localhost:8000/v1/me",
    );
  });

  it("rejects without retrying on a failed check", async () => {
    fetchMock.mockResolvedValue(jsonResponse({}, 500));
    await expect(fetchSessionMe(queryClient, "jwt-1")).rejects.toThrow(
      "GET /v1/me returned 500",
    );

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("clearCachedSessionMe", () => {
  it("forces the next consumer to hit the network again", async () => {
    await fetchSessionMe(queryClient, "jwt-1");
    clearCachedSessionMe(queryClient);
    await expect(fetchSessionMe(queryClient, "jwt-1")).resolves.toEqual(
      ME_RESPONSE,
    );

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
