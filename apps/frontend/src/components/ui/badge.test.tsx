import { render, screen, cleanup } from "@testing-library/react";
import { describe, it, expect, afterEach } from "vitest";

// #600 - the Badge primitive adopted over the #193 design tokens. What is worth
// pinning is that every named variant lands on a bridged token pair, so a
// consumer can compose a badge without a colour literal in reach.
import { Badge, badgeVariants } from "./badge";

afterEach(() => {
  cleanup();
});

describe("Badge", () => {
  it("renders its text and defaults to the primary variant", () => {
    render(<Badge data-testid="badge">Verified</Badge>);

    const badge = screen.getByTestId("badge");
    expect(badge.tagName).toBe("DIV");
    expect(badge).toHaveTextContent("Verified");
    expect(badge.className).toContain("bg-primary");
    expect(badge.className).toContain("text-primary-foreground");
  });

  it.each([
    ["secondary", "bg-secondary", "text-secondary-foreground"],
    ["destructive", "bg-destructive", "text-destructive-foreground"],
    ["outline", "border-input", "text-foreground"],
  ] as const)(
    "resolves the %s variant to a bridged token pair",
    (variant, fill, ink) => {
      expect(badgeVariants({ variant })).toContain(fill);
      expect(badgeVariants({ variant })).toContain(ink);
    },
  );

  it("shows a focus ring only for the keyboard, never for a mouse click", () => {
    const className = badgeVariants();

    expect(className).toContain("focus-visible:ring-ring");
    expect(className).not.toContain("focus:ring");
    expect(className).not.toContain("ring-offset");
  });

  it("applies a caller variant to the rendered element", () => {
    render(
      <Badge variant="destructive" data-testid="badge">
        Expired
      </Badge>,
    );

    const badge = screen.getByTestId("badge");
    expect(badge.className).toContain("bg-destructive");
    expect(badge.className).not.toContain("bg-primary");
  });

  it("merges caller className over the variant classes", () => {
    render(
      <Badge className="px-4" data-testid="badge">
        Verified
      </Badge>,
    );

    const className = screen.getByTestId("badge").className;
    expect(className).toContain("px-4");
    // tailwind-merge drops the conflicting default padding.
    expect(className).not.toContain("px-2.5");
  });
});
