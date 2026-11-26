// PHASE-8.1 T11 (#966): the pick-a-doctor card suite, restyled to the
// Phase-6 card visual language. Pins the left-panel anatomy (avatar, name,
// credentials, practice, specialty + experience, rating, facts, verified tick,
// distance) plus the pick-specific fee/verified footer and Book CTA, and the
// verified-truthfulness gate (tick gone = card gone).

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { DirectoryEntry } from "@/lib/directory/search";
import { DoctorPickCard } from "./DoctorPickCard";

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children: React.ReactNode;
  }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

function entry(overrides: Partial<DirectoryEntry> = {}): DirectoryEntry {
  return {
    partner_id: 1,
    practice_name: "Dr. A. Kumar",
    partner_type: "doctor",
    specialty: "General Physician",
    area: "Medininagar Rd",
    distance_km: 1.2,
    verified: true,
    consultation_fee: 50000,
    clinic_name: "City General Clinic",
    experience_years: 12,
    languages: ["Hindi", "English"],
    address_line: "Medininagar Road",
    city: "Daltonganj",
    photo_ref: null,
    ...overrides,
  };
}

const labels = {
  typeLabel: "Doctors",
  specialtyLabel: "General Physician",
  verifiedLabel: "Verified",
  distanceLabel: "1.2 km",
  feeLabel: "Consultation fee",
  feeNotSetLabel: "Fee not set",
  credentialsVerifiedLabel: "Credentials verified",
  bookCtaLabel: "Book with this doctor",
  viewProfileLabel: "View verified profile",
};

afterEach(() => {
  cleanup();
});

describe("DoctorPickCard", () => {
  it("renders the left-panel anatomy: avatar, name, credentials, practice, specialty + experience", () => {
    render(<DoctorPickCard entry={entry()} {...labels} onBook={vi.fn()} />);

    expect(screen.getByTestId("pick-doctor-card")).toBeInTheDocument();
    expect(screen.getByText("AK")).toBeInTheDocument();
    expect(screen.getByText("Dr. A. Kumar")).toBeInTheDocument();
    expect(screen.getByText("City General Clinic")).toBeInTheDocument();
    expect(
      screen.getByText(
        /General Physician \u00b7 Doctors \u00b7 12 years experience/,
      ),
    ).toBeInTheDocument();
    expect(screen.getByTestId("pick-verified")).toHaveTextContent("Verified");
    expect(screen.getByText("1.2 km")).toBeInTheDocument();
  });

  it("renders verified tick, distance and the set fee", () => {
    render(<DoctorPickCard entry={entry()} {...labels} onBook={vi.fn()} />);

    expect(screen.getByTestId("pick-fee")).toHaveTextContent("₹500");
    expect(screen.getByTestId("pick-credentials")).toHaveTextContent(
      "Verified",
    );
  });

  it("renders fee-not-set when the doctor has not set a fee, still pickable (US-10)", () => {
    render(
      <DoctorPickCard
        entry={entry({ consultation_fee: null })}
        {...labels}
        onBook={vi.fn()}
      />,
    );

    expect(screen.getByTestId("pick-fee")).toHaveTextContent("Fee not set");
    expect(screen.getByTestId("pick-book")).toBeInTheDocument();
  });

  it("deep-links practice name and profile action to the verified profile", () => {
    render(<DoctorPickCard entry={entry()} {...labels} onBook={vi.fn()} />);

    expect(screen.getByTestId("pick-doctor-name")).toHaveAttribute(
      "href",
      "/providers/1",
    );
    expect(screen.getByTestId("pick-view-profile")).toHaveAttribute(
      "href",
      "/providers/1",
    );
  });

  it("fires the Book CTA with the card's entry", () => {
    const onBook = vi.fn();
    render(<DoctorPickCard entry={entry()} {...labels} onBook={onBook} />);

    fireEvent.click(screen.getByTestId("pick-book"));
    expect(onBook).toHaveBeenCalledTimes(1);
    expect(onBook).toHaveBeenCalledWith(entry());
  });

  it("renders no card for an unverified row (tick gone = card gone)", () => {
    render(
      <DoctorPickCard
        entry={entry({ verified: false })}
        {...labels}
        onBook={vi.fn()}
      />,
    );

    expect(screen.queryByTestId("pick-doctor-card")).not.toBeInTheDocument();
  });
});
