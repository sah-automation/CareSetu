// PHASE-6 T05a (#317): directory result card + distance formatter suite.
// The card is the FEAT-005/ADR-0011 guarantee at the presentation layer:
// the verified tick renders only for verified rows, and the unverified row
// renders no card at all (defensive second gate on the shared derivation).
// The card never invents an `area` string the search projection does not carry.

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { DirectoryEntry } from "@/lib/directory/search";
import { DirectoryCard, formatDistanceKm } from "./DirectoryCard";

function entry(overrides: Partial<DirectoryEntry>): DirectoryEntry {
  return {
    partner_id: 1,
    practice_name: "Dr. A. Kumar",
    partner_type: "doctor",
    specialty: "General Physician",
    distance_km: 1.2,
    verified: true,
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
});

describe("formatDistanceKm", () => {
  it("formats to one decimal and composes the localised unit", () => {
    const km = (unit: string) => `${unit} km`;
    expect(formatDistanceKm(1.2, km)).toBe("1.2 km");
    expect(formatDistanceKm(42, km)).toBe("42.0 km");
  });
});

describe("DirectoryCard", () => {
  it("renders verified tick, distance, name and doctor meta, deep-linked to the profile", () => {
    render(
      <DirectoryCard
        entry={entry({})}
        typeLabel="Doctors"
        specialtyLabel="General Physician"
        verifiedLabel="Verified"
        distanceLabel="1.2 km"
      />,
    );

    const card = screen.getByTestId("directory-card");
    expect(card).toHaveAttribute("href", "/providers/1");
    expect(screen.getByText("Verified")).toBeInTheDocument();
    expect(screen.getByText("1.2 km")).toBeInTheDocument();
    expect(screen.getByText("Dr. A. Kumar")).toBeInTheDocument();
    expect(
      screen.getByText(/General Physician \u00b7 Doctors/),
    ).toBeInTheDocument();
    // Exactly one verified badge - the tick is truthful and singular.
    expect(screen.getAllByText("Verified")).toHaveLength(1);
  });

  it("renders no card for an unverified row (tick gone = card gone)", () => {
    render(
      <DirectoryCard
        entry={entry({ verified: false })}
        typeLabel="Doctors"
        specialtyLabel="General Physician"
        verifiedLabel="Verified"
        distanceLabel="1.2 km"
      />,
    );

    expect(screen.queryByTestId("directory-card")).not.toBeInTheDocument();
    expect(screen.queryByText("Dr. A. Kumar")).not.toBeInTheDocument();
  });

  it("shows type-only meta for labs/chemists and falls back when name is null", () => {
    render(
      <DirectoryCard
        entry={entry({
          practice_name: null,
          partner_type: "lab",
          specialty: null,
        })}
        typeLabel="Labs"
        specialtyLabel={null}
        verifiedLabel="Verified"
        distanceLabel="0.8 km"
      />,
    );

    const card = screen.getByTestId("directory-card");
    expect(card).toHaveAttribute("href", "/providers/1");
    expect(screen.getByText("CareSetu provider")).toBeInTheDocument();
    expect(screen.getByText(/^Labs$/)).toBeInTheDocument();
    // No specialty meta for a non-doctor, and no invented area string.
    expect(screen.queryByText(/specialty/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/area/i)).not.toBeInTheDocument();
  });
});
