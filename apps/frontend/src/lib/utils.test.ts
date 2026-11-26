import { describe, it, expect } from "vitest";

import { cn } from "./utils";

describe("cn", () => {
  it("joins truthy class names and skips falsy ones", () => {
    expect(cn("a", false && "b", undefined, "c")).toBe("a c");
  });

  it("lets later tailwind classes win over earlier conflicts", () => {
    expect(cn("p-2", "p-4")).toBe("p-4");
    expect(cn("bg-primary", "bg-accent")).toBe("bg-accent");
  });

  it("keeps unrelated classes when merging variants", () => {
    expect(cn("rounded-md px-3 text-xs", "h-9 w-9")).toContain("h-9");
    expect(cn("rounded-md px-3 text-xs", "h-9 w-9")).toContain("text-xs");
  });
});
