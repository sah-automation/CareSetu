// PHASE-2.6 T08 (#199): suite for the empty-state pattern (blueprint §9.1) -
// what-this-is, why-it-is-empty, exactly one next action, styled neutral.

import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, afterEach } from "vitest";

import { EmptyState } from "./EmptyState";

afterEach(() => {
  cleanup();
});

describe("EmptyState", () => {
  it("renders the what-this-is title", () => {
    render(<EmptyState title="No reports yet" />);

    expect(screen.getByTestId("empty-state-title")).toHaveTextContent(
      "No reports yet",
    );
  });

  it("renders the why-it-is-empty body and one next action", () => {
    const onClick = vi.fn();
    render(
      <EmptyState
        title="No reports yet"
        body="Reports your lab uploads appear here."
        action={<button onClick={onClick}>Book a lab test</button>}
      />,
    );

    expect(
      screen.getByText("Reports your lab uploads appear here."),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Book a lab test" }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("is styled neutral/soft (accent-soft), never like an error", () => {
    render(<EmptyState title="Nothing here" />);

    const state = screen.getByTestId("empty-state");
    expect(state.className).toContain("bg-accent-soft");
    expect(state.className).not.toContain("danger");
  });
});
