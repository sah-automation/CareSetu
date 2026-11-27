// PHASE-6 T05a (#966): directory result card suite - the redesigned two-panel
// Zocdoc-style card (`.dir-card-zoc`). Pins the left-panel anatomy (avatar,
// ribbon, name, credentials, practice, specialty + experience, rating, facts,
// verified tick, distance, tags, location, fee) and the right-panel
// AvailabilityDateGrid, plus the T6 `partner.selected` emission and the
// verified-truthfulness gate (tick gone = card gone).

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { DirectoryEntry } from "@/lib/directory/search";
import { DirectoryCard } from "./DirectoryCard";

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
    area: "Medininagar Rd",
    distance_km: 1.2,
    verified: true,
    consultation_fee: 30000,
    clinic_name: "City General Clinic",
    experience_years: 12,
    languages: ["Hindi", "English"],
    address_line: "Medininagar Road",
    city: "Daltonganj",
    photo_ref: null,
    ...overrides,
  };
}

afterEach(() => {
  emitPartnerSelected.mockClear();
  cleanup();
});

describe("DirectoryCard layout", () => {
  it("renders the two-panel card: left anatomy + right date grid", () => {
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
    // Left panel anatomy.
    expect(screen.getByTestId("directory-card-p1")).toBeInTheDocument();
    expect(screen.getByTestId("directory-card-p1t")).toBeInTheDocument();
    expect(screen.getByTestId("directory-card-p1b")).toBeInTheDocument();
    expect(screen.getByText("Dr. A. Kumar")).toBeInTheDocument();
    expect(screen.getByText("City General Clinic")).toBeInTheDocument();
    expect(
      screen.getByText(
        /General Physician \u00b7 Doctors \u00b7 12 years experience/,
      ),
    ).toBeInTheDocument();
    expect(screen.getByTestId("directory-card-verified")).toBeInTheDocument();
    expect(screen.getByText("1.2 km")).toBeInTheDocument();
    expect(
      screen.getByText("Medininagar Road, Daltonganj"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("directory-card-fee")).toHaveTextContent(/₹300/);
    // Right panel date grid.
    expect(screen.getByTestId("directory-card-p2")).toBeInTheDocument();
    expect(screen.getByTestId("availability-date-grid")).toBeInTheDocument();
    expect(screen.getByTestId("availability-grid")).toBeInTheDocument();
  });

  it("renders avatar initials when no photo", () => {
    render(
      <DirectoryCard
        entry={entry({ photo_ref: null })}
        typeLabel="Doctors"
        specialtyLabel="General Physician"
        verifiedLabel="Verified"
        distanceLabel="1.2 km"
      />,
    );
    expect(screen.getByText("AK")).toBeInTheDocument();
  });

  it("renders practice as area for labs/chemists (not clinic_name)", () => {
    render(
      <DirectoryCard
        entry={entry({
          partner_type: "lab",
          clinic_name: null,
          specialty: null,
        })}
        typeLabel="Labs"
        specialtyLabel={null}
        verifiedLabel="Verified"
        distanceLabel="0.8 km"
      />,
    );
    expect(screen.getByText(/Labs/)).toBeInTheDocument();
    expect(screen.queryByText(/specialty/i)).not.toBeInTheDocument();
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

    expect(emitPartnerSelected).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId("directory-card"));

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

    expect(emitPartnerSelected).not.toHaveBeenCalled();
  });
});
