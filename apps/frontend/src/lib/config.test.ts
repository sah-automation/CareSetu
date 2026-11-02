import { describe, expect, it, vi } from "vitest";

describe("config", () => {
  describe("STATUS_POLL_INTERVAL_MS", () => {
    it("defaults to 10_000 when the env var is unset", async () => {
      vi.stubEnv("NEXT_PUBLIC_STATUS_POLL_INTERVAL_MS", undefined);
      vi.resetModules();
      const { STATUS_POLL_INTERVAL_MS } = await import("./config");
      expect(STATUS_POLL_INTERVAL_MS).toBe(10_000);
    });

    it("reads from NEXT_PUBLIC_STATUS_POLL_INTERVAL_MS when set", async () => {
      vi.stubEnv("NEXT_PUBLIC_STATUS_POLL_INTERVAL_MS", "5000");
      vi.resetModules();
      const { STATUS_POLL_INTERVAL_MS } = await import("./config");
      expect(STATUS_POLL_INTERVAL_MS).toBe(5000);
    });
  });

  describe("ACCESS_TOKEN_TTL_SECONDS", () => {
    it("defaults to 7200 when the env var is unset", async () => {
      vi.stubEnv("NEXT_PUBLIC_ACCESS_TOKEN_TTL_SECONDS", undefined);
      vi.resetModules();
      const { ACCESS_TOKEN_TTL_SECONDS } = await import("./config");
      expect(ACCESS_TOKEN_TTL_SECONDS).toBe(7200);
    });
  });

  describe("PROACTIVE_REFRESH_RATIO", () => {
    it("defaults to 0.8 when the env var is unset", async () => {
      vi.stubEnv("NEXT_PUBLIC_PROACTIVE_REFRESH_RATIO", undefined);
      vi.resetModules();
      const { PROACTIVE_REFRESH_RATIO } = await import("./config");
      expect(PROACTIVE_REFRESH_RATIO).toBe(0.8);
    });
  });
});
