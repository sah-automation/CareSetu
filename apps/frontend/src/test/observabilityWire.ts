// #737: the one wire seam every operator lens page test runs on.
//
// A page's own test mocks the client, so it starts ABOVE the wire->model
// boundary and could never see a decoding fault. The wire test keeps the real
// client, stubs only the transport, and asserts what the page actually renders
// from the exact JSON the route emits - pydantic serialises every backend
// `Decimal` as a STRING, so a client that passes the body through hands a
// formatter a string and takes the panel down.
//
// This helper exists because that seam was declared twice, differently: the cost
// page routed by path suffix, the deep-links panel ignored the path, and both
// hand-rolled the session token into localStorage. Two copies of a wire contract
// drift - a third lens page would have copied one of them and made it three. All
// three shapes are here so every lens page (Business, Reliability, Product)
// imports the same one.

import { vi } from "vitest";

import { clearSession, saveSession } from "@/lib/auth/session";

/**
 * An operator whose session the real client will actually send.
 *
 * The wire test proves the real `request` path, and `request` reads the bearer
 * out of the session store (lib/api-base.ts). So the token goes through
 * `saveSession` rather than being poked into localStorage by key: the key is the
 * store's private detail, and a test that hardcodes it fails the day the store
 * rotates.
 */
export const OPERATOR_SESSION = {
  jwt: "operator.jwt.value",
  refresh_token: "operator.refresh.value",
  jti: "operator-jti",
  scope: "operator",
  identity_id: 42,
  expires_in_seconds: 900,
} as const;

/**
 * Put a real operator in the session store. Pair with `clearOperatorSession`.
 *
 * The phone is the one field `saveSession` needs and the wire test has no use
 * for; it is a fixture value, not a claim that this operator has a phone.
 */
export function signInOperator(): void {
  saveSession(OPERATOR_SESSION, "+910000000000");
}

/** Take the operator back out, so one test's session is not the next one's. */
export function clearOperatorSession(): void {
  clearSession();
}

/** A JSON response with the content type the real `request` checks for. */
export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/**
 * The path a route suffix should be matched against: the URL with its query
 * string removed.
 *
 * A page that asks a read a question sends that question in the query - the
 * Reliability feed's `?page=1&status=open` - and a suffix match against the
 * whole URL would miss, handing the read `{}` and failing its shape guard.
 */
function pathWithoutQuery(path: string): string {
  return path.split("?")[0];
}

/**
 * Whether a request path is the route a suffix names.
 *
 * Both forms are tried so a suffix matches a URL that carries a query AND a
 * suffix that names one (a query string is not a path, but a test that cares
 * about the query should still be able to name the whole thing).
 */
function matchesSuffix(path: string, suffix: string): boolean {
  return path.endsWith(suffix) || pathWithoutQuery(path).endsWith(suffix);
}

/**
 * The JSON body for the first route suffix the request names, or `{}` for a URL
 * matching none. The `{}` is deliberate: an unrouted read then fails its own
 * shape guard, which is the honest signal that the page asked for something the
 * test did not stage - better than a promise that never settles and a test that
 * times out.
 */
function bodyFor(path: string, routes: Record<string, unknown>): unknown {
  const match = Object.entries(routes).find(([suffix]) =>
    matchesSuffix(path, suffix),
  );
  return match ? match[1] : {};
}

/**
 * Answer every route with `body`, whatever the URL.
 *
 * The right default for a page whose panels all read one route, and the shape
 * the deep-links panel needed: its read is the only request the render makes.
 */
export function stubBodyWire(body: unknown): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn((_input: RequestInfo | URL) =>
    Promise.resolve(jsonResponse(body)),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/**
 * Answer each route by path suffix, so a page with several panels can give each
 * read its own body. A suffix matches whether or not the URL carries a query -
 * see `matchesSuffix`. An unrouted URL answers `{}`, which fails that read's own
 * shape guard rather than hanging the test.
 */
export function stubRouteWire(
  routes: Record<string, unknown>,
): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn((input: RequestInfo | URL) =>
    Promise.resolve(jsonResponse(bodyFor(String(input), routes))),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/**
 * Fail the URLs matching `failingSuffix` and answer the rest from `routes`.
 *
 * The default `status` is 404 with an envelope code to match, because the error
 * taxonomy (error-handling-observability §1) classes a 4xx and its code together:
 * a `500` carrying `NOT_FOUND` is a body the API would never send, and a test
 * fixture that asserts against it proves nothing about the real error path.
 */
export function stubFailingRoute(
  failingSuffix: string,
  routes: Record<string, unknown> = {},
  status = 404,
): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const path = String(input);
    if (matchesSuffix(path, failingSuffix)) {
      return Promise.resolve(
        jsonResponse({ code: "NOT_FOUND", message: "no such read" }, status),
      );
    }
    return Promise.resolve(jsonResponse(bodyFor(path, routes)));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/** The URL the stub was asked for, so a test can pin the query it sent. */
export function requestedUrls(fetchMock: ReturnType<typeof vi.fn>): string[] {
  return fetchMock.mock.calls.map((call) => String(call[0]));
}
