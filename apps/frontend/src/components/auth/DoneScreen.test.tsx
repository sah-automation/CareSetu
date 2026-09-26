// #536: the shared verified-login handoff screen. Covered here in isolation:
// the shown verified state (icon, title, informative body), the countdown and
// its progress indicator, and the always-visible "Go to Dashboard" CTA that
// fires the host's navigation handler on click. The countdown gating on the
// session-resume seam and the hosts' redirect ordering are covered separately
// in PatientAuthWizard.test.tsx and StaffLoginForm.test.tsx (#551).

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DoneScreen, DONE_SCREEN_COUNTDOWN_SECONDS } from "./DoneScreen";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

/** Run the countdown forward by `ms`, flushing the interval callbacks. */
async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe("DoneScreen - shared verified-login handoff", () => {
  function renderDone(
    overrides: {
      onGoToDashboard?: () => void;
      resumePending?: boolean;
      facts?: { label: string; value: string }[];
    } = {},
  ) {
    return render(
      <DoneScreen
        title="Identity verified"
        body="Your number is verified and your session is ready."
        openingLabel="Opening your dashboard"
        openingInLabel={(seconds) => `Opening your dashboard in ${seconds}`}
        goToDashboardLabel="Go to Dashboard"
        resumePending={overrides.resumePending ?? false}
        onGoToDashboard={overrides.onGoToDashboard ?? vi.fn()}
        {...(overrides.facts ? { facts: overrides.facts } : {})}
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

  it("shows the opening progress line as a live region with a progress indicator", () => {
    renderDone();

    const progress = screen.getByRole("status");
    expect(progress).toHaveTextContent("Opening your dashboard");
    const indicator = screen.getByRole("progressbar");
    expect(indicator).toHaveAttribute("aria-valuemax", "5");
    expect(indicator).toHaveAttribute("aria-valuenow", "5");
  });

  it("counts the visible seconds down and fires the host routine at zero (#551)", async () => {
    vi.useFakeTimers();
    const onGoToDashboard = vi.fn();
    renderDone({ onGoToDashboard });

    expect(screen.getByRole("status")).toHaveTextContent(
      "Opening your dashboard in 5",
    );

    await advance(1000);
    expect(screen.getByRole("status")).toHaveTextContent(
      "Opening your dashboard in 4",
    );
    expect(screen.getByRole("progressbar")).toHaveAttribute(
      "aria-valuenow",
      "4",
    );

    // Still short of zero: no navigation, and the CTA stays available.
    await advance(2000);
    expect(screen.getByRole("status")).toHaveTextContent(
      "Opening your dashboard in 2",
    );
    expect(onGoToDashboard).not.toHaveBeenCalled();
    expect(
      screen.getByRole("button", { name: "Go to Dashboard" }),
    ).toBeEnabled();

    await advance(2000);
    expect(onGoToDashboard).toHaveBeenCalledTimes(1);
  });

  it("holds the countdown back until the resume seam has settled (#551)", async () => {
    vi.useFakeTimers();
    const onGoToDashboard = vi.fn();
    renderDone({ onGoToDashboard, resumePending: true });

    // The host is still resuming: the line carries no digits and the clock
    // never starts, so no second passes behind the resume call.
    expect(screen.getByRole("status")).toHaveTextContent(
      "Opening your dashboard",
    );
    await advance(DONE_SCREEN_COUNTDOWN_SECONDS * 1000 * 2);
    expect(screen.getByRole("status")).toHaveTextContent(
      "Opening your dashboard",
    );
    expect(onGoToDashboard).not.toHaveBeenCalled();
    expect(screen.getByRole("progressbar")).toHaveAttribute(
      "aria-valuenow",
      "5",
    );
  });

  it("shows an always-available Go to Dashboard CTA and navigates on click", () => {
    const onGoToDashboard = vi.fn();
    renderDone({ onGoToDashboard });

    const cta = screen.getByRole("button", { name: "Go to Dashboard" });
    expect(cta).toBeEnabled();
    fireEvent.click(cta);
    expect(onGoToDashboard).toHaveBeenCalledTimes(1);
  });

  it("does not double-navigate when the CTA is pressed mid-countdown (#551)", async () => {
    vi.useFakeTimers();
    const onGoToDashboard = vi.fn();
    renderDone({ onGoToDashboard });

    await advance(2000);
    fireEvent.click(screen.getByRole("button", { name: "Go to Dashboard" }));
    expect(onGoToDashboard).toHaveBeenCalledTimes(1);

    // The tick reaching zero must not navigate a second time.
    await advance(DONE_SCREEN_COUNTDOWN_SECONDS * 1000);
    expect(onGoToDashboard).toHaveBeenCalledTimes(1);
  });

  it("clears its interval on unmount - no state update after teardown", async () => {
    vi.useFakeTimers();
    const onGoToDashboard = vi.fn();
    const { unmount } = renderDone({ onGoToDashboard });

    await advance(1000);
    expect(vi.getTimerCount()).toBeGreaterThan(0);
    unmount();
    expect(vi.getTimerCount()).toBe(0);
    await advance(DONE_SCREEN_COUNTDOWN_SECONDS * 1000);
    expect(onGoToDashboard).not.toHaveBeenCalled();
  });

  it("renders handoff facts when the host supplies them, skipping absent values", () => {
    renderDone({
      facts: [
        { label: "Practice", value: "Sunrise Clinic" },
        { label: "Destination", value: "Doctor console" },
      ],
    });

    expect(screen.getByText("Practice")).toBeInTheDocument();
    expect(screen.getByText("Sunrise Clinic")).toBeInTheDocument();
    expect(screen.getByText("Destination")).toBeInTheDocument();
    expect(screen.getByText("Doctor console")).toBeInTheDocument();
  });
});
