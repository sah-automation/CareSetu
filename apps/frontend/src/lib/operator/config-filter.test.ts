// Issue #875: config secret-key filter tests.

import { describe, expect, it } from "vitest";

import { SECRET_KEY_PATTERNS, isSecretKey } from "./config-filter";

describe("isSecretKey", () => {
  it("returns true for keys containing 'key'", () => {
    expect(isSecretKey("ai.api_key")).toBe(true);
    expect(isSecretKey("api_key")).toBe(true);
  });

  it("returns true for keys containing 'secret'", () => {
    expect(isSecretKey("smtp.secret")).toBe(true);
    expect(isSecretKey("secret_token")).toBe(true);
  });

  it("returns true for keys containing 'password'", () => {
    expect(isSecretKey("smtp.password")).toBe(true);
  });

  it("returns true for keys containing 'token'", () => {
    expect(isSecretKey("auth.token")).toBe(true);
  });

  it("returns true for keys containing 'url'", () => {
    expect(isSecretKey("redis.url")).toBe(true);
  });

  it("returns false for non-secret keys", () => {
    expect(isSecretKey("ai.temperature")).toBe(false);
    expect(isSecretKey("feature.enable_xyz")).toBe(false);
    expect(isSecretKey("cache.ttl_seconds")).toBe(false);
  });

  it("is case-insensitive", () => {
    expect(isSecretKey("API_KEY")).toBe(true);
    expect(isSecretKey("Redis.URL")).toBe(true);
    expect(isSecretKey("Smtp.Password")).toBe(true);
    expect(isSecretKey("AUTH.TOKEN")).toBe(true);
    expect(isSecretKey("MY.SECRET")).toBe(true);
  });

  it("handles partial matches", () => {
    expect(isSecretKey("apikey")).toBe(true);
    expect(isSecretKey("secretkey")).toBe(true);
    expect(isSecretKey("password123")).toBe(true);
    expect(isSecretKey("tok")).toBe(false);
  });

  it("returns false for empty string", () => {
    expect(isSecretKey("")).toBe(false);
  });
});

describe("SECRET_KEY_PATTERNS", () => {
  it("exports the expected patterns", () => {
    expect([...SECRET_KEY_PATTERNS]).toEqual([
      "key",
      "secret",
      "password",
      "token",
      "url",
    ]);
  });
});
