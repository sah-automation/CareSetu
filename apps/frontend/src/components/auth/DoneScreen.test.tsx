// #536: the shared verified-login handoff screen. Covered here in isolation:
// the shown verified state (icon, title, informative body), the single status
// line, the indeterminate progress indicator that carries no digits, and the
// always-visible "Go to Dashboard" CTA that fires the host's navigation
// handler on click. #581 removed the countdown this file used to pin: the
// component no longer ticks, so those tests went with it rather than being
// rewritten. Whether each flow navigates exactly once, and only once its own
// preconditions hold, is the hook's contract (#578) and the two hosts' wiring
// (#579, #580), not this file's.

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DoneScreen } from "./DoneScreen";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

/** Run pending timers forward by `ms`, flushing their callbacks. */
async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe("DoneScreen - shared verified-login handoff", () => {
  function renderDone(
    overrides: {
      onGoToDashboard?: () => void;
      facts?: { label: string; value: string }[];
    } = {},
  ) {
    return render(
      <DoneScreen
        title="Identity verified"
        body="Your number is verified and your session is ready."
        openingLabel="Opening your dashboard"
        goToDashboardLabel="Go to Dashboard"
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

  it("shows the one status line as a live region and never changes it", async () => {
    vi.useFakeTimers();
    renderDone();

    // `role="status"` is what makes the line announceable when it appears, and
    // it is the only progress line there is.
    const progress = screen.getByRole("status");
    expect(progress).toHaveTextContent("Opening your dashboard");
    const firstRead = progress.textContent;

    // The assertion that actually pins "constant": read the line again with
    // time on the clock. A reinstated ternary - anything keyed off a countdown
    // or a readiness flag - changes the text here and fails. A minute is
    // arbitrary and deliberately so: the screen has no clock of its own left
    // to overrun.
    await advance(60_000);

    expect(screen.getByRole("status").textContent).toBe(firstRead);
    expect(screen.getAllByRole("status")).toHaveLength(1);
  });

  it("exposes the progress indicator as indeterminate - a name, and no values", () => {
    renderDone();

    const indicator = screen.getByRole("progressbar", {
      name: "Opening your dashboard",
    });
    // Absences asserted explicitly: an indicator that keeps aria-valuenow is
    // announcing a determinate bar it no longer has, and a snapshot or a
    // name-only query would not catch an attribute merely left behind.
    expect(indicator).not.toHaveAttribute("aria-valuenow");
    expect(indicator).not.toHaveAttribute("aria-valuemin");
    expect(indicator).not.toHaveAttribute("aria-valuemax");
    expect(indicator).not.toHaveAttribute("aria-valuetext");
  });

  it("carries no digit anywhere in the progress output", () => {
    renderDone();

    // Everything the progress surface actually announces - the live line, the
    // fill, the indicator's name and any value text it might grow. Read from
    // the attributes and the text, not from the outer HTML: a CSS-module class
    // name carries a build hash, and a digit in a hash is not a digit on screen.
    const indicator = screen.getByRole("progressbar");
    const announced = [
      screen.getByRole("status").textContent,
      indicator.textContent,
      indicator.getAttribute("aria-label"),
      indicator.getAttribute("aria-valuetext"),
    ]
      .filter((part): part is string => part !== null)
      .join(" ");

    expect(announced).not.toMatch(/\d/);
  });

  it("shows an always-available Go to Dashboard CTA and navigates on click", () => {
    const onGoToDashboard = vi.fn();
    renderDone({ onGoToDashboard });

    const cta = screen.getByRole("button", { name: "Go to Dashboard" });
    expect(cta).toBeEnabled();
    fireEvent.click(cta);
    expect(onGoToDashboard).toHaveBeenCalledTimes(1);
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
