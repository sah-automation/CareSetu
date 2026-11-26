import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { describe, it, expect, afterEach } from "vitest";

// #600 - the Switch primitive adopted over the #193 design tokens. It is a
// Radix-controlled button, so what is worth pinning is the checked state it
// reports and the two track states it resolves.
import { Switch } from "./switch";

afterEach(() => {
  cleanup();
});

describe("Switch", () => {
  it("reports its checked state through role, aria-checked and data-state", () => {
    render(<Switch aria-label="Appointment reminders" />);

    const control = screen.getByRole("switch", {
      name: "Appointment reminders",
    });
    expect(control).toHaveAttribute("aria-checked", "false");
    expect(control).toHaveAttribute("data-state", "unchecked");
  });

  it("flips to checked when pressed", () => {
    render(<Switch aria-label="Appointment reminders" />);

    const control = screen.getByRole("switch");
    fireEvent.click(control);

    expect(control).toHaveAttribute("aria-checked", "true");
    expect(control).toHaveAttribute("data-state", "checked");
  });

  it("honours a controlled checked value", () => {
    render(<Switch checked aria-label="Appointment reminders" />);

    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "true");
  });

  it("reports checked state as the controlled value changes", () => {
    const { rerender } = render(
      <Switch checked={false} aria-label="Appointment reminders" />,
    );
    expect(screen.getByRole("switch")).toHaveAttribute(
      "data-state",
      "unchecked",
    );

    rerender(<Switch checked aria-label="Appointment reminders" />);
    expect(screen.getByRole("switch")).toHaveAttribute("data-state", "checked");
  });

  it("carries a knob and resolves both track states through tokens", () => {
    render(<Switch aria-label="Reminders" />);

    const control = screen.getByRole("switch");
    // Checked is the solid brand slot; unchecked is the hairline slot, and it
    // takes the matching edge because that grey has no visible outline on a
    // white surface.
    expect(control.className).toContain("data-[state=checked]:bg-primary");
    expect(control.className).toContain("data-[state=unchecked]:bg-input");
    expect(control.className).toContain("data-[state=unchecked]:border-input");
    // No stock elevation step survived the bridge.
    expect(control.className).not.toContain("shadow-sm");

    const knob = control.querySelector("span");
    expect(knob?.className).toContain("bg-surface");
    expect(knob?.className).toContain("shadow-card");
    expect(knob?.className).not.toContain("shadow-lg");
  });

  it("carries the disabled affordance and does not flip", () => {
    render(<Switch disabled aria-label="Reminders" />);

    const control = screen.getByRole("switch");
    expect(control).toBeDisabled();
    expect(control.className).toContain("disabled:cursor-not-allowed");

    fireEvent.click(control);
    expect(control).toHaveAttribute("aria-checked", "false");
  });
});
