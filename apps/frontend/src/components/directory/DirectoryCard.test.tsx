// PHASE-6 T05a (#317): directory result card + distance formatter suite.
// The card is the FEAT-005/ADR-0011 guarantee at the presentation layer:
// the verified tick renders only for verified rows, and the unverified row
// renders no card at all (defensive second gate on the shared derivation).
// The card renders area among non-null meta, never inventing a string.

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { DirectoryEntry } from "@/lib/directory/search";
import { DirectoryCard, formatDistanceKm } from "./DirectoryCard";

const { emitPartnerSelected } = vi.hoisted(() => ({
  emitPartnerSelected: vi.fn(),
}));

vi.mock("@/lib/directory/emit", () => ({ emitPartnerSelected }));

function entry(overrides: Partial<DirectoryEntry>): DirectoryEntry {
  return {
    partner_id: 1,
    practice_name: "Dr. A. Kumar",
    partner_type: "doctor",
    specialty: "General Physician",
    area: null,
    distance_km: 1.2,
    verified: true,
    ...overrides,
  };
}

afterEach(() => {
  emitPartnerSelected.mockClear();
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

  it("renders area in the meta line when non-null", () => {
    render(
      <DirectoryCard
        entry={entry({ area: "Medininagar Rd" })}
        typeLabel="Doctors"
        specialtyLabel="General Physician"
        verifiedLabel="Verified"
        distanceLabel="1.2 km"
      />,
    );

    expect(
      screen.getByText(
        /General Physician \u00b7 Doctors \u00b7 Medininagar Rd/,
      ),
    ).toBeInTheDocument();
    // Exactly one verified badge.
    expect(screen.getAllByText("Verified")).toHaveLength(1);
  });

  it("renders no area copy when area is null", () => {
    render(
      <DirectoryCard
        entry={entry({ area: null })}
        typeLabel="Doctors"
        specialtyLabel="General Physician"
        verifiedLabel="Verified"
        distanceLabel="1.2 km"
      />,
    );

    expect(
      screen.getByText(/General Physician \u00b7 Doctors/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Medininagar/)).not.toBeInTheDocument();
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

describe("DirectoryCard partner.selected emission (T6)", () => {
  it("fires the anonymous pick exactly once on a card tap", () => {
    render(
      <DirectoryCard
        entry={entry({})}
        typeLabel="Doctors"
        specialtyLabel="General Physician"
        verifiedLabel="Verified"
        distanceLabel="1.2 km"
      />,
    );

    // A rendered card starts with zero emissions - no fire on render.
    expect(emitPartnerSelected).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId("directory-card"));

    // Exactly one anonymous pick with the card's pick-only facts.
    expect(emitPartnerSelected).toHaveBeenCalledTimes(1);
    expect(emitPartnerSelected).toHaveBeenCalledWith({
      partner_id: 1,
      partner_type: "doctor",
      source: "search_card",
    });
  });

  it("does not double-fire on re-render - only the tap emits", () => {
    const { rerender } = render(
      <DirectoryCard
        entry={entry({})}
        typeLabel="Doctors"
        specialtyLabel="General Physician"
        verifiedLabel="Verified"
        distanceLabel="1.2 km"
      />,
    );

    rerender(
      <DirectoryCard
        entry={entry({})}
        typeLabel="Doctors"
        specialtyLabel="General Physician"
        verifiedLabel="Verified"
        distanceLabel="1.2 km"
      />,
    );

    // Re-render alone must not emit - only a user tap does.
    expect(emitPartnerSelected).not.toHaveBeenCalled();
  });

  it("carries the partner type and id of a lab card", () => {
    render(
      <DirectoryCard
        entry={entry({
          partner_id: 9,
          partner_type: "lab",
          specialty: null,
        })}
        typeLabel="Labs"
        specialtyLabel={null}
        verifiedLabel="Verified"
        distanceLabel="0.8 km"
      />,
    );

    fireEvent.click(screen.getByTestId("directory-card"));

    expect(emitPartnerSelected).toHaveBeenCalledTimes(1);
    expect(emitPartnerSelected).toHaveBeenCalledWith({
      partner_id: 9,
      partner_type: "lab",
      source: "search_card",
    });
  });
});
