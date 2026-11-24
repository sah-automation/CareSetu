import { describe, expect, test, afterEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  within,
  cleanup,
} from "@testing-library/react";

import { LangProvider } from "@/lib/i18n/LangContext";
import { ProfileMonthGrid } from "./ProfileMonthGrid";

afterEach(() => cleanup());

function renderGrid(props: Parameters<typeof ProfileMonthGrid>[0] = {}) {
  return render(
    <LangProvider>
      <ProfileMonthGrid {...props} />
    </LangProvider>,
  );
}

describe("ProfileMonthGrid", () => {
  test("renders the heading, the per-kind sub and the weekday strip", () => {
    renderGrid({ partnerId: 7, mode: "doctor", hours: null });

    expect(screen.getByTestId("profile-month-grid")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /Availability/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/whole month in one view/i)).toBeInTheDocument();
    expect(screen.getByText(/Consultation slots/)).toBeInTheDocument();
    expect(screen.getByTestId("profile-month-weekdays")).toBeInTheDocument();
    expect(
      within(screen.getByTestId("profile-month-weekdays")).getAllByText(
        /^(Sun|Mon|Tue|Wed|Thu|Fri|Sat)$/,
      ),
    ).toHaveLength(7);
  });

  test("shows the current month and disables prev until navigated away", () => {
    renderGrid({ partnerId: 7, mode: "doctor", hours: null });

    const now = new Date();
    const title = screen.getByTestId("profile-month-title");
    expect(title.textContent).toContain(
      now.toLocaleDateString(undefined, { month: "long", year: "numeric" }),
    );

    const prev = screen.getByTestId("profile-month-prev");
    expect(prev).toBeDisabled();

    const next = screen.getByTestId("profile-month-next");
    expect(next).not.toBeDisabled();
  });

  test("navigates to the next month and back", () => {
    renderGrid({ partnerId: 7, mode: "doctor", hours: null });

    const title = screen.getByTestId("profile-month-title");
    const before = title.textContent;

    fireEvent.click(screen.getByTestId("profile-month-next"));
    expect(screen.getByTestId("profile-month-title").textContent).not.toBe(
      before,
    );

    fireEvent.click(screen.getByTestId("profile-month-prev"));
    expect(screen.getByTestId("profile-month-title").textContent).toBe(before);
  });

  test("selects an open cell and shows the selection callout", () => {
    renderGrid({ partnerId: 7, mode: "doctor", hours: "9am-5pm" });

    const openCells = within(
      screen.getByTestId("profile-month-cells"),
    ).getAllByTestId("profile-month-cell");
    const open = openCells.find((cell) => cell.dataset.state === "open");
    expect(open).toBeDefined();

    fireEvent.click(open!);
    const callout = screen.getByTestId("profile-month-selected");
    expect(callout).toHaveTextContent(/consultation slots/);
    expect(callout).toHaveTextContent(/9am-5pm/);
  });

  test("renders open, closed and past cells with distinct states", () => {
    renderGrid({ partnerId: 7, mode: "doctor", hours: null });

    const cells = within(
      screen.getByTestId("profile-month-cells"),
    ).getAllByTestId("profile-month-cell");
    const withState = cells.filter((c) => c.dataset.state !== undefined);
    expect(withState.length).toBeGreaterThan(0);

    const states = new Set(withState.map((c) => c.dataset.state));
    expect(states.has("open")).toBe(true);
    expect(states.has("closed")).toBe(true);
  });

  test("renders the legend with the per-kind open/closed words", () => {
    renderGrid({ partnerId: 7, mode: "lab", hours: null });

    const legend = screen.getByTestId("profile-month-legend");
    expect(legend).toHaveTextContent("Collection open");
    expect(legend).toHaveTextContent("Closed");
    expect(legend).toHaveTextContent("Today");
  });
});
