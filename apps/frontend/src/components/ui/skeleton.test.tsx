import { render, screen, cleanup } from "@testing-library/react";
import { describe, it, expect, afterEach } from "vitest";

import { Skeleton } from "./skeleton";

afterEach(() => {
  cleanup();
});

describe("Skeleton", () => {
  it("renders a pulsing placeholder div", () => {
    render(<Skeleton data-testid="skeleton" />);

    const skeleton = screen.getByTestId("skeleton");
    expect(skeleton.tagName).toBe("DIV");
    // The app-wide reduced-motion floor in src/app/globals.css neutralises
    // this animation under prefers-reduced-motion; with motion on it pulses.
    expect(skeleton.className).toContain("animate-pulse");
  });

  it("merges caller className over the defaults", () => {
    render(
      <Skeleton className="h-4 w-full rounded-none" data-testid="skeleton" />,
    );

    const skeleton = screen.getByTestId("skeleton");
    expect(skeleton.className).toContain("h-4");
    expect(skeleton.className).toContain("w-full");
    // tailwind-merge drops the conflicting default radius.
    expect(skeleton.className).not.toContain("rounded-md");
  });
});
