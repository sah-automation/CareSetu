// PHASE-2.7 T1 (#499): the reworked patient home shell (PROTO-2.7 binding).
// A returning patient lands on a full-width greeting strip that names the saved
// first name in the current language, with a generic fallback when no name is
// saved, above the responsive feed. The profile completion meter, nudge stack
// and demo scaffolds no longer render on the home.
//
// #500: the slim one-line profile-completeness banner joins the same composed
// seam under the greeting strip - present when name/age/gender are missing and
// not dismissed, absent when basics are complete or the per-device dismissal
// flag is set.

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PatientDashboardPage from "./page";
import { ProfileProvider } from "@/lib/profile/ProfileContext";
import type { StoredPatientProfile } from "@/lib/profile/api";
import { __resetLangForTests, useLang } from "@/lib/i18n/LangContext";
import { STRINGS } from "@/lib/i18n/dictionaries";
import type { DirectoryEntry } from "@/lib/directory/search";

const state = vi.hoisted(() => ({
  getProfile: vi.fn(),
  saveProfile: vi.fn(),
  push: vi.fn(),
  user: { id: 7, phone: "+91 98765 43210", roles: ["patient"] },
}));

// #503: the Recommended rail fetches the active scope's directory data through
// this client - the composed seam feeds raw entries (including an unverified
// row) so the rail's verified-only, distance-sorted projection is asserted.
const searchDirectory = vi.hoisted(() => vi.fn());

vi.mock("@/lib/profile/api", () => ({
  getProfile: state.getProfile,
  saveProfile: state.saveProfile,
}));

vi.mock("@/lib/auth/AuthContext", () => ({
  useAuth: () => ({
    user: state.user,
    selectedRole: null,
    switchRole: vi.fn(),
    logout: vi.fn(),
    isAuthenticated: true,
    isLoading: false,
  }),
}));

vi.mock("@/lib/directory/search", async (importOriginal) => {
  const original =
    await importOriginal<typeof import("@/lib/directory/search")>();
  return { ...original, searchDirectory };
});

// #502: the search card routes through fresh navigation - the router push is
// the seam the scoped-destination assertions check.
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: state.push }),
}));

vi.mock("next/link", () => {
  return {
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
  };
});

const completeProfile: StoredPatientProfile = {
  name: "Asha Devi",
  age: 30,
  gender: "female",
  preferred_language: "en",
  area: "Bishrampur",
  emergency_contact: "+91 98765 43210",
  photo_ref: "me.jpg",
};

function langFlip() {
  // Provider-less suites subscribe to the shared module store directly; this
  // button is the one-mutation-path way to flip locale mid-test.
  const { lang, setLang } = useLang();
  return (
    <button type="button" onClick={() => setLang(lang === "en" ? "hi" : "en")}>
      flip-lang
    </button>
  );
}

function renderHome() {
  return render(
    <ProfileProvider>
      <LangFlipHost />
    </ProfileProvider>,
  );
}

function LangFlipHost() {
  return (
    <>
      {langFlip()}
      <PatientDashboardPage />
    </>
  );
}

beforeEach(() => {
  window.localStorage.clear();
  __resetLangForTests();
  state.getProfile.mockReset();
  state.saveProfile.mockReset();
  state.push.mockReset();
  searchDirectory.mockReset();
  searchDirectory.mockResolvedValue({ fell_back: false, items: [] });
  state.getProfile.mockResolvedValue({ set: false, profile: null });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("patient home shell (#499)", () => {
  it("greets the saved first name in the current language", async () => {
    state.getProfile.mockResolvedValue({ set: true, profile: completeProfile });
    renderHome();

    const greeting = await screen.findByTestId("patient-home-greeting");
    await waitFor(() =>
      expect(greeting).toHaveTextContent(
        STRINGS.en.patientHome.welcome("Asha"),
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: "flip-lang" }));
    await waitFor(() =>
      expect(greeting).toHaveTextContent(
        STRINGS.hi.patientHome.welcome("Asha"),
      ),
    );
  });

  it("falls back to the generic greeting when no name is saved", async () => {
    state.getProfile.mockResolvedValue({ set: false, profile: null });
    renderHome();

    const greeting = await screen.findByTestId("patient-home-greeting");
    await waitFor(() =>
      expect(greeting).toHaveTextContent(STRINGS.en.patientHome.welcomeGuest),
    );
    expect(greeting).not.toHaveTextContent(
      STRINGS.en.patientHome.welcome("Asha"),
    );
  });

  it("no longer composes the meter, nudge stack or demo scaffolds", async () => {
    state.getProfile.mockResolvedValue({ set: true, profile: completeProfile });
    renderHome();

    await screen.findByTestId("patient-home-greeting");
    expect(screen.queryByTestId("pc-meter-label")).not.toBeInTheDocument();
    expect(screen.queryByTestId("pc-nudge-stack")).not.toBeInTheDocument();
    expect(screen.queryByTestId("profile-gate-demo")).not.toBeInTheDocument();
    expect(screen.queryByTestId("consent-demo-card")).not.toBeInTheDocument();
  });

  it("renders the greeting strip above the feed with an empty rail", async () => {
    renderHome();

    const greeting = await screen.findByTestId("patient-home-greeting");
    expect(screen.getByTestId("patient-home-rail")).toBeInTheDocument();
    expect(
      greeting.compareDocumentPosition(screen.getByTestId("patient-home-rail")),
    ).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });
});

describe("profile completeness banner (#500)", () => {
  it("renders when basics are incomplete and not dismissed", async () => {
    state.getProfile.mockResolvedValue({ set: false, profile: null });
    renderHome();

    const banner = await screen.findByTestId("pc-banner");
    expect(banner).toHaveTextContent(STRINGS.en.patientHome.banner);
    expect(banner).toHaveTextContent(STRINGS.en.patientHome.bannerCta);
    expect(
      screen.getByRole("button", {
        name: STRINGS.en.patientHome.bannerDismiss,
      }),
    ).toBeInTheDocument();
    // The slim banner is a separate element from the (removed) nudge stack.
    expect(screen.queryByTestId("pc-nudge-stack")).not.toBeInTheDocument();
  });

  it("renders nothing when basics are complete (testid absent, not hidden)", async () => {
    state.getProfile.mockResolvedValue({ set: true, profile: completeProfile });
    renderHome();

    await screen.findByTestId("patient-home-greeting");
    await waitFor(() =>
      expect(screen.queryByTestId("pc-banner")).not.toBeInTheDocument(),
    );
  });

  it("dismisses per device and stays gone on a later visit", async () => {
    state.getProfile.mockResolvedValue({ set: false, profile: null });
    renderHome();
    await screen.findByTestId("pc-banner");

    fireEvent.click(screen.getByTestId("pc-banner-dismiss"));
    await waitFor(() =>
      expect(screen.queryByTestId("pc-banner")).not.toBeInTheDocument(),
    );
    expect(
      window.localStorage.getItem("caresetu.profileBanner.dismissed"),
    ).toBe("1");

    // A fresh render (later visit) still honors the durable dismissal.
    cleanup();
    renderHome();
    await screen.findByTestId("patient-home-greeting");
    await waitFor(() =>
      expect(screen.queryByTestId("pc-banner")).not.toBeInTheDocument(),
    );
  });

  it("serves the banner copy in hi from the same patientHome surface", async () => {
    state.getProfile.mockResolvedValue({ set: false, profile: null });
    renderHome();
    await screen.findByTestId("pc-banner");

    fireEvent.click(screen.getByRole("button", { name: "flip-lang" }));
    await waitFor(() =>
      expect(screen.getByTestId("pc-banner")).toHaveTextContent(
        STRINGS.hi.patientHome.banner,
      ),
    );
  });
});

describe("location chip + picker (#501)", () => {
  it("shows the persisted profile area on the feed chip", async () => {
    state.getProfile.mockResolvedValue({ set: true, profile: completeProfile });
    renderHome();

    const chip = await screen.findByTestId("location-chip-feed");
    await waitFor(() => expect(chip).toHaveTextContent("Bishrampur"));
  });

  it("falls back to Daltonganj when no area is persisted", async () => {
    state.getProfile.mockResolvedValue({ set: false, profile: null });
    renderHome();

    const chip = await screen.findByTestId("location-chip-feed");
    expect(chip).toHaveTextContent(STRINGS.en.loc.cities.Daltonganj);
  });

  it("opens the sheet listing the single city with the coming-soon note", async () => {
    renderHome();
    fireEvent.click(await screen.findByTestId("location-chip-feed"));

    const sheet = await screen.findByTestId("location-sheet");
    expect(sheet).toHaveTextContent(STRINGS.en.loc.cities.Daltonganj);
    expect(sheet).toHaveTextContent(STRINGS.en.loc.citySub);
    expect(sheet).toHaveTextContent(STRINGS.en.loc.more);
  });

  it("applying Daltonganj persists the area and updates the chip", async () => {
    state.getProfile.mockResolvedValue({ set: true, profile: completeProfile });
    renderHome();
    await waitFor(() =>
      expect(screen.getByTestId("location-chip-feed")).toHaveTextContent(
        "Bishrampur",
      ),
    );

    fireEvent.click(screen.getByTestId("location-chip-feed"));
    fireEvent.click(await screen.findByTestId("location-apply"));

    await waitFor(() =>
      expect(screen.getByTestId("location-chip-feed")).toHaveTextContent(
        STRINGS.en.loc.cities.Daltonganj,
      ),
    );
    // The choice flows through the profile draft persistence, not a side seam.
    const stored = JSON.parse(
      window.localStorage.getItem("caresetu.profile.draft.7") ?? "{}",
    );
    expect(stored.area).toBe("Daltonganj");
  });

  it("serves the chip fallback and sheet copy in hi", async () => {
    state.getProfile.mockResolvedValue({ set: false, profile: null });
    renderHome();
    const chip = await screen.findByTestId("location-chip-feed");
    expect(chip).toHaveTextContent(STRINGS.en.loc.cities.Daltonganj);

    fireEvent.click(screen.getByRole("button", { name: "flip-lang" }));

    await waitFor(() =>
      expect(screen.getByTestId("location-chip-feed")).toHaveTextContent(
        STRINGS.hi.loc.cities.Daltonganj,
      ),
    );
    fireEvent.click(screen.getByTestId("location-chip-feed"));
    const sheet = await screen.findByTestId("location-sheet");
    expect(sheet).toHaveTextContent(STRINGS.hi.loc.cities.Daltonganj);
    expect(sheet).toHaveTextContent(STRINGS.hi.loc.more);
  });

  it("localizes a persisted known area on the chip in hi", async () => {
    state.getProfile.mockResolvedValue({
      set: true,
      profile: { ...completeProfile, area: "Daltonganj" },
    });
    renderHome();
    await waitFor(() =>
      expect(screen.getByTestId("location-chip-feed")).toHaveTextContent(
        STRINGS.en.loc.cities.Daltonganj,
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: "flip-lang" }));

    await waitFor(() =>
      expect(screen.getByTestId("location-chip-feed")).toHaveTextContent(
        STRINGS.hi.loc.cities.Daltonganj,
      ),
    );
  });
});

describe("home search card (#502)", () => {
  const scopePills = () => screen.getAllByTestId("search-scope-pill");

  it("renders the Doctor/Lab/Chemist pills with Doctor active by default", async () => {
    renderHome();
    await screen.findByTestId("home-search-card");

    expect(scopePills()).toHaveLength(3);
    const [doctor, lab, chemist] = scopePills();
    expect(doctor).toHaveTextContent(STRINGS.en.search.doctor);
    expect(lab).toHaveTextContent(STRINGS.en.search.lab);
    expect(chemist).toHaveTextContent(STRINGS.en.search.chemist);
    expect(doctor).toHaveAttribute("data-active", "true");
    expect(doctor).toHaveAttribute("aria-pressed", "true");
    expect(lab).toHaveAttribute("data-active", "false");
    // The default scope carries into the See-all destination.
    expect(screen.getByTestId("search-see-all")).toHaveAttribute(
      "href",
      "/patient/find?type=doctor",
    );
  });

  it("switching scope updates the active pill and the See-all destination", async () => {
    renderHome();
    await screen.findByTestId("home-search-card");

    fireEvent.click(
      screen.getByRole("button", { name: STRINGS.en.search.lab }),
    );
    const [doctor, lab, chemist] = scopePills();
    expect(doctor).toHaveAttribute("data-active", "false");
    expect(lab).toHaveAttribute("data-active", "true");
    expect(lab).toHaveAttribute("aria-pressed", "true");
    expect(chemist).toHaveAttribute("data-active", "false");
    expect(screen.getByTestId("search-see-all")).toHaveAttribute(
      "href",
      "/patient/find?type=lab",
    );

    fireEvent.click(
      screen.getByRole("button", { name: STRINGS.en.search.chemist }),
    );
    expect(screen.getByTestId("search-see-all")).toHaveAttribute(
      "href",
      "/patient/find?type=chemist",
    );
  });

  it("Enter on a query routes to Find Care scoped to the active pill", async () => {
    renderHome();
    await screen.findByTestId("home-search-card");

    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "  heart care  " },
    });
    fireEvent.submit(screen.getByRole("search"));

    // The query is trimmed and carried as ?q; the scope as ?type.
    expect(state.push).toHaveBeenCalledWith(
      "/patient/find?type=doctor&q=heart+care",
    );
  });

  it("the Search button routes with the active scope", async () => {
    renderHome();
    await screen.findByTestId("home-search-card");

    fireEvent.click(
      screen.getByRole("button", { name: STRINGS.en.search.lab }),
    );
    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "thyroid profile" },
    });
    fireEvent.click(screen.getByTestId("search-go"));

    expect(state.push).toHaveBeenCalledWith(
      "/patient/find?type=lab&q=thyroid+profile",
    );
  });

  it("searching with no query still routes to scoped Find Care", async () => {
    renderHome();
    await screen.findByTestId("home-search-card");

    fireEvent.submit(screen.getByRole("search"));

    expect(state.push).toHaveBeenCalledWith("/patient/find?type=doctor");
  });

  it("keeps 48px touch targets and full width on a phone", async () => {
    renderHome();
    await screen.findByTestId("home-search-card");

    const input = screen.getByRole("searchbox");
    const button = screen.getByTestId("search-go");
    // The input and Search button meet the 48px phone touch target (ticket);
    // every scope pill keeps the blueprint >=44px floor.
    expect(input.className).toContain("min-h-12");
    expect(input.className).toContain("w-full");
    expect(button.className).toContain("min-h-12");
    for (const pill of scopePills()) {
      expect(pill.className).toContain("min-h-11");
    }
  });

  it("a long query never widens the page at 320px (min-w-0 guards)", async () => {
    renderHome();
    await screen.findByTestId("home-search-card");

    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "x".repeat(200) },
    });

    // The input and its flex wrapper both carry the min-width:0 guard (the
    // prototype `.search-card .search-bar` regression rule), so an intrinsic
    // query width can never push past the flex basis and overflow the page.
    const input = screen.getByRole("searchbox");
    expect(input).toHaveValue("x".repeat(200));
    expect(input.className).toContain("min-w-0");
    expect(input.parentElement).not.toBeNull();
    expect(input.parentElement!.className).toContain("min-w-0");
    expect(input.parentElement!.className).toContain("flex-1");
    // Proof from the 320px floor rather than the test viewport.
    document.documentElement.style.width = "320px";
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(320);
    document.documentElement.style.width = "";
  });

  it("serves the search card copy in hi from the same search surface", async () => {
    renderHome();
    await screen.findByTestId("home-search-card");

    fireEvent.click(screen.getByRole("button", { name: "flip-lang" }));

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: STRINGS.hi.search.doctor }),
      ).toHaveAttribute("data-active", "true"),
    );
    expect(
      screen.getByRole("button", { name: STRINGS.hi.search.lab }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: STRINGS.hi.search.chemist }),
    ).toBeInTheDocument();
    expect(screen.getByRole("searchbox")).toHaveAttribute(
      "placeholder",
      STRINGS.hi.search.placeholder,
    );
    expect(screen.getByTestId("search-go")).toHaveTextContent(
      STRINGS.hi.search.go,
    );
    expect(screen.getByTestId("search-see-all")).toHaveTextContent(
      STRINGS.hi.search.seeAll,
    );
    expect(screen.getByTestId("search-see-all")).toHaveAttribute(
      "href",
      "/patient/find?type=doctor",
    );
  });
});

describe("recommended near-you rail (#503)", () => {
  function doctor(
    id: number,
    name: string,
    distanceKm: number,
    overrides: Partial<DirectoryEntry> = {},
  ): DirectoryEntry {
    return {
      partner_id: id,
      practice_name: name,
      partner_type: "doctor",
      specialty: "General Physician",
      area: "Medininagar Rd",
      distance_km: distanceKm,
      verified: true,
      consultation_fee: null,
      ...overrides,
    };
  }

  function lab(id: number, name: string, distanceKm: number): DirectoryEntry {
    return {
      partner_id: id,
      practice_name: name,
      partner_type: "lab",
      specialty: null,
      area: null,
      distance_km: distanceKm,
      verified: true,
      consultation_fee: null,
    };
  }

  it("fetches the active scope and shows only verified providers, distance-sorted", async () => {
    searchDirectory.mockResolvedValue({
      fell_back: false,
      items: [
        doctor(2, "Dr. Far Clinic", 3.2),
        doctor(3, "Dr. Hidden Row", 0, { verified: false }),
        doctor(1, "Dr. Near Clinic", 1.1),
      ],
    });
    renderHome();

    const cards = await screen.findAllByTestId("rec-card");
    expect(searchDirectory).toHaveBeenCalledWith({ partnerType: "doctor" });
    // The unverified row never renders a card ("tick gone = card gone").
    expect(cards).toHaveLength(2);
    // Distance-sorted ascending, near before far.
    expect(cards[0]).toHaveTextContent("Dr. Near Clinic");
    expect(cards[0]).toHaveTextContent("1.1 km");
    expect(cards[1]).toHaveTextContent("Dr. Far Clinic");
    expect(cards[1]).toHaveTextContent("3.2 km");
    expect(screen.queryByText("Dr. Hidden Row")).not.toBeInTheDocument();
    expect(screen.getAllByText(STRINGS.en.directory.verified)).toHaveLength(2);
    // Metadata joins the shared card language (specialty · type · area).
    expect(cards[1]).toHaveTextContent(
      "General Physician · Doctors · Medininagar Rd",
    );
    // Cards keep the destination scoped to each provider profile.
    expect(cards[0]).toHaveAttribute("href", "/providers/1");
  });

  it("switching scope swaps the rail panel and the scoped destinations together", async () => {
    searchDirectory.mockImplementation(async ({ partnerType }) => ({
      fell_back: false,
      items:
        partnerType === "lab"
          ? [lab(11, "Sahyog Path Lab", 0.8)]
          : [doctor(1, "Dr. Near Clinic", 1.1)],
    }));
    renderHome();
    expect(await screen.findByText("Dr. Near Clinic")).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: STRINGS.en.search.lab }),
    );

    // Rail panel swapped for the active scope...
    await waitFor(() =>
      expect(screen.getByText("Sahyog Path Lab")).toBeInTheDocument(),
    );
    expect(screen.queryByText("Dr. Near Clinic")).not.toBeInTheDocument();
    expect(searchDirectory).toHaveBeenLastCalledWith({ partnerType: "lab" });
    expect(
      screen.getByRole("link", { name: /Sahyog Path Lab/ }),
    ).toHaveAttribute("href", "/providers/11");
    // ...and the Search / See-all destination from #502 swapped on the same state.
    expect(screen.getByTestId("search-see-all")).toHaveAttribute(
      "href",
      "/patient/find?type=lab",
    );
  });

  it("renders a horizontal snap-scroll row on a phone and a 3-up grid at >=720px", async () => {
    searchDirectory.mockResolvedValue({
      fell_back: false,
      items: [
        doctor(1, "Dr. A", 1.1),
        doctor(2, "Dr. B", 2.2),
        doctor(3, "Dr. C", 3.3),
      ],
    });
    renderHome();

    const scroll = await screen.findByTestId("rec-scroll");
    expect(scroll.className).toContain("snap-x");
    expect(scroll.className).toContain("snap-mandatory");
    expect(scroll.className).toContain("overflow-x-auto");
    expect(scroll.className).toContain("min-[720px]:grid");
    expect(scroll.className).toContain("min-[720px]:grid-cols-3");
    for (const card of screen.getAllByTestId("rec-card")) {
      expect(card.className).toContain("snap-start");
    }
  });

  it("renders a friendly empty state when no verified supply exists", async () => {
    searchDirectory.mockResolvedValue({ fell_back: false, items: [] });
    renderHome();

    const empty = await screen.findByTestId("empty-state");
    expect(screen.getByTestId("empty-state-title")).toHaveTextContent(
      STRINGS.en.rec.emptyTitle,
    );
    expect(empty).toHaveTextContent(STRINGS.en.rec.emptyBody);
    expect(screen.queryByTestId("rec-scroll")).not.toBeInTheDocument();
  });

  it("degrades a failed fetch to the honest empty state", async () => {
    searchDirectory.mockRejectedValue(new Error("network down"));
    renderHome();

    expect(await screen.findByTestId("empty-state")).toBeInTheDocument();
    expect(screen.queryByTestId("rec-scroll")).not.toBeInTheDocument();
  });

  it("serves the rail copy in hi from the same rec surface", async () => {
    searchDirectory.mockResolvedValue({
      fell_back: false,
      items: [doctor(1, "Dr. Near Clinic", 1.1)],
    });
    renderHome();
    await screen.findByTestId("rec-card");

    fireEvent.click(screen.getByRole("button", { name: "flip-lang" }));

    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: STRINGS.hi.rec.title }),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText(STRINGS.hi.directory.verified)).toBeInTheDocument();
    expect(screen.getByTestId("rec-card")).toHaveTextContent(
      STRINGS.hi.directory.distanceKm("1.1"),
    );
  });
});

describe("services grid (#504)", () => {
  const tiles = () => screen.getAllByTestId("svc-tile");
  const tile = (key: string) =>
    tiles().find((el) => el.getAttribute("data-svc-key") === key)!;

  it("renders the four tiles in the fixed binding order with the right labels", async () => {
    renderHome();
    await screen.findByTestId("services-grid");

    const order = tiles().map((el) => el.getAttribute("data-svc-key"));
    expect(order).toEqual(["doctor", "lab", "chemist", "start"]);

    expect(tile("doctor")).toHaveTextContent(STRINGS.en.services.doctor);
    expect(tile("lab")).toHaveTextContent(STRINGS.en.services.lab);
    expect(tile("chemist")).toHaveTextContent(STRINGS.en.services.chemist);
    expect(tile("start")).toHaveTextContent(STRINGS.en.services.start);
    expect(tile("chemist")).toHaveTextContent(STRINGS.en.services.soon);
  });

  it("points consult and lab at the scoped Find Care routes and start at intake", async () => {
    renderHome();
    await screen.findByTestId("services-grid");

    expect(
      screen.getByRole("link", { name: STRINGS.en.services.doctor }),
    ).toHaveAttribute("href", "/patient/find?type=doctor");
    expect(
      screen.getByRole("link", { name: STRINGS.en.services.lab }),
    ).toHaveAttribute("href", "/patient/find?type=lab");
    expect(
      screen.getByRole("link", { name: STRINGS.en.services.start }),
    ).toHaveAttribute("href", "/patient/intake");
  });

  it("renders Order medicine marked Soon as a non-navigating tile", async () => {
    renderHome();
    await screen.findByTestId("services-grid");

    const chemist = tile("chemist");
    expect(chemist).toHaveAttribute("data-svc-soon", "true");
    expect(chemist).toHaveAttribute("aria-disabled", "true");
    // Not a link and never navigates: the tile is a dimmed span with no href.
    expect(
      screen.queryByRole("link", { name: STRINGS.en.services.chemist }),
    ).not.toBeInTheDocument();
  });

  it("renders Start visit as the accent tile", async () => {
    renderHome();
    await screen.findByTestId("services-grid");

    const start = tile("start");
    expect(start.className).toContain("bg-accent");
    expect(start.className).toContain("border-accent");
    // Accent is visually distinct from the plain surface tiles.
    expect(tile("doctor").className).not.toContain("bg-accent");
  });

  it("matches the binding's 2-up phone and 4-across >=720px grid", async () => {
    renderHome();
    await screen.findByTestId("services-grid");

    const grid = screen.getByTestId("services-grid-tiles");
    expect(grid.className).toContain("grid-cols-2");
    expect(grid.className).toContain("min-[720px]:grid-cols-4");
  });

  it("serves the grid copy in hi from the same services surface", async () => {
    renderHome();
    await screen.findByTestId("services-grid");

    fireEvent.click(screen.getByRole("button", { name: "flip-lang" }));

    await waitFor(() =>
      expect(tile("doctor")).toHaveTextContent(STRINGS.hi.services.doctor),
    );
    expect(tile("lab")).toHaveTextContent(STRINGS.hi.services.lab);
    expect(tile("chemist")).toHaveTextContent(STRINGS.hi.services.chemist);
    expect(tile("start")).toHaveTextContent(STRINGS.hi.services.start);
    expect(tile("chemist")).toHaveTextContent(STRINGS.hi.services.soon);
  });
});
