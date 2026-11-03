import { describe, expect, it } from "vitest";

import nextConfig from "../../next.config";

const CACHE_HEADER_VALUE =
  "public, s-maxage=3600, stale-while-revalidate=86400";
const PUBLIC_ROUTES = ["/", "/directory", "/doctors", "/labs", "/chemists"];

describe("next config cache headers", () => {
  it("adds the exact cache header to all five public routes", async () => {
    const rules = await nextConfig.headers();
    const cached = rules
      .filter((rule) =>
        rule.headers.some(
          (header) =>
            header.key === "Cache-Control" &&
            header.value === CACHE_HEADER_VALUE,
        ),
      )
      .map((rule) => rule.source);
    expect(cached.sort()).toEqual(PUBLIC_ROUTES.slice().sort());
  });

  it("keeps security headers on the global matcher", async () => {
    const rules = await nextConfig.headers();
    const global = rules.find((rule) => rule.source === "/(.*)");
    expect(global?.headers).toContainEqual({
      key: "X-Content-Type-Options",
      value: "nosniff",
    });
  });

  it("does not add a cache header to protected route matchers", async () => {
    const rules = await nextConfig.headers();
    const cachedProtected = rules.filter(
      (rule) =>
        rule.source !== "/(.*)" &&
        !PUBLIC_ROUTES.includes(rule.source) &&
        rule.headers.some((header) => header.key === "Cache-Control"),
    );
    expect(cachedProtected).toHaveLength(0);
  });
});
