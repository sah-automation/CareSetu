import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { describe, it, expect, vi, afterEach } from "vitest";

import { Button, buttonVariants } from "./button";

afterEach(() => {
  cleanup();
});

describe("Button", () => {
  it("renders a button with accessible content", () => {
    render(<Button>Save record</Button>);

    const button = screen.getByRole("button", { name: "Save record" });
    expect(button).toBeInTheDocument();
    expect(button.tagName).toBe("BUTTON");
  });

  it("fires onClick when clicked", () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Tap</Button>);

    fireEvent.click(screen.getByRole("button"));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("does not fire onClick when disabled", () => {
    const onClick = vi.fn();
    render(
      <Button disabled onClick={onClick}>
        Tap
      </Button>,
    );

    fireEvent.click(screen.getByRole("button"));
    expect(onClick).not.toHaveBeenCalled();
  });

  it.each([
    ["default", "bg-primary"],
    ["destructive", "bg-destructive"],
    ["outline", "border-input"],
    ["secondary", "bg-secondary"],
    ["ghost", "hover:bg-accent-soft"],
    ["link", "underline-offset-4"],
  ] as const)("applies %s variant classes", (variant, expected) => {
    render(<Button variant={variant}>{variant}</Button>);

    expect(screen.getByRole("button").className).toContain(expected);
  });

  it("applies size classes", () => {
    render(<Button size="icon">i</Button>);

    expect(screen.getByRole("button").className).toContain("h-9 w-9");
  });

  it("merges caller className over the variant defaults", () => {
    render(<Button className="mt-2">x</Button>);

    expect(screen.getByRole("button").className).toContain("mt-2");
  });

  it("renders as the child element with merged props under asChild", () => {
    render(
      <Button asChild>
        <a href="/records">Open records</a>
      </Button>,
    );

    const link = screen.getByRole("link", { name: "Open records" });
    expect(link.getAttribute("href")).toBe("/records");
    expect(link.className).toContain("inline-flex");
  });

  it("exposes buttonVariants for non-component consumers", () => {
    expect(buttonVariants({ variant: "ghost" })).toContain(
      "hover:bg-accent-soft",
    );
    expect(buttonVariants()).toContain("bg-primary");
  });

  // PHASE-2.6 T08 (#199): spinner-in-button pattern (blueprint §9.1) -
  // in-place mutations disable the trigger while pending.
  describe("loading", () => {
    it("renders a spinner and marks the button busy while loading", () => {
      render(<Button loading>Save</Button>);

      const button = screen.getByRole("button", { name: "Save" });
      expect(button).toHaveAttribute("aria-busy", "true");
      expect(screen.getByTestId("button-spinner")).toBeInTheDocument();
    });

    it("disables the button and swallows clicks while loading", () => {
      const onClick = vi.fn();
      render(
        <Button loading onClick={onClick}>
          Save
        </Button>,
      );

      expect(screen.getByRole("button")).toBeDisabled();
      fireEvent.click(screen.getByRole("button"));
      expect(onClick).not.toHaveBeenCalled();
    });

    it("renders no spinner and no busy state when not loading", () => {
      render(<Button>Save</Button>);

      expect(screen.getByRole("button")).not.toHaveAttribute("aria-busy");
      expect(screen.queryByTestId("button-spinner")).toBeNull();
    });
  });
});
