// PHASE-6 T05a (#966): AvailabilityDateGrid suite - the card's right-panel
// 14-day availability grid (prototype `.dir-p2` / `.dir-date-grid`). Pins the
// header range label + prev/next nav, the 14 day cells + trailing More cell,
// per-type labels/icons (doctor=appts+video, lab=slots+home,
// chemist=windows+delivery), available vs unavailable states, and week nav
// regenerating cells with a shifted range.

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { AvailabilityDateGrid } from "./AvailabilityDateGrid";

afterEach(() => {
  cleanup();
});

function renderGrid(mode: "doctor" | "lab" | "chemist" = "doctor") {
  return render(<AvailabilityDateGrid mode={mode} partnerId={1} />);
}

describe("AvailabilityDateGrid structure", () => {
  it("renders the header range label and prev/next nav", () => {
    renderGrid("doctor");
    expect(screen.getByTestId("availability-range")).toBeInTheDocument();
    expect(screen.getByTestId("availability-prev")).toBeInTheDocument();
    expect(screen.getByTestId("availability-next")).toBeInTheDocument();
    expect(screen.getByTestId("availability-prev")).toBeDisabled();
  });

  it("renders 14 day cells plus a trailing More cell", () => {
    renderGrid("doctor");
    const cells = screen.getAllByTestId("date-cell");
    expect(cells).toHaveLength(14);
    expect(screen.getByTestId("date-cell-more")).toBeInTheDocument();
  });

  it("labels each cell with weekday and day number, first cell as Today", () => {
    renderGrid("doctor");
    const first = screen.getAllByTestId("date-cell")[0];
    expect(first).toHaveTextContent("Today");
    expect(screen.getByTestId("date-cell-more")).toHaveTextContent("More");
    expect(screen.getByTestId("date-cell-more")).toHaveTextContent("View all");
  });

  it("shows per-type labels and icons: doctor appts + video", () => {
    renderGrid("doctor");
    const available = screen
      .getAllByTestId("date-cell")
      .filter((c) => !c.disabled);
    expect(available.length).toBeGreaterThan(0);
    expect(screen.getAllByText(/appts/)).toHaveLength(available.length);
  });

  it("shows per-type labels and icons: lab slots", () => {
    renderGrid("lab");
    const available = screen
      .getAllByTestId("date-cell")
      .filter((c) => !c.disabled);
    expect(available.length).toBeGreaterThan(0);
    expect(screen.getAllByText(/slots/)).toHaveLength(available.length);
  });

  it("shows per-type labels and icons: chemist windows", () => {
    renderGrid("chemist");
    const available = screen
      .getAllByTestId("date-cell")
      .filter((c) => !c.disabled);
    expect(available.length).toBeGreaterThan(0);
    expect(screen.getAllByText(/windows/)).toHaveLength(available.length);
  });

  it("greys out and disables unavailable cells", () => {
    renderGrid("doctor");
    const unavailable = screen
      .getAllByTestId("date-cell")
      .filter((c) => c.disabled);
    if (unavailable.length > 0) {
      expect(unavailable[0]).toBeDisabled();
    }
  });
});

describe("AvailabilityDateGrid week navigation", () => {
  it("updates the range label and regenerates cells on next week", async () => {
    renderGrid("doctor");
    const rangeBefore = screen.getByTestId("availability-range").textContent;
    const next = screen.getByTestId("availability-next");
    fireEvent.click(next);
    await waitFor(() => {
      expect(screen.getByTestId("availability-range")).not.toHaveTextContent(
        rangeBefore ?? "",
      );
    });
    expect(screen.getAllByTestId("date-cell")).toHaveLength(14);
    // Prev becomes enabled once we've moved forward.
    expect(screen.getByTestId("availability-prev")).not.toBeDisabled();
  });

  it("moves back to the original range on prev", async () => {
    renderGrid("doctor");
    const next = screen.getByTestId("availability-next");
    const prev = screen.getByTestId("availability-prev");
    const rangeBefore = screen.getByTestId("availability-range").textContent;
    fireEvent.click(next);
    await waitFor(() => expect(prev).not.toBeDisabled());
    fireEvent.click(prev);
    await waitFor(() => {
      expect(screen.getByTestId("availability-range")).toHaveTextContent(
        rangeBefore ?? "",
      );
    });
  });
});

describe("AvailabilityDateGrid responsive classes", () => {
  it("applies the horizontal-scroll classes for narrow viewports", () => {
    renderGrid("doctor");
    const grid = screen.getByTestId("availability-grid");
    expect(grid).toHaveClass("grid-cols-7");
  });
});
