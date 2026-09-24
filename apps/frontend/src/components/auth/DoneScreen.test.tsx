// #536: the shared verified-login handoff screen. Covered here in isolation:
// the shown verified state (icon, title, informative body), the opening
// progress cue, and the always-visible "Go to Dashboard" CTA that fires the
// host's navigation handler on click. The patient-flow redirect ordering is
// covered separately in PatientAuthWizard.test.tsx.

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DoneScreen } from "./DoneScreen";

afterEach(() => {
  cleanup();
});

describe("DoneScreen - shared verified-login handoff", () => {
  function renderDone(overrides: { onGoToDashboard?: () => void } = {}) {
    return render(
      <DoneScreen
        title="Identity verified"
        body="Your number is verified and your session is ready."
        openingLabel="Opening your dashboard"
        goToDashboardLabel="Go to Dashboard"
        onGoToDashboard={overrides.onGoToDashboard ?? vi.fn()}
      />,
    );
  }

  it("renders the verified state with the confirmation icon and copy", () => {
    renderDone();

    expect(
      screen.getByRole("heading", { name: "Identity verified" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Your number is verified and your session is ready."),
    ).toBeInTheDocument();
    expect(document.querySelector("svg")).not.toBeNull();
  });

  it("renders the opening progress cue as a live region", () => {
    renderDone();

    const progress = screen.getByRole("status");
    expect(progress).toHaveTextContent("Opening your dashboard");
  });

  it("shows an always-available Go to Dashboard CTA and navigates on click", () => {
    const onGoToDashboard = vi.fn();
    renderDone({ onGoToDashboard });

    const cta = screen.getByRole("button", { name: "Go to Dashboard" });
    expect(cta).toBeEnabled();
    fireEvent.click(cta);
    expect(onGoToDashboard).toHaveBeenCalledTimes(1);
  });
});
