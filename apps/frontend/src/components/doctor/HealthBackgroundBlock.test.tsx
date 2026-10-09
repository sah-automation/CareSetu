// #679 (parent #673): the shared read-only health-background block. Pins the
// three states - populated (blood group plus five chip areas, empty granted
// areas rendering the plain "None recorded" text), shared-but-empty (the quiet
// "No health background shared yet." note), and not-shared (the calm locked
// card) - so the empty and locked states cannot collapse into each other, and
// that labels travel in as props with no new dictionary fork.

import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import {
  HealthBackgroundBlock,
  type HealthBackgroundLabels,
} from "./HealthBackgroundBlock";
import { STRINGS } from "@/lib/i18n/dictionaries";
import type { HealthBackgroundView } from "@/lib/doctor/api";

afterEach(() => {
  cleanup();
});

const t = STRINGS.en.doctorPatients;
const hiT = STRINGS.hi.doctorPatients;

function view(
  overrides: Partial<HealthBackgroundView> = {},
): HealthBackgroundView {
  return {
    set: true,
    acknowledged: true,
    background: {
      blood_group: "B+",
      conditions: ["Hypertension"],
      allergies: [],
      medications: ["Amlodipine"],
      immunizations: [],
      family_history: ["Father: diabetes"],
    },
    ...overrides,
  };
}

function renderBlock(
  view: HealthBackgroundView | null,
  labels: HealthBackgroundLabels = t,
) {
  return render(
    <HealthBackgroundBlock healthBackground={view} labels={labels} />,
  );
}

describe("HealthBackgroundBlock", () => {
  it("renders the blood group and the five chip areas, empty areas as none recorded", () => {
    renderBlock(view());

    const set = within(screen.getByTestId("health-background-set"));
    expect(set.getByText(t.bloodGroupLabel)).toBeInTheDocument();
    expect(set.getAllByText("B+", { selector: "span" }).length).toBeGreaterThan(
      0,
    );
    // Five area labels: conditions, allergies, medications, immunizations,
    // family history.
    expect(set.getAllByTestId("health-area-label")).toHaveLength(6);
    // Only the populated areas chip; the empty ones keep the plain text.
    expect(set.getAllByTestId("health-chip").map((c) => c.textContent)).toEqual(
      ["Hypertension", "Amlodipine", "Father: diabetes"],
    );
    expect(
      set.getAllByText(t.noneRecorded, { selector: "span" }).length,
    ).toBeGreaterThan(0);
  });

  it("renders a null blood group as none recorded", () => {
    renderBlock(
      view({
        background: {
          blood_group: null,
          conditions: [],
          allergies: [],
          medications: [],
          immunizations: [],
          family_history: [],
        },
      }),
    );

    const set = within(screen.getByTestId("health-background-set"));
    expect(
      set.getAllByText(t.noneRecorded, { selector: "span" }).length,
    ).toBeGreaterThan(0);
  });

  it("renders the quiet empty state when shared but nothing is recorded", () => {
    renderBlock(
      view({
        set: false,
        acknowledged: false,
        background: null,
      }),
    );

    expect(screen.getByTestId("health-background-empty")).toBeInTheDocument();
    expect(screen.getByText(t.healthBackgroundEmpty)).toBeInTheDocument();
    expect(screen.queryByTestId("locked-section")).not.toBeInTheDocument();
    expect(screen.queryByTestId("health-chip")).not.toBeInTheDocument();
  });

  it("renders the locked not-shared card when the section is denied", () => {
    renderBlock(null);

    expect(screen.getByTestId("locked-section")).toBeInTheDocument();
    expect(screen.getByText(t.notSharedTitle)).toBeInTheDocument();
    expect(screen.getByText(t.notSharedBody)).toBeInTheDocument();
    expect(
      screen.queryByTestId("health-background-set"),
    ).not.toBeInTheDocument();
    expect(screen.queryByTestId("health-chip")).not.toBeInTheDocument();
    // A locked section must never read as "no conditions" - the empty state
    // element is absent too.
    expect(
      screen.queryByTestId("health-background-empty"),
    ).not.toBeInTheDocument();
  });

  it("renders Hindi labels passed in verbatim (REQ-006 parity)", () => {
    renderBlock(view(), hiT);

    const set = within(screen.getByTestId("health-background-set"));
    expect(set.getByText(hiT.bloodGroupLabel)).toBeInTheDocument();
    expect(set.getByText(hiT.familyHistoryLabel)).toBeInTheDocument();
    expect(
      set.getAllByText(hiT.noneRecorded, { selector: "span" }).length,
    ).toBeGreaterThan(0);
  });
});
