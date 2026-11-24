// #967 (FEAT-004): FilterSheet bottom-sheet suite - open/close, the specialty
// checkbox wiring to the parent's commit (first checked in closed pick-list
// order), client-side counts from the loaded items, Reset/Show actions, and
// the per-type sections (doctors / labs / chemists) matching the prototype.

import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { DirectoryEntry } from "@/lib/directory/search";
import { FilterSheet } from "./FilterSheet";

function entry(
  id: number,
  practiceName: string,
  overrides: Partial<DirectoryEntry> = {},
): DirectoryEntry {
  return {
    partner_id: id,
    practice_name: practiceName,
    partner_type: "doctor",
    specialty: null,
    area: null,
    distance_km: 1,
    verified: true,
    consultation_fee: null,
    ...overrides,
  };
}

type SheetProps = Partial<Parameters<typeof FilterSheet>[0]>;

function renderSheet(props: SheetProps = {}) {
  const onCommit = vi.fn();
  const onOpenChange = vi.fn();
  const utils = render(
    <FilterSheet
      open
      onOpenChange={onOpenChange}
      sectionType="doctor"
      specialty={null}
      location={null}
      items={[]}
      onCommit={onCommit}
      {...props}
    />,
  );
  return { ...utils, onCommit, onOpenChange };
}

function rowFor(label: string): HTMLElement {
  const row = screen
    .getByText(label)
    .closest('[data-testid="filter-check-row"]');
  if (!row) throw new Error(`no filter-check-row for ${label}`);
  return row as HTMLElement;
}

afterEach(() => {
  cleanup();
});

describe("FilterSheet open/close", () => {
  it("renders the dialog with the Filters title when open", () => {
    renderSheet();

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByTestId("filter-sheet")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Filters" }),
    ).toBeInTheDocument();
  });

  it("calls onOpenChange(false) from the built-in close button", () => {
    const { onOpenChange } = renderSheet();

    fireEvent.click(screen.getByRole("button", { name: /close/i }));

    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("calls onOpenChange(false) from Show", () => {
    const { onOpenChange } = renderSheet({ items: [entry(1, "Dr. A")] });

    fireEvent.click(screen.getByTestId("filter-show"));

    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});

describe("FilterSheet doctor sections", () => {
  it("lists specialty checkboxes with client-side counts from items", () => {
    renderSheet({
      items: [
        entry(1, "Dr. A", { specialty: "General Physician" }),
        entry(2, "Dr. B", { specialty: "General Physician" }),
        entry(3, "Dr. C", { specialty: "Pediatrician" }),
      ],
    });

    expect(rowFor("General Physician")).toHaveTextContent("General Physician2");
    expect(rowFor("Pediatrician")).toHaveTextContent("Pediatrician1");
    expect(rowFor("Dentist")).toHaveTextContent("Dentist0");
  });

  it("updates counts when the loaded results change", () => {
    const { rerender } = renderSheet({
      items: [entry(1, "Dr. A", { specialty: "Dentist" })],
    });

    expect(rowFor("Dentist")).toHaveTextContent("Dentist1");

    rerender(
      <FilterSheet
        open
        onOpenChange={vi.fn()}
        sectionType="doctor"
        specialty={null}
        location={null}
        items={[
          entry(1, "Dr. A", { specialty: "Dentist" }),
          entry(2, "Dr. B", { specialty: "Dentist" }),
        ]}
        onCommit={vi.fn()}
      />,
    );

    expect(rowFor("Dentist")).toHaveTextContent("Dentist2");
  });

  it("wires a checked specialty to the commit payload", () => {
    const { onCommit } = renderSheet();

    fireEvent.click(
      within(rowFor("Pediatrician")).getByTestId("filter-checkbox"),
    );

    expect(onCommit).toHaveBeenLastCalledWith({
      specialty: "Pediatrician",
    });
  });

  it("wires the first checked specialty in closed pick-list order when several are checked", () => {
    const { onCommit } = renderSheet();

    // Pediatrician sits after General Physician in the closed pick-list, so
    // once both are checked the list-order first (General Physician) wins.
    fireEvent.click(
      within(rowFor("Pediatrician")).getByTestId("filter-checkbox"),
    );
    fireEvent.click(
      within(rowFor("General Physician")).getByTestId("filter-checkbox"),
    );

    expect(onCommit).toHaveBeenLastCalledWith({
      specialty: "General Physician",
    });
  });

  it("commits null when the last checked specialty is unchecked", () => {
    const { onCommit } = renderSheet({ specialty: "Pediatrician" });

    expect(
      within(rowFor("Pediatrician")).getByTestId("filter-checkbox"),
    ).toBeChecked();

    fireEvent.click(
      within(rowFor("Pediatrician")).getByTestId("filter-checkbox"),
    );

    expect(onCommit).toHaveBeenLastCalledWith({ specialty: null });
  });

  it("seeds the checked specialty from the committed prop on open", () => {
    renderSheet({ specialty: "Dentist" });

    expect(
      within(rowFor("Dentist")).getByTestId("filter-checkbox"),
    ).toBeChecked();
    expect(
      within(rowFor("Pediatrician")).getByTestId("filter-checkbox"),
    ).not.toBeChecked();
  });

  it("renders the cosmetic consult-type radio group", () => {
    renderSheet();

    const group = screen.getByRole("radiogroup", {
      name: "Consultation type",
    });
    expect(within(group).getByRole("radio", { name: "All" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    fireEvent.click(within(group).getByRole("radio", { name: "Online" }));
    expect(
      within(group).getByRole("radio", { name: "Online" }),
    ).toHaveAttribute("aria-checked", "true");
  });
});

describe("FilterSheet location draft", () => {
  it("commits the location draft on blur when it changed", () => {
    const { onCommit } = renderSheet({ location: null });

    const input = screen.getByTestId("filter-location-input");
    fireEvent.change(input, { target: { value: "Daltonganj" } });
    fireEvent.blur(input);

    expect(onCommit).toHaveBeenLastCalledWith({
      location: "Daltonganj",
    });
  });

  it("does not commit an unchanged location on blur", () => {
    const { onCommit } = renderSheet({ location: "Daltonganj" });

    fireEvent.blur(screen.getByTestId("filter-location-input"));

    expect(onCommit).not.toHaveBeenCalled();
  });
});

describe("FilterSheet Reset and Show", () => {
  it("Reset clears type, q, specialty, and location via the commit payload", () => {
    const { onCommit } = renderSheet({
      specialty: "Dentist",
      location: "Daltonganj",
    });

    fireEvent.click(screen.getByTestId("filter-reset"));

    expect(onCommit).toHaveBeenCalledWith({
      type: null,
      q: null,
      specialty: null,
      location: null,
    });
  });

  it("Show labels the current result count and closes the sheet", () => {
    const { onOpenChange } = renderSheet({
      items: [entry(1, "Dr. A"), entry(2, "Dr. B"), entry(3, "Dr. C")],
    });

    const show = screen.getByTestId("filter-show");
    expect(show).toHaveTextContent("Show 3 doctors");

    fireEvent.click(show);
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});

describe("FilterSheet lab sections", () => {
  it("renders test-type checkboxes with counts and cosmetic services", () => {
    renderSheet({
      sectionType: "lab",
      items: [
        entry(1, "Sahyog Blood Centre", { partner_type: "lab" }),
        entry(2, "City X-Ray Clinic", { partner_type: "lab" }),
        entry(3, "Care Path Labs", { partner_type: "lab" }),
      ],
    });

    expect(rowFor("Blood tests")).toHaveTextContent("Blood tests1");
    expect(rowFor("X-ray")).toHaveTextContent("X-ray1");
    expect(rowFor("Pathology")).toHaveTextContent("Pathology1");
    expect(rowFor("ECG")).toHaveTextContent("ECG0");

    expect(screen.getByLabelText("Home collection")).toBeInTheDocument();
    expect(screen.getByLabelText("NABL accredited only")).toBeInTheDocument();

    expect(screen.getByTestId("filter-show")).toHaveTextContent("Show 3 labs");
  });

  it("toggles a service checkbox without committing anything", () => {
    const { onCommit } = renderSheet({ sectionType: "lab" });

    fireEvent.click(screen.getByLabelText("Home collection"));

    expect(screen.getByLabelText("Home collection")).toBeChecked();
    expect(onCommit).not.toHaveBeenCalled();
  });
});

describe("FilterSheet chemist sections", () => {
  it("renders service checkboxes and the availability radio", () => {
    renderSheet({
      sectionType: "chemist",
      items: [entry(1, "Sharma Medical", { partner_type: "chemist" })],
    });

    expect(screen.getByLabelText("Home delivery")).toBeInTheDocument();
    expect(
      screen.getByLabelText("E-prescription delivery"),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Generic medicines")).toBeInTheDocument();

    const group = screen.getByRole("radiogroup", { name: "Availability" });
    expect(
      within(group).getByRole("radio", { name: "Any time" }),
    ).toHaveAttribute("aria-checked", "true");
    fireEvent.click(within(group).getByRole("radio", { name: "Open now" }));
    expect(
      within(group).getByRole("radio", { name: "Open now" }),
    ).toHaveAttribute("aria-checked", "true");

    expect(screen.getByTestId("filter-show")).toHaveTextContent(
      "Show 1 chemists",
    );
  });

  it("does not render doctor specialty sections", () => {
    renderSheet({ sectionType: "chemist" });

    expect(
      document.querySelector(
        '[data-testid="filter-check-row"][data-section="specialty"]',
      ),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("radiogroup", { name: "Consultation type" }),
    ).not.toBeInTheDocument();
  });
});
