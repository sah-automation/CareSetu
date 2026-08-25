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

vi.mock("@/lib/record/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/record/api")>();
  return { ...mod, fetchOwnRecord: vi.fn() };
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

beforeEach(() => {
  __resetLangForTests();
  resolveWith(TIMELINE);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

async function waitForTimeline() {
  await screen.findByTestId("record-timeline");
}

describe("RecordPage (inside the patient light shell)", () => {
  it("mounts within the patient AppShell with header, filters and placeholders", async () => {
    render(
      <PatientGroupLayout>
        <LangFlipHost />
      </PatientGroupLayout>,
    );
    await waitForTimeline();

    expect(screen.getByTestId("app-shell")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "My Record" })) //
      .toBeInTheDocument();
    expect(
      screen.getByRole("group", { name: "Filter record entries" }),
    ).toBeInTheDocument();
    // Forward-scope placeholders stay Soon (Phases 4/12).
    for (const id of ["placeholder-access", "placeholder-health"]) {
      const card = screen.getByTestId(id);
      expect(card).toHaveAttribute("aria-disabled", "true");
      expect(card.querySelector('[data-testid="soon-badge"]')).not.toBeNull();
    }
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
    expect(mockFetchOwnRecord).toHaveBeenCalledTimes(3);
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

    fireEvent.click(screen.getByTestId("filter-chip-metric"));
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

    expect(screen.getByRole("heading", { name: "मेरा रिकॉर्ड" })) //
      .toBeInTheDocument();
    expect(screen.getByTestId("filter-chip-consultation")) //
      .toHaveTextContent(STRINGS.hi.record.filter.consultation);
    expect(screen.getByTestId("placeholder-access")) //
      .toHaveTextContent(STRINGS.hi.record.placeholder.accessTitle);
    expect(screen.getByTestId("entry-24")) //
      .toHaveTextContent(STRINGS.hi.record.badge.delivered);
  });
});
