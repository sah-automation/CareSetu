// PHASE-7 T19 (#363): intake status list page suite - renders the four intake
// statuses (Captured / Structuring / Ready for Review / Recapture needed)
// mapped from the backend machine status values, refreshes statuses from the
// backend in-page (get_intake / get_pre_summary), marks the current + done
// steps, shows a ready pre-summary's continue affordance into consultation
// booking, and surfaces the re-record / type instead path on recapture-needed.
// Bilingual EN/HI. The intake API is mocked at the seam.

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import IntakeStatusPage from "./page";
import PatientGroupLayout from "@/app/(patient)/layout";
import { ApiError } from "@/lib/api-errors";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { __resetLangForTests, useLang } from "@/lib/i18n/LangContext";
import {
  fetchIntake,
  fetchPreSummary,
  type IntakeDetailView,
  type IntakeStatus,
  type PreSummaryView,
} from "@/lib/intake/api";

vi.mock("next/navigation", () => ({
  useParams: () => ({ intakeId: "42" }),
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/patient/intake/42/status",
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

vi.mock("@/lib/intake/api", () => ({
  fetchIntake: vi.fn(),
  fetchPreSummary: vi.fn(),
}));

const t = STRINGS.en.intake.status;
const hiT = STRINGS.hi.intake.status;
const getIntake = vi.mocked(fetchIntake);
const getPreSummary = vi.mocked(fetchPreSummary);

function intake(
  overrides: Partial<IntakeDetailView> & { status?: IntakeStatus } = {},
): IntakeDetailView {
  return {
    intake_id: 42,
    patient_id: 7,
    mode: "voice",
    language: "en",
    status: "structuring",
    record_attempts: 1,
    text: null,
    transcript: "fever since 2 days",
    transcript_usability: "usable",
    forced_text: false,
    media_refs: [],
    created_at: "2026-09-08T10:00:00Z",
    updated_at: "2026-09-08T10:00:00Z",
    ...overrides,
  };
}

function preSummary(overrides: Partial<PreSummaryView> = {}): PreSummaryView {
  return {
    pre_summary_id: 9,
    intake_id: 42,
    structured_fields: { chief_complaints: ["fever"] },
    structuring_confidence: 0.82,
    low_confidence: false,
    review_state: "draft",
    patient_edits: null,
    doctor_corrections: null,
    review_attribution: null,
    reviewed_by: null,
    reviewed_at: null,
    created_at: "2026-09-08T10:00:00Z",
    updated_at: "2026-09-08T10:00:00Z",
    ...overrides,
  };
}

function LangFlipHost() {
  const { lang, setLang } = useLang();
  return (
    <>
      <button
        type="button"
        onClick={() => setLang(lang === "en" ? "hi" : "en")}
      >
        flip-lang
      </button>
      <IntakeStatusPage />
    </>
  );
}

async function flush() {
  await act(async () => {});
}

async function renderLoaded(overrides: Parameters<typeof intake>[0] = {}) {
  getIntake.mockResolvedValue(intake(overrides));
  render(<IntakeStatusPage />);
  await flush();
}

beforeEach(() => {
  __resetLangForTests();
  getIntake.mockReset();
  getPreSummary.mockReset();
  getIntake.mockResolvedValue(intake());
  getPreSummary.mockResolvedValue(preSummary());
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("IntakeStatusPage (inside the patient shell)", () => {
  it("mounts within the patient AppShell", async () => {
    render(
      <PatientGroupLayout>
        <IntakeStatusPage />
      </PatientGroupLayout>,
    );
    await flush();
    expect(screen.getByTestId("app-shell")).toBeInTheDocument();
  });
});

describe("IntakeStatusPage status list", () => {
  it("renders the four status steps in order", async () => {
    await renderLoaded({ status: "captured" });

    expect(screen.getByTestId("status-list")).toBeInTheDocument();
    expect(screen.getByTestId("status-row-captured")).toBeInTheDocument();
    expect(screen.getByTestId("status-row-structuring")).toBeInTheDocument();
    expect(
      screen.getByTestId("status-row-ready_for_review"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("status-row-re_record")).toBeInTheDocument();
  });

  it("maps backend status values to the four labels", async () => {
    await renderLoaded({ status: "ready_for_review" });

    expect(screen.getByTestId("status-label-captured")).toHaveTextContent(
      t.captured,
    );
    expect(screen.getByTestId("status-label-structuring")).toHaveTextContent(
      t.structuring,
    );
    expect(
      screen.getByTestId("status-label-ready_for_review"),
    ).toHaveTextContent(t.readyForReview);
    expect(screen.getByTestId("status-label-re_record")).toHaveTextContent(
      t.reRecord,
    );
  });

  it("marks the current status and prior steps done", async () => {
    await renderLoaded({ status: "ready_for_review" });

    expect(
      screen.getByTestId("status-current-ready_for_review"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("status-done-captured")).toBeInTheDocument();
    expect(screen.getByTestId("status-done-structuring")).toBeInTheDocument();
    expect(
      screen.queryByTestId("status-done-ready_for_review"),
    ).not.toBeInTheDocument();
  });
});

describe("IntakeStatusPage status refresh", () => {
  it("refetches intake and the ready pre-summary on Refresh", async () => {
    getIntake.mockResolvedValue(intake({ status: "ready_for_review" }));
    getPreSummary.mockResolvedValue(preSummary());
    await renderLoaded({ status: "ready_for_review" });

    const refreshCallsBefore = getIntake.mock.calls.length;
    fireEvent.click(screen.getByTestId("btn-refresh"));
    await flush();

    expect(getIntake.mock.calls.length).toBe(refreshCallsBefore + 1);
    expect(getPreSummary).toHaveBeenCalledWith(42);
  });

  it("polls while structuring without manual refresh", async () => {
    vi.useFakeTimers();
    try {
      getIntake.mockResolvedValue(intake({ status: "structuring" }));
      render(<IntakeStatusPage />);
      await flush();

      // Simulate the pre-summary becoming ready on the next poll.
      getIntake.mockResolvedValue(intake({ status: "ready_for_review" }));
      getPreSummary.mockResolvedValue(preSummary());

      await act(async () => {
        await vi.advanceTimersByTimeAsync(2000);
      });

      expect(getIntake.mock.calls.length).toBeGreaterThan(0);
      expect(
        screen.getByTestId("status-current-ready_for_review"),
      ).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("IntakeStatusPage continue affordance", () => {
  it("shows the continue button into consultation booking when ready", async () => {
    getIntake.mockResolvedValue(intake({ status: "ready_for_review" }));
    getPreSummary.mockResolvedValue(preSummary());
    await renderLoaded({ status: "ready_for_review" });

    expect(screen.getByTestId("continue-zone")).toBeInTheDocument();
    expect(screen.getByTestId("btn-continue")).toHaveAttribute(
      "href",
      "/doctors?intake=42",
    );
    expect(screen.getByTestId("btn-continue")).toHaveTextContent(t.continue);
  });

  it("hides the continue affordance until the pre-summary is ready", async () => {
    await renderLoaded({ status: "structuring" });
    expect(screen.queryByTestId("continue-zone")).not.toBeInTheDocument();
  });
});

describe("IntakeStatusPage re-record path", () => {
  it("shows re-record + type instead on recapture needed", async () => {
    getIntake.mockResolvedValue(intake({ status: "re_record" }));
    await renderLoaded({ status: "re_record" });

    expect(screen.getByTestId("rerecord-zone")).toBeInTheDocument();
    expect(screen.getByTestId("btn-rerecord")).toHaveTextContent(
      t.reRecordAction,
    );
    expect(screen.getByTestId("btn-type")).toHaveTextContent(t.typeInstead);
    expect(screen.getByTestId("btn-rerecord")).toHaveAttribute(
      "href",
      "/patient/intake/voice",
    );
    expect(screen.getByTestId("btn-type")).toHaveAttribute(
      "href",
      "/patient/intake/text",
    );
  });
});

describe("IntakeStatusPage failure", () => {
  it("shows the dedicated failed-state copy for a terminal backend failure", async () => {
    getIntake.mockResolvedValue(intake({ status: "failed" }));
    await renderLoaded({ status: "failed" });

    expect(screen.getByTestId("status-row-failed")).toHaveTextContent(t.failed);
    expect(screen.getByTestId("status-row-failed")).toHaveTextContent(
      t.failedDesc,
    );
    expect(screen.queryByTestId("continue-zone")).not.toBeInTheDocument();
    expect(screen.queryByTestId("rerecord-zone")).not.toBeInTheDocument();
  });

  it("shows a trace-id error banner when the intake fails to load, and retries", async () => {
    const apiError = new ApiError({
      code: "INTERNAL_ERROR",
      message: "boom",
      trace_id: "trace-st999001",
      details: {},
    });
    getIntake.mockRejectedValueOnce(apiError);
    render(<IntakeStatusPage />);
    await flush();

    expect(screen.getByTestId("error-banner")).toHaveTextContent(
      t.loadFailedTitle,
    );
    expect(screen.getByTestId("error-banner-trace-id")).toHaveTextContent(
      "trace-st999001",
    );

    getIntake.mockResolvedValue(intake({ status: "captured" }));
    fireEvent.click(screen.getByTestId("error-banner-retry"));
    await flush();

    expect(screen.getByTestId("status-list")).toBeInTheDocument();
    expect(getIntake).toHaveBeenCalledTimes(2);
  });

  it("reads the intake id from the route params", async () => {
    await renderLoaded({ status: "captured" });
    expect(getIntake).toHaveBeenCalledWith(42);
  });
});

describe("IntakeStatusPage bilingual EN/HI (REQ-006)", () => {
  it("switches all visible copy to Hindi when the locale flips", async () => {
    getIntake.mockResolvedValue(intake({ status: "ready_for_review" }));
    getPreSummary.mockResolvedValue(preSummary());
    render(<LangFlipHost />);
    await flush();

    fireEvent.click(screen.getByText("flip-lang"));
    await flush();

    expect(screen.getByTestId("status-label-captured")).toHaveTextContent(
      hiT.captured,
    );
    expect(screen.getByTestId("status-label-structuring")).toHaveTextContent(
      hiT.structuring,
    );
    expect(
      screen.getByTestId("status-label-ready_for_review"),
    ).toHaveTextContent(hiT.readyForReview);
    expect(screen.getByTestId("status-label-re_record")).toHaveTextContent(
      hiT.reRecord,
    );
    expect(screen.getByTestId("btn-continue")).toHaveTextContent(hiT.continue);
  });
});
