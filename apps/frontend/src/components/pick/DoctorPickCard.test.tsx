// PHASE-8.1 T11 (#449): the pick-a-doctor card suite. Shares DirectoryCard's
// verified-truthfulness guarantee (ADR-0011: an unverified row renders no
// card), renders the fee or the fee-not-set marker without ever blocking the
// pick (US-10), shows the credentials-verified summary, deep-links to the
// verified profile, and fires the Book CTA into the consent sheet.

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { DirectoryEntry } from "@/lib/directory/search";
import { DoctorPickCard, formatFeePaise } from "./DoctorPickCard";

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

describe("formatFeePaise", () => {
  it("formats integer paise as a whole-rupee INR amount", () => {
    expect(formatFeePaise(50000)).toBe("\u20B9500");
    expect(formatFeePaise(300)).toBe("\u20B93");
  });
});

describe("DoctorPickCard", () => {
  it("renders verified tick, practice, meta, distance and the set fee", () => {
    render(<DoctorPickCard entry={entry()} {...labels} onBook={vi.fn()} />);

    expect(screen.getByTestId("pick-doctor-card")).toBeInTheDocument();
    expect(screen.getByTestId("pick-verified")).toHaveTextContent("Verified");
    expect(
      screen.getByText("General Physician · Doctors · Medininagar Rd"),
    ).toBeInTheDocument();
    expect(screen.getByText("1.2 km")).toBeInTheDocument();
    expect(screen.getByTestId("pick-fee")).toHaveTextContent("\u20B9500");
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
