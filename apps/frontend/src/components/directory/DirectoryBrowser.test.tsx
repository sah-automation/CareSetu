// PHASE-6 T05a (#317): directory browse surface suite (blueprint §3.1 row 2,
// PROTO-PHASE-6 as the visual binding). Covers the URL-as-source-of-truth
// filter flow, the truthful verified tick on every card (FEAT-005/ADR-0011),
// the honest wider-area fallback that keeps all other filters (glossary), and
// loading/empty/error states.

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { useSyncExternalStore } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  LangProvider,
  useLang,
  __resetLangForTests,
} from "@/lib/i18n/LangContext";
import type { DirectorySearchView } from "@/lib/directory/search";
import { DirectoryBrowser } from "./DirectoryBrowser";

// The mocked router.push/replace commits to the same reactive store the mocked
// useSearchParams reads, so chip toggles and submits actually re-render the
// browser and re-key its fetch effect (single committed source of truth).
const navigation = vi.hoisted(() => {
  const state: { params: URLSearchParams } = { params: new URLSearchParams() };
  const listeners = new Set<() => void>();
  return {
    state,
    getParams: () => state.params,
    setParams(next: URLSearchParams) {
      state.params = next;
      for (const listener of listeners) listener();
    },
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
  };
});
const mockReplace = vi.fn((to: string) => {
  const [, qs] = to.split("?");
  navigation.setParams(new URLSearchParams(qs ?? ""));
});
const { searchDirectory } = vi.hoisted(() => ({ searchDirectory: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace }),
  useSearchParams: () =>
    useSyncExternalStore(
      navigation.subscribe,
      navigation.getParams,
      navigation.getParams,
    ),
}));

vi.mock("@/lib/directory/search", async (importOriginal) => {
  const original =
    await importOriginal<typeof import("@/lib/directory/search")>();
  return { ...original, searchDirectory };
});

function view(
  items: DirectorySearchView["items"],
  fell_back = false,
): DirectorySearchView {
  return { items, fell_back };
}

function doctor(
  id: number,
  name: string,
  overrides: Partial<DirectorySearchView["items"][number]> = {},
): DirectorySearchView["items"][number] {
  return {
    partner_id: id,
    practice_name: name,
    partner_type: "doctor",
    specialty: "General Physician",
    area: null,
    distance_km: id,
    verified: true,
    ...overrides,
  };
}

function LangSwitcher() {
  const { lang, setLang } = useLang();
  return (
    <button type="button" onClick={() => setLang(lang === "en" ? "hi" : "en")}>
      {lang === "en" ? "\u0939\u093F\u0902" : "EN"}
    </button>
  );
}

beforeEach(() => {
  navigation.setParams(new URLSearchParams());
  mockReplace.mockClear();
  searchDirectory.mockReset();
  __resetLangForTests();
  document.documentElement.lang = "en";
});

afterEach(() => {
  cleanup();
});

describe("DirectoryBrowser loading the directory", () => {
  it("shows skeletons while the first search is in flight", () => {
    searchDirectory.mockReturnValue(new Promise(() => {}));

    render(<DirectoryBrowser />);

    expect(screen.getByTestId("directory-loading")).toBeInTheDocument();
    expect(screen.queryByTestId("directory-cards")).not.toBeInTheDocument();
    expect(screen.queryByTestId("directory-error")).not.toBeInTheDocument();
  });

  it("renders only verified cards - every card carries the truthful tick", async () => {
    searchDirectory.mockResolvedValueOnce(
      view([
        doctor(1, "Dr. A. Kumar"),
        {
          partner_id: 2,
          practice_name: "Sahyog Path Lab",
          partner_type: "lab",
          specialty: null,
          area: null,
          distance_km: 0.8,
          verified: true,
        },
      ]),
    );

    render(<DirectoryBrowser />);

    await screen.findByTestId("directory-cards");
    expect(screen.getAllByTestId("directory-card")).toHaveLength(2);
    // One tick per card, each backed by the shared derivation.
    expect(screen.getAllByText("Verified")).toHaveLength(2);
    expect(screen.getByText("Dr. A. Kumar")).toBeInTheDocument();
    // Localised one-decimal distances.
    expect(screen.getByText("1.0 km")).toBeInTheDocument();
    expect(screen.getByText("0.8 km")).toBeInTheDocument();
    // Cards deep-link to the provider profile surface (T06).
    expect(screen.getByText("Dr. A. Kumar").closest("a")).toHaveAttribute(
      "href",
      "/providers/1",
    );
    expect(screen.getByText("Sahyog Path Lab").closest("a")).toHaveAttribute(
      "href",
      "/providers/2",
    );
    // Result count announced; no outside-area label without a fallback.
    expect(screen.getByText("2 providers found")).toBeInTheDocument();
    expect(screen.queryByTestId("outside-area")).not.toBeInTheDocument();
  });

  it("renders area in the card meta when the search response carries it", async () => {
    searchDirectory.mockResolvedValueOnce(
      view([doctor(1, "Dr. A. Kumar", { area: "Medininagar Rd" })]),
    );

    render(<DirectoryBrowser />);

    await screen.findByTestId("directory-cards");
    expect(
      screen.getByText(
        /General Physician \u00b7 Doctors \u00b7 Medininagar Rd/,
      ),
    ).toBeInTheDocument();
  });

  it("drops a false-tick row entirely - card and tick disappear together", async () => {
    searchDirectory.mockResolvedValueOnce(
      view([
        doctor(1, "Dr. Ghost", { verified: false }),
        doctor(2, "Dr. Real"),
      ]),
    );

    render(<DirectoryBrowser />);

    await screen.findByTestId("directory-cards");
    expect(screen.getByText("Dr. Real")).toBeInTheDocument();
    expect(screen.queryByText("Dr. Ghost")).not.toBeInTheDocument();
    expect(screen.getAllByTestId("directory-card")).toHaveLength(1);
    expect(screen.getAllByText("Verified")).toHaveLength(1);
  });
});

describe("DirectoryBrowser filters as URL source of truth", () => {
  it("sends the committed filters to the search and mirrors them in chips", async () => {
    navigation.setParams(
      new URLSearchParams("type=doctor&specialty=General%20Physician&q=Kumar"),
    );
    searchDirectory.mockResolvedValueOnce(view([doctor(1, "Dr. A. Kumar")]));

    render(<DirectoryBrowser />);

    await screen.findByTestId("directory-cards");
    expect(searchDirectory).toHaveBeenCalledWith({
      q: "Kumar",
      partnerType: "doctor",
      specialty: "General Physician",
    });
    const [all, doctors, labs, chemists] = screen.getAllByTestId("type-chip");
    expect(all).toHaveAttribute("data-active", "false");
    expect(doctors).toHaveAttribute("data-active", "true");
    expect(labs).toHaveAttribute("data-active", "false");
    expect(chemists).toHaveAttribute("data-active", "false");
    // The search input preserves the committed query.
    expect(screen.getByDisplayValue("Kumar")).toBeInTheDocument();
  });

  it("replaces the URL and refetches when a type chip is toggled", async () => {
    searchDirectory.mockResolvedValue(view([doctor(1, "Dr. A. Kumar")]));

    render(<DirectoryBrowser />);
    await screen.findByTestId("directory-cards");

    fireEvent.click(screen.getByRole("button", { name: "Labs" }));

    expect(mockReplace).toHaveBeenCalledWith("/directory?type=lab");
    expect(searchDirectory).toHaveBeenLastCalledWith({
      q: "",
      partnerType: "lab",
      specialty: null,
    });
  });

  it("selects a specialty chip as an implied doctor search", async () => {
    searchDirectory.mockResolvedValue(view([doctor(1, "Dr. Smile")]));

    render(<DirectoryBrowser />);
    await screen.findByTestId("directory-cards");

    fireEvent.click(screen.getByRole("button", { name: "Dentist" }));

    expect(mockReplace).toHaveBeenCalledWith(
      "/directory?type=doctor&specialty=Dentist",
    );
    expect(searchDirectory).toHaveBeenLastCalledWith({
      q: "",
      partnerType: "doctor",
      specialty: "Dentist",
    });
  });

  it("does not fire a request for an in-progress but unsubmitted query", async () => {
    searchDirectory.mockResolvedValue(view([doctor(1, "Dr. A. Kumar")]));

    render(<DirectoryBrowser />);
    await screen.findByTestId("directory-cards");
    const calls = searchDirectory.mock.calls.length;

    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "uncommitted" },
    });

    expect(screen.getByDisplayValue("uncommitted")).toBeInTheDocument();
    expect(searchDirectory.mock.calls).toHaveLength(calls);
    expect(mockReplace).not.toHaveBeenCalled();
  });

  it("submits the query to the URL and refetches", async () => {
    searchDirectory.mockResolvedValue(view([doctor(1, "Dr. A. Kumar")]));

    render(<DirectoryBrowser />);
    await screen.findByTestId("directory-cards");

    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "  heart  " },
    });
    fireEvent.submit(screen.getByRole("search"));

    expect(mockReplace).toHaveBeenCalledWith("/directory?q=heart");
    expect(searchDirectory).toHaveBeenLastCalledWith({
      q: "heart",
      partnerType: null,
      specialty: null,
    });
  });

  it("hides specialty chips while a lab or chemist filter is active", () => {
    navigation.setParams(new URLSearchParams("type=chemist"));
    searchDirectory.mockResolvedValue(view([]));

    render(<DirectoryBrowser />);

    expect(screen.queryAllByTestId("specialty-chip")).toHaveLength(0);
    // Heading types the preset.
    expect(screen.getByTestId("directory-heading")).toHaveTextContent(
      "Find chemists near you",
    );
  });
});

describe("DirectoryBrowser type-preset variants (T05b)", () => {
  it("pins the partner type from the preset and searches with it", async () => {
    searchDirectory.mockResolvedValueOnce(view([doctor(1, "Dr. A. Kumar")]));

    render(<DirectoryBrowser presetType="doctor" />);

    await screen.findByTestId("directory-cards");
    expect(searchDirectory).toHaveBeenCalledWith({
      q: "",
      partnerType: "doctor",
      specialty: null,
    });
    // The route is the type filter: heading types the preset and the type
    // chip row is suppressed.
    expect(screen.getByTestId("directory-heading")).toHaveTextContent(
      "Find doctors near you",
    );
    expect(screen.queryAllByTestId("type-chip")).toHaveLength(0);
    // Doctor presets keep the specialty chips for narrowing.
    expect(screen.getAllByTestId("specialty-chip").length).toBeGreaterThan(0);
  });

  it("keeps search and specialty commits on the variant route", async () => {
    searchDirectory.mockResolvedValue(view([doctor(1, "Dr. Smile")]));

    render(<DirectoryBrowser presetType="doctor" />);
    await screen.findByTestId("directory-cards");

    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "  heart  " },
    });
    fireEvent.submit(screen.getByRole("search"));

    expect(mockReplace).toHaveBeenCalledWith("/doctors?q=heart");
    expect(searchDirectory).toHaveBeenLastCalledWith({
      q: "heart",
      partnerType: "doctor",
      specialty: null,
    });

    fireEvent.click(screen.getByRole("button", { name: "Dentist" }));

    // The specialty commit preserves the already-committed query - the URL
    // stays the single source of truth for every filter.
    expect(mockReplace).toHaveBeenCalledWith(
      "/doctors?q=heart&specialty=Dentist",
    );
    expect(searchDirectory).toHaveBeenLastCalledWith({
      q: "heart",
      partnerType: "doctor",
      specialty: "Dentist",
    });
  });

  it("suppresses specialty chips on a non-doctor preset", () => {
    searchDirectory.mockResolvedValue(view([]));

    render(<DirectoryBrowser presetType="chemist" />);

    expect(screen.getByTestId("directory-heading")).toHaveTextContent(
      "Find chemists near you",
    );
    expect(screen.queryAllByTestId("type-chip")).toHaveLength(0);
    expect(screen.queryAllByTestId("specialty-chip")).toHaveLength(0);
  });

  it("ignores a URL type param while a preset pins the type", async () => {
    navigation.setParams(new URLSearchParams("type=lab"));
    searchDirectory.mockResolvedValueOnce(view([]));

    render(<DirectoryBrowser presetType="doctor" />);

    await waitFor(() =>
      expect(searchDirectory).toHaveBeenCalledWith({
        q: "",
        partnerType: "doctor",
        specialty: null,
      }),
    );
    expect(screen.queryAllByTestId("type-chip")).toHaveLength(0);
  });
});

describe("DirectoryBrowser empty, error and fallback states", () => {
  it("shows the no-results empty state and clears the search", async () => {
    navigation.setParams(new URLSearchParams("q=zzz"));
    searchDirectory.mockResolvedValue(view([]));

    render(<DirectoryBrowser />);

    expect(screen.getByDisplayValue("zzz")).toBeInTheDocument();
    expect(
      await screen.findByText("No providers found for this search"),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Clear search" }));

    expect(mockReplace).toHaveBeenCalledWith("/directory");
  });

  it("labels the wider-area fallback honestly and keeps every other filter", async () => {
    navigation.setParams(
      new URLSearchParams("type=doctor&specialty=Pediatrician&q=child"),
    );
    searchDirectory.mockResolvedValueOnce(
      view(
        [doctor(3, "Dr. Far", { specialty: "Pediatrician", distance_km: 42 })],
        true,
      ),
    );

    render(<DirectoryBrowser />);

    await screen.findByTestId("directory-cards");
    expect(screen.getByTestId("outside-area")).toBeInTheDocument();
    expect(
      screen.getByText("Showing providers outside your area"),
    ).toBeInTheDocument();
    // Every other filter is preserved in the URL-derived UI.
    expect(
      screen
        .getAllByTestId("type-chip")
        .find((c) => c.textContent === "Doctors"),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      screen
        .getAllByTestId("specialty-chip")
        .find((c) => c.textContent === "Pediatrician"),
    ).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByDisplayValue("child")).toBeInTheDocument();
    expect(screen.getByText("42.0 km")).toBeInTheDocument();
  });

  it("shows the error state and retries the search", async () => {
    searchDirectory
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce(view([doctor(1, "Dr. A. Kumar")]));

    render(<DirectoryBrowser />);

    expect(await screen.findByTestId("directory-error")).toBeInTheDocument();
    expect(
      screen.getByText("We could not load the directory"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("group", {
        name: "Filter by provider type and specialty",
      }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByTestId("directory-cards")).toBeInTheDocument();
    expect(screen.getByText("Dr. A. Kumar")).toBeInTheDocument();
  });

  it("re-renders results in Hindi when the app locale flips (REQ-006)", async () => {
    searchDirectory.mockResolvedValueOnce(
      view([
        doctor(1, "Dr. A. Kumar", { partner_type: "chemist", specialty: null }),
      ]),
    );

    render(
      <LangProvider>
        <LangSwitcher />
        <DirectoryBrowser />
      </LangProvider>,
    );

    await screen.findByTestId("directory-cards");
    fireEvent.click(screen.getByRole("button", { name: "\u0939\u093F\u0902" }));

    expect(document.documentElement.lang).toBe("hi");
    expect(
      await screen.findByText(
        "\u0938\u0924\u094D\u092F\u093E\u092A\u093F\u0924",
      ),
    ).toBeInTheDocument(); // verified badge rendered in Hindi
  });
});
