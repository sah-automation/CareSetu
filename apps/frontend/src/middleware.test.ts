import { describe, it, expect } from "vitest";
import { NextRequest, NextResponse } from "next/server";
import { middleware, config } from "./middleware";

function makeRequest(path: string, cookie?: string): NextRequest {
  const url = new URL(path, "http://localhost:3000");
  const headers = new Headers();
  if (cookie) {
    headers.set("cookie", cookie);
  }
  return new NextRequest(url, { headers });
}

function redirectLocation(response: NextResponse): string | null {
  const location = response.headers.get("location");
  return location ? new URL(location).pathname : null;
}

describe("middleware", () => {
  describe("protected routes without session", () => {
    it.each(["/patient", "/patient/dashboard", "/partner", "/operator"])(
      "redirects %s to /login",
      (path) => {
        const response = middleware(makeRequest(path), {} as never);
        expect(response.status).toBe(307);
        expect(redirectLocation(response)).toBe("/login");
      },
    );
  });

  describe("protected routes with session", () => {
    it.each(["/patient", "/patient/dashboard", "/partner", "/operator"])(
      "passes %s through",
      (path) => {
        const response = middleware(
          makeRequest(path, "caresetu_session=tok"),
          {} as never,
        );
        expect(response.status).toBe(200);
      },
    );
  });

  describe("/login route", () => {
    it("redirects to /patient when session exists", () => {
      const response = middleware(
        makeRequest("/login", "caresetu_session=tok"),
        {} as never,
      );
      expect(response.status).toBe(307);
      expect(redirectLocation(response)).toBe("/patient");
    });

    it("passes through when no session", () => {
      const response = middleware(makeRequest("/login"), {} as never);
      expect(response.status).toBe(200);
    });
  });

  describe("/choose-role route", () => {
    it("redirects to /login when no session", () => {
      const response = middleware(makeRequest("/choose-role"), {} as never);
      expect(response.status).toBe(307);
      expect(redirectLocation(response)).toBe("/login");
    });

    it("passes through when session exists", () => {
      const response = middleware(
        makeRequest("/choose-role", "caresetu_session=tok"),
        {} as never,
      );
      expect(response.status).toBe(200);
    });
  });

  describe("public routes", () => {
    it.each(["/", "/some-public-page"])("passes %s through", (path) => {
      const response = middleware(makeRequest(path), {} as never);
      expect(response.status).toBe(200);
    });
  });

  describe("config.matcher", () => {
    it("only matches protected and auth routes", () => {
      expect(config.matcher).toEqual([
        "/patient/:path*",
        "/partner/:path*",
        "/operator/:path*",
        "/login",
        "/choose-role",
      ]);
    });
  });
});
