// PHASE-2.6 T09 (#200): suite for homepage section 5 - featured doctor
// cards. Covers both acceptance branches against a mocked fetch of the
// marked integration point (lib/directory/featured, gap G2): live verified
// cards when activated supply exists, and the honest "Directory launching
// soon" empty state when it does not - plus the loading and failure paths.

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FeaturedDoctors } from "./FeaturedDoctors";
import type { FeaturedDoctor } from "@/lib/directory/featured";
import { __resetLangForTests } from "@/lib/i18n/LangContext";

vi.mock("@/lib/directory/featured", () => ({
  fetchFeaturedDoctors: vi.fn(),
}));

// Import after the mock declaration so the suite binds the mocked function.
import { fetchFeaturedDoctors } from "@/lib/directory/featured";

const mockFetchFeatured = vi.mocked(fetchFeaturedDoctors);

const CARDS: FeaturedDoctor[] = [
  {
    id: 1,
    name: "Dr. A. Kumar",
    specialty: "General Physician",
    area: "Medininagar Rd",
    distance_km: 1.2,
    consultation_fee: 30000,
  },
  {
    id: 2,
    name: "Dr. S. Devi",
    specialty: "Gynecologist",
    area: null,
    distance_km: 3.4,
    consultation_fee: null,
  },
];

beforeEach(() => {
  mockFetchFeatured.mockReset();
  localStorage.clear();
  __resetLangForTests();
  document.documentElement.lang = "en";
});

afterEach(() => {
  cleanup();
});

describe("FeaturedDoctors (gap G2)", () => {
  it("shows skeletons while the integration point resolves", () => {
    mockFetchFeatured.mockReturnValue(new Promise(() => {}));
    render(<FeaturedDoctors />);

    expect(screen.getByTestId("featured-loading")).toBeInTheDocument();
    expect(screen.queryByTestId("empty-state")).not.toBeInTheDocument();
    expect(screen.queryByTestId("featured-cards")).not.toBeInTheDocument();
  });

  it("renders live verified cards when activated supply exists", async () => {
    mockFetchFeatured.mockResolvedValue(CARDS);
    render(<FeaturedDoctors />);

    await waitFor(() =>
      expect(screen.getByTestId("featured-cards")).toBeInTheDocument(),
    );
    expect(screen.getByText("Dr. A. Kumar")).toBeInTheDocument();
    expect(screen.getByText("Dr. S. Devi")).toBeInTheDocument();
    // Only activated providers are ever returned, so every card shows the
    // truthful verified indicator (FEAT-004 Rule 1 / FEAT-005). Meta joins
    // non-null parts only - the dropped `consultType` never renders, and a
    // card without an area shows just its specialty.
    expect(screen.getAllByText("Verified")).toHaveLength(2);
    // #961 card template: specialty sits under the name, area renders on its
    // own line when present, distance comes from the payload, and the fee cell
    // shows paise->rupees only when the payload carried one.
    expect(screen.getByText("General Physician")).toBeInTheDocument();
    expect(screen.getByText("Medininagar Rd")).toBeInTheDocument();
    expect(screen.getByText("1.2 km")).toBeInTheDocument();
    expect(screen.getByText("3.4 km")).toBeInTheDocument();
    expect(screen.getByText("Gynecologist")).toBeInTheDocument();
    expect(screen.getByText(/₹300/)).toBeInTheDocument();
    expect(screen.getByText("consult")).toBeInTheDocument();
    // No fake cards means no empty state either.
    expect(screen.queryByTestId("empty-state")).not.toBeInTheDocument();
    // Cards target provider profiles; view-all pre-seeds the directory.
    expect(
      screen.getByRole("link", { name: /Dr\. A\. Kumar/ }),
    ).toHaveAttribute("href", "/providers/1");
    expect(
      screen.getByRole("link", { name: "View all doctors" }),
    ).toHaveAttribute("href", "/directory?type=doctor");
  });

  it("renders the honest launching-soon empty state when supply is empty", async () => {
    mockFetchFeatured.mockResolvedValue([]);
    render(<FeaturedDoctors />);

    expect(await screen.findByTestId("empty-state")).toBeInTheDocument();
    expect(
      screen.getByText("Directory launching soon in Daltonganj"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Get started as a patient" }),
    ).toHaveAttribute("href", "/login");
    expect(screen.queryByTestId("featured-cards")).not.toBeInTheDocument();
  });

  it("degrades a failed fetch to the honest empty state", async () => {
    mockFetchFeatured.mockRejectedValue(new Error("network down"));
    render(<FeaturedDoctors />);

    expect(await screen.findByTestId("empty-state")).toBeInTheDocument();
    expect(screen.queryByTestId("featured-cards")).not.toBeInTheDocument();
  });
});
