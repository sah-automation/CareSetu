// PHASE-3 T8 (#217): Entry detail screen suite - source attribution,
// consent lineage citation, lab-results table, egress trail presence/
// absence, not-found, error/retry lifecycle, and bilingual EN/HI parity.

import {
  cleanup,
  render,
  screen,
  fireEvent,
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

import EntryDetailPage from "./page";
import PatientGroupLayout from "@/app/(patient)/layout";
import { __resetLangForTests, useLang } from "@/lib/i18n/LangContext";
import { STRINGS } from "@/lib/i18n/dictionaries";
import {
  fetchOwnRecord,
  type RecordEntryView,
  type RecordTimeline,
} from "@/lib/record/api";
import { fetchEgressLog, type EgressLog } from "@/lib/consent/api";

const mockUseParams = vi.fn(() => ({ entryId: "26" }));

vi.mock("@/lib/record/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/record/api")>();
  return { ...mod, fetchOwnRecord: vi.fn() };
});

vi.mock("@/lib/consent/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/consent/api")>();
  return { ...mod, fetchEgressLog: vi.fn() };
});

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/patient/record/entry/26",
  useParams: () => mockUseParams(),
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
const mockFetchEgressLog = vi.mocked(fetchEgressLog);

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

const LAB_ENTRY = entry({
  entry_id: 26,
  entry_type: "lab_report",
  payload: {
    order_id: 1042,
    filename: "cbc-panel.pdf",
    results: [
      {
        test: "Hemoglobin",
        value: "11.2 g/dL",
        range: "12.0 - 15.5",
        status: "below_range",
      },
      {
        test: "WBC count",
        value: "7,400 /uL",
        range: "4,000 - 11,000",
        status: "in_range",
      },
      {
        test: "Platelets",
        value: "2.6 lakh /uL",
        range: "1.5 - 4.1 lakh",
        status: "in_range",
      },
    ],
  },
  occurred_at: "2026-08-21T14:30:00Z",
});

const CONSULTATION_ENTRY = entry({
  entry_id: 28,
  entry_type: "consultation",
  payload: {},
  occurred_at: "2026-08-19T10:30:00Z",
});

const TIMELINE: RecordTimeline = {
  record_id: 5,
  patient_id: 7,
  created_at: "2026-08-01T09:00:00Z",
  entries: [LAB_ENTRY, CONSULTATION_ENTRY],
};

const EGRESS_LOG: EgressLog = {
  items: [
    {
      egress_id: 1,
      patient_id: 7,
      consent_id: 11,
      lineage_ref: "C-2026-011",
      version: 1,
      counterparty_type: "provider",
      counterparty_id: "Dr. A. Kumar",
      record_scope: "lab_report",
      disclosed_entry_ids: [26],
      disclosed_at: "2026-08-19T09:00:00Z",
    },
  ],
};

const EMPTY_EGRESS: EgressLog = { items: [] };

function resolveWith(
  timeline: RecordTimeline | null,
  egress: EgressLog = EMPTY_EGRESS,
) {
  mockFetchOwnRecord.mockImplementation(() =>
    timeline === null
      ? Promise.reject(new Error("network down"))
      : Promise.resolve(timeline),
  );
  mockFetchEgressLog.mockImplementation(() => Promise.resolve(egress));
}

function rejectEgress() {
  mockFetchEgressLog.mockImplementation(() =>
    Promise.reject(new Error("network down")),
  );
}

beforeEach(() => {
  __resetLangForTests();
  mockUseParams.mockReturnValue({ entryId: "26" });
  resolveWith(TIMELINE, EMPTY_EGRESS);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function LangFlipHost() {
  return (
    <>
      {langFlip()}
      <EntryDetailPage />
    </>
  );
}

describe("EntryDetailPage (inside the patient light shell)", () => {
  it("shows loading skeletons while fetching", () => {
    render(
      <PatientGroupLayout>
        <EntryDetailPage />
      </PatientGroupLayout>,
    );
    expect(screen.getByTestId("entry-detail-loading")).toBeInTheDocument();
  });

  it("renders source card and breadcrumbs for a lab report entry", async () => {
    resolveWith(TIMELINE, EGRESS_LOG);
    render(
      <PatientGroupLayout>
        <EntryDetailPage />
      </PatientGroupLayout>,
    );

    await waitFor(() =>
      expect(
        screen.queryByTestId("entry-detail-loading"),
      ).not.toBeInTheDocument(),
    );

    expect(screen.getByTestId("app-shell")).toBeInTheDocument();
    expect(screen.getByTestId("page-header")).toBeInTheDocument();
    expect(screen.getByTestId("breadcrumbs")).toBeInTheDocument();
    expect(screen.getByTestId("entry-source-card")).toBeInTheDocument();
  });

  it("shows the not-found state when entry ID is missing from timeline", async () => {
    resolveWith({ ...TIMELINE, entries: [CONSULTATION_ENTRY] });
    render(<EntryDetailPage />);

    await waitFor(() =>
      expect(screen.getByTestId("entry-detail-not-found")).toBeInTheDocument(),
    );
    const notFoundCard = screen.getByTestId("entry-detail-not-found");
    expect(notFoundCard).toHaveTextContent("Entry not found.");
  });

  it("shows error banner on API failure and recovers on retry", async () => {
    resolveWith(null);
    render(<EntryDetailPage />);

    await screen.findByTestId("error-banner");
    expect(
      screen.queryByTestId("entry-detail-loading"),
    ).not.toBeInTheDocument();

    // Retry still failing
    resolveWith(null);
    fireEvent.click(screen.getByTestId("error-banner-retry"));
    await waitFor(() =>
      expect(screen.queryByTestId("error-banner")).not.toBeInTheDocument(),
    );
    await screen.findByTestId("error-banner");
    expect(mockFetchOwnRecord).toHaveBeenCalledTimes(2);

    // Retry succeeds
    resolveWith(TIMELINE, EMPTY_EGRESS);
    fireEvent.click(screen.getByTestId("error-banner-retry"));
    await waitFor(() =>
      expect(screen.queryByTestId("error-banner")).not.toBeInTheDocument(),
    );
    expect(mockFetchOwnRecord).toHaveBeenCalledTimes(3);
  });
});

describe("EntryDetailPage source and consent", () => {
  it("shows filing metadata (date, booking ref) in the page header description", async () => {
    resolveWith(TIMELINE, EMPTY_EGRESS);
    render(<EntryDetailPage />);

    await waitFor(() =>
      expect(
        screen.queryByTestId("entry-detail-loading"),
      ).not.toBeInTheDocument(),
    );

    const header = screen.getByTestId("page-header");
    expect(header).toHaveTextContent("21 Aug 2026");
    expect(header).toHaveTextContent("#1042");
  });

  it("shows consent lineage reference when egress trail exists", async () => {
    resolveWith(TIMELINE, EGRESS_LOG);
    render(<EntryDetailPage />);

    await waitFor(() =>
      expect(
        screen.queryByTestId("entry-detail-loading"),
      ).not.toBeInTheDocument(),
    );

    const sourceCard = screen.getByTestId("entry-source-card");
    expect(within(sourceCard).getByText(/C-2026-011/)).toBeInTheDocument();
    expect(within(sourceCard).getByText(/v1/)).toBeInTheDocument();
    expect(screen.getByTestId("consent-log-link")).toBeInTheDocument();
  });

  it("omits consent section silently when no egress trail exists", async () => {
    resolveWith(TIMELINE, EMPTY_EGRESS);
    render(<EntryDetailPage />);

    await waitFor(() =>
      expect(
        screen.queryByTestId("entry-detail-loading"),
      ).not.toBeInTheDocument(),
    );

    expect(screen.queryByTestId("consent-log-link")).not.toBeInTheDocument();
  });
});

describe("EntryDetailPage lab results table", () => {
  it("renders a results table for lab_report entries with results data", async () => {
    resolveWith(TIMELINE, EGRESS_LOG);
    render(<EntryDetailPage />);

    await waitFor(() =>
      expect(
        screen.queryByTestId("entry-detail-loading"),
      ).not.toBeInTheDocument(),
    );

    expect(screen.getByTestId("entry-results-table")).toBeInTheDocument();
    expect(screen.getByTestId("lab-results-table")).toBeInTheDocument();

    const table = screen.getByTestId("lab-results-table");
    expect(table).toHaveTextContent("Hemoglobin");
    expect(table).toHaveTextContent("11.2 g/dL");
    expect(table).toHaveTextContent("WBC count");
    expect(table).toHaveTextContent("Platelets");
  });

  it("renders correct status badges (in range vs below range)", async () => {
    resolveWith(TIMELINE, EGRESS_LOG);
    render(<EntryDetailPage />);

    await waitFor(() =>
      expect(
        screen.queryByTestId("entry-detail-loading"),
      ).not.toBeInTheDocument(),
    );

    const belowRangeBadge = screen.getByTestId("lab-status-0");
    expect(belowRangeBadge).toHaveTextContent("Below range");

    const inRangeBadge = screen.getByTestId("lab-status-1");
    expect(inRangeBadge).toHaveTextContent("In range");
  });

  it("omits the results table for non-lab entry types", async () => {
    mockUseParams.mockReturnValue({ entryId: "28" });

    resolveWith(TIMELINE, EMPTY_EGRESS);
    render(<EntryDetailPage />);

    await waitFor(() =>
      expect(
        screen.queryByTestId("entry-detail-loading"),
      ).not.toBeInTheDocument(),
    );

    expect(screen.queryByTestId("entry-results-table")).not.toBeInTheDocument();
    expect(screen.queryByTestId("lab-results-table")).not.toBeInTheDocument();
  });

  it("omits the results table when lab entry has no results array", async () => {
    const labNoResults = entry({
      entry_id: 99,
      entry_type: "lab_report",
      payload: { order_id: 200, filename: "xray.pdf" },
      occurred_at: "2026-08-20T10:00:00Z",
    });
    resolveWith({ ...TIMELINE, entries: [labNoResults] }, EMPTY_EGRESS);
    render(<EntryDetailPage />);

    await waitFor(() =>
      expect(
        screen.queryByTestId("entry-detail-loading"),
      ).not.toBeInTheDocument(),
    );

    expect(screen.queryByTestId("entry-results-table")).not.toBeInTheDocument();
  });
});

describe("EntryDetailPage egress trail", () => {
  it("renders the trail when disclosures exist for this entry", async () => {
    resolveWith(TIMELINE, EGRESS_LOG);
    render(<EntryDetailPage />);

    await waitFor(() =>
      expect(
        screen.queryByTestId("entry-detail-loading"),
      ).not.toBeInTheDocument(),
    );

    expect(screen.getByTestId("entry-egress-trail")).toBeInTheDocument();
    expect(screen.getByText("Who has seen this entry")).toBeInTheDocument();
    expect(screen.getByTestId("egress-entry-1")).toHaveTextContent("provider");
    expect(screen.getByTestId("egress-entry-1")).toHaveTextContent(
      "Dr. A. Kumar",
    );
  });

  it("omits the trail silently when no disclosures exist for this entry", async () => {
    // Egress has entries but none include entry_id 26
    const unrelatedEgress: EgressLog = {
      items: [
        {
          egress_id: 2,
          patient_id: 7,
          consent_id: 12,
          lineage_ref: "C-2026-012",
          version: 1,
          counterparty_type: "provider",
          counterparty_id: "Dr. B",
          record_scope: "consultation",
          disclosed_entry_ids: [28],
          disclosed_at: "2026-08-20T10:00:00Z",
        },
      ],
    };
    resolveWith(TIMELINE, unrelatedEgress);
    render(<EntryDetailPage />);

    await waitFor(() =>
      expect(
        screen.queryByTestId("entry-detail-loading"),
      ).not.toBeInTheDocument(),
    );

    expect(screen.queryByTestId("entry-egress-trail")).not.toBeInTheDocument();
  });
});

describe("EntryDetailPage action bar", () => {
  it("shows share and download buttons", async () => {
    resolveWith(TIMELINE, EMPTY_EGRESS);
    render(<EntryDetailPage />);

    await waitFor(() =>
      expect(
        screen.queryByTestId("entry-detail-loading"),
      ).not.toBeInTheDocument(),
    );

    expect(screen.getByTestId("share-entry-btn")).toBeInTheDocument();
    expect(screen.getByTestId("download-pdf-btn")).toBeInTheDocument();
    expect(screen.getByTestId("download-pdf-btn")).toBeDisabled();
  });
});

describe("EntryDetailPage bilingual EN/HI (REQ-006)", () => {
  it("renames all copy to Hindi when language is flipped", async () => {
    resolveWith(TIMELINE, EGRESS_LOG);
    render(<LangFlipHost />);

    await waitFor(() =>
      expect(
        screen.queryByTestId("entry-detail-loading"),
      ).not.toBeInTheDocument(),
    );

    fireEvent.click(screen.getByText("flip-lang"));

    const sourceCard = screen.getByTestId("entry-source-card");
    expect(within(sourceCard).getByText("स्रोत")).toBeInTheDocument();
    expect(within(sourceCard).getByText("अनुमति का हवाला")).toBeInTheDocument();
    expect(within(sourceCard).getByText(/C-2026-011/)).toBeInTheDocument();
    expect(screen.getByTestId("entry-results-table")).toHaveTextContent(
      "नतीजे",
    );
    expect(screen.getByTestId("entry-results-table")).toHaveTextContent("जाँच");
    expect(screen.getByTestId("lab-status-0")).toHaveTextContent(
      STRINGS.hi.record.detail.resultsStatusBelowRange,
    );
    expect(screen.getByTestId("entry-egress-trail")).toHaveTextContent(
      "इस एंट्री को किसने देखा",
    );
    expect(screen.getByTestId("share-entry-btn")).toHaveTextContent(
      STRINGS.hi.record.detail.shareEntry,
    );
    expect(screen.getByTestId("download-pdf-btn")).toHaveTextContent(
      STRINGS.hi.record.detail.downloadPdf,
    );
  });
});
