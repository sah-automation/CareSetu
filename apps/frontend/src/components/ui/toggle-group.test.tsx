import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, afterEach, vi } from "vitest";

// PRD trace: FEAT-005 (Provider Profiles and Credential Display).
// #600 - the ToggleGroup primitive adopted over the #193 design tokens. It is
// the one primitive the ticket calls out for pressed-state and keyboard
// assertions, so both are pinned here: per-item pressed state, and that the
// keyboard path is left open to the browser's native button activation.
//
// #623: the activation cases drive `user-event` rather than following the key
// events with a synthetic `fireEvent.click`. That click was doing the browser's
// job for it, so every state change in this file came from a mouse even though
// the suite claimed to be about the keyboard - and the claim was the part that
// mattered, because "operable from the keyboard alone" is an accessibility
// promise about a doctor who never touches a pointer. `user-event` implements
// the browser's default action for a key on a focused native button, so the
// click now comes from the keypress. The repo had no `user-event`; #623 added it
// rather than leaving the simulation in place.
import { ToggleGroup, ToggleGroupItem, toggleVariants } from "./toggle-group";

afterEach(() => {
  cleanup();
});

function specialties(type: "single" | "multiple") {
  return (
    <ToggleGroup type={type} aria-label="Specialties">
      <ToggleGroupItem value="general">General Physician</ToggleGroupItem>
      <ToggleGroupItem value="pediatrics">Pediatrician</ToggleGroupItem>
      <ToggleGroupItem value="dentist">Dentist</ToggleGroupItem>
    </ToggleGroup>
  );
}

/**
 * Presses an activation key on a focused item the way a browser does.
 *
 * Two assertions, and they are the primitive's whole responsibility split:
 *
 *   1. The key event is not default-prevented, so the browser is free to perform
 *      its native activation on the focused `<button>`. A primitive that swallowed
 *      the key fails on the `fireEvent` return value.
 *   2. The state change then arrives on its own, because `user-event` runs the
 *      browser's default action for that key on that element - the same click a
 *      real browser synthesises, produced here by the keypress rather than
 *      dispatched by hand.
 *
 * Before #623 the second step was an explicit `fireEvent.click`, which meant the
 * suite proved only that clicking worked and asserted the keyboard in a comment.
 */
async function pressKey(control: HTMLElement, key: " " | "Enter") {
  const user = userEvent.setup();
  control.focus();
  expect(
    fireEvent.keyDown(control, { key }),
    `keyDown "${key}" was default-prevented`,
  ).toBe(true);
  // `{Enter}` is user-event's syntax for pressing a named key. Without the
  // braces it types the five characters "Enter" instead, which presses nothing
  // - and pressing nothing is exactly what a test claiming keyboard
  // operability must never be able to pass as.
  await user.keyboard(key === "Enter" ? "{Enter}" : " ");
  expect(
    fireEvent.keyUp(control, { key }),
    `keyUp "${key}" was default-prevented`,
  ).toBe(true);
}

describe("ToggleGroup", () => {
  it("renders one natively focusable button per item", async () => {
    render(specialties("multiple"));

    for (const name of ["General Physician", "Pediatrician", "Dentist"]) {
      const control = screen.getByRole("button", { name });
      expect(control.tagName).toBe("BUTTON");
      expect(control).toHaveAttribute("type", "button");
    }
  });

  it("reports unpressed state per item to begin with", async () => {
    render(specialties("multiple"));

    for (const name of ["General Physician", "Pediatrician", "Dentist"]) {
      expect(screen.getByRole("button", { name })).toHaveAttribute(
        "aria-pressed",
        "false",
      );
      expect(screen.getByRole("button", { name })).toHaveAttribute(
        "data-state",
        "off",
      );
    }
  });

  it("leaves the activation keys to the browser instead of swallowing them", async () => {
    render(specialties("multiple"));

    // The keyboard contract, stated directly: nothing on the item calls
    // preventDefault for Space or Enter, so the browser performs the native
    // button activation itself. This is the half of "operable from the keyboard
    // alone" that a jsdom test can assert; the other half is the button tag,
    // asserted in the test above.
    for (const key of [" ", "Enter"] as const) {
      const control = screen.getByRole("button", { name: "General Physician" });
      expect(fireEvent.keyDown(control, { key }), `keyDown "${key}"`).toBe(
        true,
      );
      expect(fireEvent.keyUp(control, { key }), `keyUp "${key}"`).toBe(true);
      // Neither key alone changes the state - nothing in the primitive listens.
      expect(control).toHaveAttribute("aria-pressed", "false");
    }
  });

  it("reports pressed state per item once a focused item is activated", async () => {
    render(specialties("multiple"));

    // No pointer event: focus the item, then press Space on it.
    const general = screen.getByRole("button", { name: "General Physician" });
    general.focus();
    await pressKey(general, " ");

    expect(general).toHaveAttribute("aria-pressed", "true");
    expect(general).toHaveAttribute("data-state", "on");
    // Pressed state is per item - its siblings are untouched.
    expect(
      screen.getByRole("button", { name: "Pediatrician" }),
    ).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "Dentist" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("accumulates a multi-select from the keyboard", async () => {
    render(specialties("multiple"));

    for (const name of ["General Physician", "Pediatrician"]) {
      const control = screen.getByRole("button", { name });
      control.focus();
      await pressKey(control, " ");
    }

    expect(
      screen.getByRole("button", { name: "General Physician" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByRole("button", { name: "Pediatrician" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Dentist" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("also answers Enter, the other key a native button takes", async () => {
    render(specialties("multiple"));

    const general = screen.getByRole("button", { name: "General Physician" });
    general.focus();
    await pressKey(general, "Enter");

    expect(general).toHaveAttribute("aria-pressed", "true");
  });

  it("un-presses an item pressed twice", async () => {
    render(specialties("multiple"));

    const general = screen.getByRole("button", { name: "General Physician" });
    general.focus();
    await pressKey(general, " ");
    await pressKey(general, " ");

    expect(general).toHaveAttribute("aria-pressed", "false");
    expect(general).toHaveAttribute("data-state", "off");
  });

  it("carries the multi-select group's toolbar role", async () => {
    render(specialties("multiple"));

    expect(
      screen.getByRole("toolbar", { name: "Specialties" }),
    ).toBeInTheDocument();
  });

  it("reports single-select selection through radio semantics", async () => {
    render(specialties("single"));

    // Radix maps `single` onto radio semantics, not aria-pressed.
    const pediatrics = screen.getByRole("radio", { name: "Pediatrician" });
    expect(pediatrics).toHaveAttribute("aria-checked", "false");
    expect(
      screen.getByRole("radiogroup", { name: "Specialties" }),
    ).toBeInTheDocument();

    await pressKey(pediatrics, " ");
    expect(pediatrics).toHaveAttribute("aria-checked", "true");

    // Single-select: choosing the next one releases the previous.
    const dentist = screen.getByRole("radio", { name: "Dentist" });
    await pressKey(dentist, " ");
    expect(dentist).toHaveAttribute("aria-checked", "true");
    expect(pediatrics).toHaveAttribute("aria-checked", "false");
  });

  it("honours a controlled value and reports it back on change", async () => {
    const onValueChange = vi.fn();
    render(
      <ToggleGroup
        type="multiple"
        value={["general"]}
        onValueChange={onValueChange}
        aria-label="Specialties"
      >
        <ToggleGroupItem value="general">General Physician</ToggleGroupItem>
        <ToggleGroupItem value="pediatrics">Pediatrician</ToggleGroupItem>
      </ToggleGroup>,
    );

    expect(
      screen.getByRole("button", { name: "General Physician" }),
    ).toHaveAttribute("aria-pressed", "true");

    await pressKey(screen.getByRole("button", { name: "Pediatrician" }), " ");
    // Uncontrolled from the item's point of view: it reports the whole next
    // selection and lets the owner decide.
    expect(onValueChange).toHaveBeenCalledWith(["general", "pediatrics"]);
  });

  it("resolves the selected state to the accent-soft / accent-strong pair", async () => {
    expect(toggleVariants()).toContain("data-[state=on]:bg-accent-soft");
    expect(toggleVariants()).toContain("data-[state=on]:text-accent-strong");
    // `accent-foreground` is not a token in this app (#193) - upstream's pair
    // would not resolve, which is why both halves were re-pointed.
    expect(toggleVariants()).not.toContain("accent-foreground");
  });

  it("gives the outline variant a token edge and token elevation", async () => {
    expect(toggleVariants({ variant: "outline" })).toContain("border-input");
    expect(toggleVariants({ variant: "outline" })).toContain("shadow-card");
    expect(toggleVariants({ variant: "outline" })).not.toContain("shadow-sm");
  });

  it("applies the group variant and size to every item", async () => {
    render(
      <ToggleGroup type="multiple" variant="outline" size="sm">
        <ToggleGroupItem value="general" data-testid="general">
          General Physician
        </ToggleGroupItem>
      </ToggleGroup>,
    );

    const className = screen.getByTestId("general").className;
    expect(className).toContain("border-input");
    expect(className).toContain("h-9");
  });

  it("lets an item pick its own size only when the group sets none", async () => {
    const { rerender } = render(
      <ToggleGroup type="multiple">
        <ToggleGroupItem value="general" size="lg" data-testid="general">
          General Physician
        </ToggleGroupItem>
      </ToggleGroup>,
    );
    expect(screen.getByTestId("general").className).toContain("h-11");

    // Upstream precedence, pinned: a group-level value wins over the item's own.
    rerender(
      <ToggleGroup type="multiple" size="sm">
        <ToggleGroupItem value="general" size="lg" data-testid="general">
          General Physician
        </ToggleGroupItem>
      </ToggleGroup>,
    );
    expect(screen.getByTestId("general").className).toContain("h-9");
  });

  it("marks every item disabled and refuses the keyboard when the group is", async () => {
    render(
      <ToggleGroup type="multiple" disabled aria-label="Specialties">
        <ToggleGroupItem value="general">General Physician</ToggleGroupItem>
      </ToggleGroup>,
    );

    const general = screen.getByRole("button", { name: "General Physician" });
    expect(general).toBeDisabled();
    general.focus();
    await pressKey(general, " ");

    expect(general).toHaveAttribute("aria-pressed", "false");
  });
});
