// PRD trace: FEAT-005 (Provider Profiles and Credential Display).
// #623 (F5): the labelled-field helper's own suite.
//
// The field's contract is narrow and worth pinning on its own: it WRAPS its
// control, and it puts the hint on `aria-describedby` rather than inside the
// `<label>` where it would become part of the accessible NAME. The help moved
// there because a name is what the thing IS and a description is guidance about
// it; "Languages Separate with commas" announced as the field's name is a hint
// read as an identity.
//
// #623 also fixed the degradation path. It reads as a detail and is not one: the
// helper previously called `Children.only`, which THROWS on a fragment or on
// several nodes, so the "render the help unassociated instead" branch its own
// comment described was unreachable for exactly the two cases the comment named.
// A caller who wrapped their input in a fragment got a crash, which is the worse
// of the two outcomes the branch existed to prevent.

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ProfileField } from "./ProfileField";

afterEach(cleanup);

describe("ProfileField", () => {
  it("names the control by the label alone and describes it with the hint", () => {
    render(
      <ProfileField id="about" label="About you" help="What you treat">
        <textarea id="about" />
      </ProfileField>,
    );

    const control = screen.getByLabelText("About you");
    expect(control).toHaveAccessibleName("About you");
    expect(control).toHaveAccessibleDescription("What you treat");
  });

  it("keeps a description the caller already set, rather than replacing it", () => {
    render(
      <ProfileField id="pin" label="PIN code" help="Six digits">
        <input id="pin" aria-describedby="pin-error" data-testid="control" />
      </ProfileField>,
    );

    // Both ids survive: the caller's error AND this field's hint. Overwriting
    // would have silenced the error message the moment a hint was added.
    const described = screen
      .getByTestId("control")
      .getAttribute("aria-describedby");
    expect(described?.split(/\s+/)).toEqual(["pin-error", "pin-help"]);
    expect(screen.getByText("Six digits")).toHaveAttribute("id", "pin-help");
  });

  it("adds nothing when there is no hint to add", () => {
    render(
      <ProfileField id="city" label="City">
        <input id="city" data-testid="control" />
      </ProfileField>,
    );

    expect(screen.getByTestId("control")).not.toHaveAttribute(
      "aria-describedby",
    );
  });

  // The three degradation cases. Each asserted on the OUTCOME - the hint still
  // reaches the page, and nothing crashes - because "it did not throw" is not
  // the requirement; a hint a doctor cannot read is not a fix either.
  it("renders the hint unassociated when the control is wrapped in a fragment", () => {
    render(
      <ProfileField id="city" label="City" help="As it appears on your sign">
        <>
          <input id="city" data-testid="control" />
        </>
      </ProfileField>,
    );

    // No crash, and the guidance is still on the page - just not bound to a
    // control it cannot be sure which one it describes.
    expect(screen.getByTestId("control")).toBeInTheDocument();
    expect(screen.getByText("As it appears on your sign")).toBeInTheDocument();
  });

  it("renders the hint unassociated when several controls are passed", () => {
    render(
      <ProfileField id="city" label="City" help="As it appears on your sign">
        <input id="city" data-testid="control" />
        <input data-testid="extra" />
      </ProfileField>,
    );

    expect(screen.getByTestId("control")).toBeInTheDocument();
    expect(screen.getByTestId("extra")).toBeInTheDocument();
    expect(screen.getByText("As it appears on your sign")).toBeInTheDocument();
  });

  it("renders the hint unassociated when the child is bare text", () => {
    render(
      <ProfileField id="city" label="City" help="As it appears on your sign">
        {"not a control"}
      </ProfileField>,
    );

    expect(screen.getByText("As it appears on your sign")).toBeInTheDocument();
  });
});
