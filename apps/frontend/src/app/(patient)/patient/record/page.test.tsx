// PHASE-3 T7 (#216): the My Record screen suite - real-API timeline render
// (mocked at the facade-client seam per the brief), type filtering including
// the ratified More-dropdown rename, §2.7 Soon placeholders, empty/error
// states, and the bilingual EN/HI contract (परामर्श everywhere).

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import {
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import RecordPage from "./page";
import PatientGroupLayout from "@/app/(patient)/layout";
import { __resetLangForTests, useLang } from "@/lib/i18n/LangContext";
import { STRINGS } from "@/lib/i18n/dictionaries";
import {
  fetchOwnRecord,
  type RecordEntryView,
  type RecordTimeline,
} from "@/lib/record/api";
import { fetchAccessHistory, type AccessHistoryEntry } from "@/lib/audit/api";

vi.mock("@/lib/record/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/record/api")>();
  return { ...mod, fetchOwnRecord: vi.fn() };
});

vi.mock("@/lib/audit/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/audit/api")>();
  return { ...mod, fetchAccessHistory: vi.fn() };
});

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/patient/record",
}));

vi.mock("@/lib/auth/AuthContext", () => ({
  useAuth: () => ({
    user: { id: 7, phone: "+911234567890", roles: ["patient"] },
    selectedRole: "patient",
    switchRole: vi.fn(),
    logout: vi.fn(),
    isAuthenticated: true,
    isLoading: false,
  }),
}));

const mockFetchOwnRecord = vi.mocked(fetchOwnRecord);
const mockFetchAccessHistory = vi.mocked(fetchAccessHistory);

// Radix popper relies on ResizeObserver and opens menus on real pointer
// events, neither of which jsdom implements fully (same stubs as the
// dropdown-menu primitive suite). File isolation keeps them local.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

beforeAll(() => {
  window.ResizeObserver =
    window.ResizeObserver ??
    (ResizeObserverStub as unknown as typeof ResizeObserver);
  if (!window.PointerEvent) {
    class PointerEventStub extends MouseEvent {}
    window.PointerEvent = PointerEventStub as unknown as typeof PointerEvent;
  }
});

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

function entry(overrides: Partial<RecordEntryView>): RecordEntryView {
  return {
    entry_id: 1,
    entry_type: "consultation",
    payload: {},
    occurred_at: "2026-08-19T10:00:00Z",
    created_at: "2026-08-19T10:00:05Z",
    ...overrides,
  };
}

// Deliberately shuffled vs clinical time - the screen must still render
// newest-first (defensive sort in the view model).
const TIMELINE: RecordTimeline = {
  record_id: 5,
  patient_id: 7,
  created_at: "2026-08-01T09:00:00Z",
  entries: [
    entry({
      entry_id: 31,
      entry_type: "metric",
      payload: {},
      occurred_at: "2026-08-18T07:45:00Z",
    }),
    entry({
      entry_id: 30,
      entry_type: "prescription",
      payload: { prescription_id: 12, status: "issued" },
      occurred_at: "2026-08-19T09:00:00Z",
    }),
    entry({
      entry_id: 28,
      entry_type: "consultation",
      payload: {},
      occurred_at: "2026-08-19T10:30:00Z",
    }),
    entry({
      entry_id: 26,
      entry_type: "lab_report",
      payload: { order_id: 1042, filename: "cbc-panel.pdf" },
      occurred_at: "2026-08-21T14:30:00Z",
    }),
    entry({
      entry_id: 24,
      entry_type: "prescription",
      payload: {
        prescription_id: 9,
        fulfillment_order_id: 3,
        status: "delivered",
      },
      occurred_at: "2026-08-22T08:00:00Z",
    }),
  ],
};

function resolveWith(timeline: RecordTimeline | null) {
  mockFetchOwnRecord.mockImplementation(() =>
    timeline === null
      ? Promise.reject(new Error("network down"))
      : Promise.resolve(timeline),
  );
}

function accessEntry(
  overrides: Partial<AccessHistoryEntry>,
): AccessHistoryEntry {
  return {
    actor_id: 3,
    accessed_at: "2026-08-15T11:00:00Z",
    denied: false,
    ...overrides,
  };
}

const ACCESS_HISTORY: AccessHistoryEntry[] = [
  // Deliberately out of order (lab first, doctor second) - the screen must
  // still render newest-first by accessed_at.
  accessEntry({
    actor_id: 4,
    actor_type: "lab",
    scope: "lab_results",
    accessed_at: "2026-08-18T07:45:00Z",
  }),
  accessEntry({
    actor_id: 3,
    actor_type: "doctor",
    scope: "consultations",
    accessed_at: "2026-08-19T09:00:00Z",
  }),
];

function resolveAccessWith(entries: AccessHistoryEntry[] | null) {
  mockFetchAccessHistory.mockImplementation(() =>
    entries === null
      ? Promise.reject(new Error("network down"))
      : Promise.resolve({ entries }),
  );
}

beforeEach(() => {
  __resetLangForTests();
  resolveWith(TIMELINE);
  resolveAccessWith(ACCESS_HISTORY);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

async function waitForTimeline() {
  await screen.findByTestId("record-timeline");
}

function openMoreMenu() {
  const trigger = screen.getByTestId("filter-more-btn");
  fireEvent.pointerDown(trigger);
  fireEvent.click(trigger);
}

describe("RecordPage (inside the patient light shell)", () => {
  it("mounts within the patient AppShell with header and filters", async () => {
    render(
      <PatientGroupLayout>
        <LangFlipHost />
      </PatientGroupLayout>,
    );
    await waitForTimeline();

    expect(screen.getByTestId("app-shell")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "My Health Record" })) //
      .toBeInTheDocument();
    expect(
      screen.getByRole("group", { name: "Filter record entries" }),
    ).toBeInTheDocument();
    // The health-tracking snapshot is now a live card (#511), rendered once
    // per responsive zone (jsdom ignores the lg visibility classes).
    const health = await screen.findAllByTestId("health-snapshot");
    expect(health).toHaveLength(2);
    // The access-history Soon placeholder was replaced by real data (#283).
    expect(screen.queryByTestId("placeholder-access")).not.toBeInTheDocument();
  });

  it("renders API entries newest-first regardless of payload order", async () => {
    render(<RecordPage />);
    await waitForTimeline();

    const ids = [
      ...screen.getByTestId("record-timeline").querySelectorAll("li"),
    ].map((li) => li.getAttribute("data-testid"));
    expect(ids).toEqual([
      "entry-24",
      "entry-26",
      "entry-28",
      "entry-30",
      "entry-31",
    ]);
  });

  it("shows the delivered prescription with its success badge", async () => {
    render(<RecordPage />);
    await waitForTimeline();

    expect(screen.getByTestId("entry-24")).toHaveTextContent("Delivered");
    expect(screen.getByTestId("entry-26")).toHaveTextContent("cbc-panel.pdf");
  });

  it("shows skeletons while loading and recovers when Retry succeeds", async () => {
    resolveWith(null);
    render(<RecordPage />);

    expect(screen.getByTestId("record-loading")).toBeInTheDocument();
    await screen.findByTestId("error-banner");

    // A failed read never renders as a calm empty state.
    expect(screen.queryByTestId("empty-state")).not.toBeInTheDocument();

    // Still failing: the banner returns (wait out the loading swap first so
    // the lookup cannot catch the pre-click banner).
    resolveWith(null);
    fireEvent.click(screen.getByTestId("error-banner-retry"));
    await waitFor(() =>
      expect(screen.queryByTestId("error-banner")).not.toBeInTheDocument(),
    );
    await screen.findByTestId("error-banner");
    expect(mockFetchOwnRecord).toHaveBeenCalledTimes(2);

    // Then the retry succeeds and the timeline replaces the banner.
    resolveWith(TIMELINE);
    fireEvent.click(screen.getByTestId("error-banner-retry"));
    await waitForTimeline();

    expect(screen.queryByTestId("error-banner")).not.toBeInTheDocument();
    // RecordPage fetched 3x; the two health-snapshot cards (one per zone) mount
    // on the first ready render and fetch once each = 5 total. The cards render
    // in the same commit as the timeline, so wait on them before counting - a
    // bare assertion could race the card effects' first fetch.
    await screen.findAllByTestId("health-snapshot");
    await waitFor(() => expect(mockFetchOwnRecord).toHaveBeenCalledTimes(5));
  });

  it("lets Dismiss close the error banner without refetching", async () => {
    resolveWith(null);
    render(<RecordPage />);
    await screen.findByTestId("error-banner");

    fireEvent.click(screen.getByTestId("error-banner-dismiss"));
    expect(screen.queryByTestId("error-banner")).not.toBeInTheDocument();
    expect(mockFetchOwnRecord).toHaveBeenCalledTimes(1);
  });
});

function LangFlipHost() {
  return (
    <>
      {langFlip()}
      <RecordPage />
    </>
  );
}

describe("RecordPage type filters", () => {
  it("filters by a chip's type and reflects aria-pressed", async () => {
    render(<RecordPage />);
    await waitForTimeline();

    fireEvent.click(screen.getByTestId("filter-chip-prescription"));
    const visible = screen
      .getByTestId("record-timeline")
      .querySelectorAll("li");
    expect([...visible].map((li) => li.getAttribute("data-testid"))).toEqual([
      "entry-24",
      "entry-30",
    ]);
    expect(screen.getByTestId("filter-chip-prescription")) //
      .toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("filter-chip-all")) //
      .toHaveAttribute("aria-pressed", "false");
  });

  it("collapses Lab results + Metrics into More, which renames to the active filter", async () => {
    render(<RecordPage />);
    await waitForTimeline();

    const trigger = screen.getByTestId("filter-more-btn");
    // Closed by default; trigger reads "More".
    expect(trigger.getAttribute("aria-haspopup")).toBe("menu");
    expect(screen.getByTestId("filter-more-label")) //
      .toHaveTextContent("More");

    // Open and pick Lab results from the radio menu.
    fireEvent.pointerDown(trigger);
    fireEvent.click(trigger);
    const item = screen.getByRole("menuitemradio", { name: "Lab results" });
    fireEvent.click(item);

    // The trigger renamed itself to the active filter (ratified outcome).
    expect(await screen.findByTestId("record-timeline")).toBeInTheDocument();
    expect(screen.getByTestId("filter-more-label")) //
      .toHaveTextContent("Lab results");
    const visible = screen
      .getByTestId("record-timeline")
      .querySelectorAll("li");
    expect([...visible].map((li) => li.getAttribute("data-testid"))).toEqual([
      "entry-26",
    ]);
  });

  it("shows the empty state when the filter has no entries", async () => {
    resolveWith({
      ...TIMELINE,
      entries: [entry({ entry_id: 28, entry_type: "consultation" })],
    });
    render(<RecordPage />);
    await waitForTimeline();

    // Metrics is never a chip - it lives in the More menu at every width.
    openMoreMenu();
    fireEvent.click(screen.getByRole("menuitemradio", { name: "Metrics" }));
    expect(screen.getByTestId("empty-state")).toBeInTheDocument();
    expect(screen.queryByTestId("record-timeline")) //
      .not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("filter-chip-all"));
    await waitForTimeline();
  });

  it("shows the empty state when the fresh timeline has no entries at all", async () => {
    resolveWith({ ...TIMELINE, entries: [] });
    render(<RecordPage />);

    expect(await screen.findByTestId("empty-state")).toHaveTextContent(
      "No entries yet",
    );
  });
});

describe("RecordPage bilingual EN/HI (REQ-006)", () => {
  it("renames everything incl. Consultations -> परामर्श in Hindi", async () => {
    render(<LangFlipHost />);
    await waitForTimeline();

    fireEvent.click(screen.getByText("flip-lang"));

    expect(screen.getByRole("heading", { name: "मेरा हेल्थ रिकॉर्ड" })) //
      .toBeInTheDocument();
    expect(screen.getByTestId("filter-chip-consultation")) //
      .toHaveTextContent(STRINGS.hi.record.filter.consultation);
    expect(
      screen.getByRole("heading", {
        name: STRINGS.hi.record.accessHistory.heading,
      }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("entry-24")) //
      .toHaveTextContent(STRINGS.hi.record.badge.delivered);
  });
});

describe("RecordPage access history", () => {
  it("renders real entries with identity, scope and timestamp", async () => {
    render(<RecordPage />);
    await screen.findByTestId("access-history-list");

    expect(mockFetchAccessHistory).toHaveBeenCalledWith(7);
    expect(screen.getByTestId("access-entry-0")).toHaveTextContent("doctor");
    expect(screen.getByTestId("access-entry-0")) //
      .toHaveTextContent("consultations");
    expect(screen.getByTestId("access-entry-1")) //
      .toHaveTextContent("lab_results");
  });

  it("sorts entries newest-first by accessed_at", async () => {
    render(<RecordPage />);
    await screen.findByTestId("access-history-list");

    const first = screen.getByTestId("access-entry-0").textContent ?? "";
    const second = screen.getByTestId("access-entry-1").textContent ?? "";
    // Payload ships lab-before-doctor; the screen reorders newest-first.
    expect(first).toContain("doctor");
    expect(second).toContain("lab");
  });

  it("flags denied attempts with the denied label and reason", async () => {
    resolveAccessWith([
      accessEntry({
        actor_id: 9,
        accessed_at: "2026-08-12T02:33:00Z",
        denied: true,
        denial_reason: "no consent",
      }),
    ]);
    render(<RecordPage />);
    await screen.findByTestId("access-entry-0");

    expect(screen.getByTestId("access-entry-0")) //
      .toHaveTextContent(STRINGS.en.record.accessHistory.deniedLabel);
    expect(screen.getByTestId("access-entry-0")) //
      .toHaveTextContent("no consent");
  });

  it("shows an empty state when there is no access history", async () => {
    resolveAccessWith([]);
    render(<RecordPage />);

    // Growing inline empty copy inside the accordion (both zones carry it).
    const mobileCard = await screen.findByTestId("access-history");
    expect(
      within(mobileCard).getByText(STRINGS.en.record.accessHistory.emptyTitle),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("access-history-list")).not.toBeInTheDocument();
  });

  it("shows a loading skeleton before the entries resolve", async () => {
    mockFetchAccessHistory.mockReturnValue(new Promise(() => {}));
    render(<RecordPage />);

    expect(await screen.findByTestId("access-loading")).toBeInTheDocument();
    expect(screen.queryByTestId("access-history-list")).not.toBeInTheDocument();
  });

  it("shows an error banner when access history fails and recovers on Retry", async () => {
    resolveAccessWith(null);
    render(<RecordPage />);
    await screen.findByTestId("error-banner");
    expect(mockFetchAccessHistory).toHaveBeenCalledTimes(1);

    resolveAccessWith(ACCESS_HISTORY);
    fireEvent.click(screen.getByTestId("error-banner-retry"));
    await screen.findByTestId("access-history-list");
    expect(mockFetchAccessHistory).toHaveBeenCalledTimes(2);
    expect(screen.queryByTestId("error-banner")).not.toBeInTheDocument();
  });
});

describe("RecordPage PROTO-3.1 snapshot strip", () => {
  it("never flashes counts while the record is still loading", async () => {
    mockFetchOwnRecord.mockReturnValue(new Promise(() => {}));
    render(<RecordPage />);

    expect(screen.queryByTestId("snapshot-strip")).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("snapshot-strip-desktop"),
    ).not.toBeInTheDocument();
  });

  it("derives counts from the payload and shows honest zero micro-labels", async () => {
    render(<RecordPage />);
    await waitForTimeline();

    const strip = screen.getByTestId("snapshot-strip");
    expect(within(strip).getByTestId("snapshot-all")).toHaveTextContent("5");
    expect(within(strip).getByTestId("snapshot-prescription")) //
      .toHaveTextContent("2");
    // One of two rx entries is still issued -> the tile carries `1 issued`.
    expect(screen.getByTestId("snapshot-issued")).toHaveTextContent("1 issued");
    // No out-of-range rows in the payload: no flagged micro-label at all.
    expect(screen.queryByTestId("snapshot-flagged")).not.toBeInTheDocument();
  });

  it("doubles as a jump-filter: it scopes the feed and mirrors aria-pressed", async () => {
    render(<RecordPage />);
    await waitForTimeline();

    expect(screen.getByTestId("snapshot-consultation")).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    fireEvent.click(screen.getByTestId("snapshot-consultation"));
    expect(screen.getByTestId("snapshot-consultation")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByTestId("filter-chip-consultation")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    const visible = screen
      .getByTestId("record-timeline")
      .querySelectorAll("li");
    expect([...visible].map((li) => li.getAttribute("data-testid"))).toEqual([
      "entry-28",
    ]);
  });

  it("mirrors the same counts as static read-only tiles on desktop", async () => {
    render(<RecordPage />);
    await waitForTimeline();

    const desktop = screen.getByTestId("snapshot-strip-desktop");
    // The desktop copy is informational only - never a second set of controls.
    expect(desktop.querySelectorAll("button")).toHaveLength(0);
    expect(within(desktop).getByText("5")).toBeInTheDocument();
    expect(within(desktop).getByText("Prescriptions")).toBeInTheDocument();
    // One rx entry is still issued -> the prescription tile carries it; other
    // tiles never claim anything about delivery.
    expect(within(desktop).getByText("1 issued")).toBeInTheDocument();
  });

  it("renders a truthful `0 issued` micro-label, and never on other tiles", async () => {
    resolveWith({
      ...TIMELINE,
      entries: [
        entry({
          entry_type: "prescription",
          payload: { prescription_id: 9, status: "delivered" },
          occurred_at: "2026-08-22T08:00:00Z",
        }),
        entry({
          entry_type: "consultation",
          payload: {},
          occurred_at: "2026-08-21T10:30:00Z",
        }),
        entry({
          entry_type: "lab_report",
          payload: { order_id: 1042 },
          occurred_at: "2026-08-21T14:30:00Z",
        }),
      ],
    });
    render(<RecordPage />);
    await waitForTimeline();

    expect(
      within(screen.getByTestId("snapshot-prescription")).getByTestId(
        "snapshot-issued",
      ),
    ).toHaveTextContent("0 issued");
    expect(
      within(screen.getByTestId("snapshot-consultation")).queryByText(/issued/),
    ).toBeNull();
    expect(
      within(screen.getByTestId("snapshot-lab_report")).queryByText(/issued/),
    ).toBeNull();
    expect(
      within(screen.getByTestId("snapshot-strip-desktop")).getByText(
        "0 issued",
      ),
    ).toBeInTheDocument();
  });
});

describe("RecordPage PROTO-3.1 filter chip vocabulary", () => {
  it("never renders Metrics as a chip - it lives in More at every width", async () => {
    render(<RecordPage />);
    await waitForTimeline();

    expect(screen.queryByTestId("filter-chip-metric")).not.toBeInTheDocument();
    openMoreMenu();
    expect(
      screen.getByRole("menuitemradio", { name: "Metrics" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("menuitemradio", { name: "Lab results" }),
    ).toBeInTheDocument();
  });
});

describe("RecordPage PROTO-3.1 timeline date grouping", () => {
  it("labels month buckets with a localized heading and count", async () => {
    render(<RecordPage />);
    await waitForTimeline();

    expect(screen.getByTestId("group-2026-08")).toBeInTheDocument();
    expect(screen.getByTestId("group-count-2026-08")).toHaveTextContent("5");
  });

  it("links every entry card to its detail page", async () => {
    render(<RecordPage />);
    await waitForTimeline();

    expect(screen.getByTestId("entry-link-24")).toHaveAttribute(
      "href",
      "/patient/record/24",
    );
    expect(screen.getByTestId("entry-link-26")).toHaveAttribute(
      "href",
      "/patient/record/26",
    );
  });
});

describe("RecordPage PROTO-3.1 out-of-range lab flags", () => {
  const FLAGGED_TIMELINE: RecordTimeline = {
    ...TIMELINE,
    entries: [
      entry({
        entry_id: 26,
        entry_type: "lab_report",
        payload: {
          order_id: 1042,
          filename: "cbc-panel.pdf",
          results: [
            { test: "Hb", value: "8.2", status: "below_range" },
            { test: "WBC", value: "12.1", status: "above_range" },
          ],
        },
        occurred_at: "2026-08-21T14:30:00Z",
      }),
    ],
  };

  it("renders per-row amber badges and the flagged micro-label", async () => {
    resolveWith(FLAGGED_TIMELINE);
    render(<RecordPage />);
    await waitForTimeline();

    expect(screen.getByTestId("lab-flag-26-0")).toHaveTextContent(
      "Hb 8.2 · below usual range",
    );
    expect(screen.getByTestId("lab-flag-26-1")).toHaveTextContent(
      "WBC 12.1 · above usual range",
    );
    expect(screen.getByTestId("snapshot-flagged")).toHaveTextContent(
      "1 flagged",
    );
  });

  it("summarizes flagged rows in the desktop rail footnote", async () => {
    resolveWith(FLAGGED_TIMELINE);
    render(<RecordPage />);
    await waitForTimeline();

    const rail = screen.getByTestId("record-rail");
    expect(within(rail).getByTestId("record-rail-flag-footnote")) //
      .toHaveTextContent("2 values outside your usual range");
  });
});

describe("RecordPage PROTO-3.1 zones", () => {
  it("stacks the health snapshot and who-accessed cards under the mobile feed", async () => {
    render(<RecordPage />);
    await screen.findByTestId("access-history-list");

    const mobile = screen.getByTestId("record-privacy-mobile");
    await within(mobile).findByTestId("health-snapshot");
    expect(within(mobile).getByTestId("access-history")).toBeInTheDocument();
    // The consent-log entry point now lives inside the who-accessed section.
    expect(
      within(mobile).getByTestId("access-consent-log-link"),
    ).toHaveAttribute("href", "/patient/record/consent-log");
    // Only two access rows exist -> no "see the latest 5" hint.
    expect(
      within(mobile).queryByTestId("access-more-hint"),
    ).not.toBeInTheDocument();
  });

  it("mirrors the summary, health snapshot and who-accessed list in the rail", async () => {
    render(<RecordPage />);
    await waitForTimeline();
    await screen.findByTestId("access-history-rail-list");

    const rail = screen.getByTestId("record-rail");
    expect(within(rail).getByTestId("record-rail-summary")).toBeInTheDocument();
    await within(rail).findByTestId("health-snapshot");
    expect(
      within(rail).getByTestId("access-consent-log-link-rail"),
    ).toHaveAttribute("href", "/patient/record/consent-log");
    expect(
      within(rail).queryByTestId("access-more-hint-rail"),
    ).not.toBeInTheDocument();
    // The rail carries its own access list testid set (same data, newest first).
    expect(
      within(rail).getByTestId("access-history-rail-list"),
    ).toBeInTheDocument();
    expect(within(rail).getByTestId("access-entry-rail-0")).toHaveTextContent(
      "doctor",
    );
  });

  it("renders only the latest five rows with a hint and the full-count badge", async () => {
    const many = Array.from({ length: 7 }, (_, i) =>
      accessEntry({
        actor_id: i + 10,
        actor_type: "doctor",
        accessed_at: `2026-08-${String(i + 1).padStart(2, "0")}T09:00:00Z`,
      }),
    );
    resolveAccessWith(many);
    render(<RecordPage />);
    await screen.findByTestId("access-history-list");

    const mobile = screen.getByTestId("record-privacy-mobile");
    const list = within(mobile).getByTestId("access-history-list");
    expect(list.querySelectorAll("li")).toHaveLength(5);
    expect(mobile.querySelectorAll("[data-testid='access-more-hint']")) //
      .toHaveLength(1);
    expect(within(mobile).getByTestId("access-more-hint")) //
      .toHaveTextContent("Showing the 5 most recent");
    // The badge reports the full audit count, not the five rendered rows.
    expect(within(mobile).getByTestId("access-history")).toHaveTextContent("7");
  });

  it("summarizes payload counts in the at-a-glance rail card", async () => {
    render(<RecordPage />);
    await waitForTimeline();

    const summary = screen.getByTestId("record-rail-summary");
    expect(within(summary).getByText("Consultations")).toBeInTheDocument();
    // One entry per consultation/lab/metric; two prescriptions.
    expect(within(summary).getAllByText("1")).toHaveLength(3);
    expect(within(summary).getByText("2")).toBeInTheDocument();
  });
});
