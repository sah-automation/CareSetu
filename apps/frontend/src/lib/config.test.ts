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
});
