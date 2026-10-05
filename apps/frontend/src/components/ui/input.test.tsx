import { render, screen, cleanup } from "@testing-library/react";
import { describe, it, expect, afterEach } from "vitest";

// #600 - the Input primitive adopted over the #193 design tokens. It is a plain
// native input, so what is worth pinning is that native attributes survive the
// wrapper and that the surface resolves to tokens.
import { Input } from "./input";

afterEach(() => {
  cleanup();
});

describe("Input", () => {
  it("forwards native input attributes and keeps its own type", () => {
    render(
      <Input
        type="email"
        name="contact"
        defaultValue="a@b.co"
        placeholder="you@example.com"
        data-testid="input"
      />,
    );

    const input = screen.getByTestId("input");
    expect(input.tagName).toBe("INPUT");
    expect(input).toHaveAttribute("type", "email");
    expect(input).toHaveAttribute("name", "contact");
    expect(input).toHaveValue("a@b.co");
    expect(input).toHaveAttribute("placeholder", "you@example.com");
  });

  it("resolves its fill, edge, radius and focus ring through tokens", () => {
    render(<Input data-testid="input" />);

    const className = screen.getByTestId("input").className;
    expect(className).toContain("rounded-md");
    expect(className).toContain("border-input");
    expect(className).toContain("bg-surface");
    expect(className).toContain("text-foreground");
    expect(className).toContain("focus-visible:ring-ring");
    // Upstream's stock shadow-sm and its transparent fill are both gone
    // (file:bg-transparent is upstream's and stays - it clears the button).
    expect(className).not.toContain("shadow-sm");
    expect(className.split(" ")).not.toContain("bg-transparent");
  });

  it("merges caller className over the defaults", () => {
    render(<Input className="rounded-none" data-testid="input" />);

    // tailwind-merge drops the conflicting default radius.
    expect(screen.getByTestId("input").className).not.toContain("rounded-md");
  });

  it("carries the disabled affordance", () => {
    render(<Input disabled data-testid="input" />);

    const input = screen.getByTestId("input") as HTMLInputElement;
    expect(input.disabled).toBe(true);
    expect(input.className).toContain("disabled:cursor-not-allowed");
  });
});
