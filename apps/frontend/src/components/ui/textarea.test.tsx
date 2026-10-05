import { render, screen, cleanup } from "@testing-library/react";
import { describe, it, expect, afterEach } from "vitest";

// #600 - the Textarea primitive adopted over the #193 design tokens. It is a
// plain native textarea, so what is worth pinning is that native attributes
// survive the wrapper and that the surface resolves to tokens.
import { Textarea } from "./textarea";

afterEach(() => {
  cleanup();
});

describe("Textarea", () => {
  it("renders a resizable-by-markup multi-line field", () => {
    render(
      <Textarea
        name="about"
        rows={4}
        defaultValue="Twelve years in general practice."
        placeholder="About your practice"
        data-testid="textarea"
      />,
    );

    const textarea = screen.getByTestId("textarea");
    expect(textarea.tagName).toBe("TEXTAREA");
    expect(textarea).toHaveAttribute("name", "about");
    expect(textarea).toHaveAttribute("rows", "4");
    expect(textarea).toHaveValue("Twelve years in general practice.");
    expect(textarea).toHaveAttribute("placeholder", "About your practice");
  });

  it("resolves its fill, edge, radius and focus ring through tokens", () => {
    render(<Textarea data-testid="textarea" />);

    const className = screen.getByTestId("textarea").className;
    expect(className).toContain("min-h-20");
    expect(className).toContain("rounded-md");
    expect(className).toContain("border-input");
    expect(className).toContain("bg-surface");
    expect(className).toContain("text-foreground");
    expect(className).toContain("focus-visible:ring-ring");
    // Upstream's stock shadow-sm and its arbitrary min height are both gone.
    expect(className).not.toContain("shadow-sm");
    expect(className).not.toContain("min-h-[");
  });

  it("merges caller className over the defaults", () => {
    render(<Textarea className="rounded-none" data-testid="textarea" />);

    // tailwind-merge drops the conflicting default radius.
    expect(screen.getByTestId("textarea").className).not.toContain(
      "rounded-md",
    );
  });

  it("carries the disabled affordance", () => {
    render(<Textarea disabled data-testid="textarea" />);

    const textarea = screen.getByTestId("textarea") as HTMLTextAreaElement;
    expect(textarea.disabled).toBe(true);
    expect(textarea.className).toContain("disabled:cursor-not-allowed");
  });
});
