// PHASE-8.1 T13 (#451): case workspace review route (/doctor/review/[intakeId])
// suite. Covers: the stage chip and forced-review requirement (US-13), full
// pre-summary render (chief complaints, symptoms, duration, confidence,
// attribution), the single-action attributed finalize (US-14/#442), the
// consented health history (used via ConsentedHistory, deny-safe), the
// consult-complete handshake into prescription-pending (US-24), load failure
// with retry, and bilingual EN/HI parity (REQ-006).

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import ReviewWorkspacePage from "./page";
import { ApiError } from "@/lib/api-errors";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { __resetLangForTests, useLang } from "@/lib/i18n/LangContext";
import {
  fetchPreSummaryForReview,
  reviewPreSummary,
  type PreSummaryReviewResult,
  type PreSummaryView,
} from "@/lib/intake/api";
import {
  listOpenCases,
  markConsultComplete,
  type CareCaseStage,
  type CaseDetailView,
} from "@/lib/care/api";
import { fetchPartnerMe, type PartnerMeView } from "@/lib/partner/api";
import { readConsentedHistory, type RecordTimeline } from "@/lib/record/api";

vi.mock("next/link", () => {
  return {
    default: ({
      href,
      children,
      ...rest
    }: {
      href: string;
      children: ReactNode;
    }) => (
      <a href={href} {...rest}>
        {children}
      </a>
    ),
  };
});

vi.mock("@/lib/intake/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/intake/api")>();
  return {
    ...mod,
    fetchPreSummaryForReview: vi.fn(),
    reviewPreSummary: vi.fn(),
  };
});

vi.mock("@/lib/care/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/care/api")>();
  return { ...mod, listOpenCases: vi.fn(), markConsultComplete: vi.fn() };
});

vi.mock("@/lib/partner/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/partner/api")>();
  return { ...mod, fetchPartnerMe: vi.fn() };
});

vi.mock("@/lib/record/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/record/api")>();
  return { ...mod, readConsentedHistory: vi.fn() };
});

const t = STRINGS.en.caseWorkspace;
const consoleT = STRINGS.en.doctorConsole;
const hiT = STRINGS.hi.caseWorkspace;
const getPre = vi.mocked(fetchPreSummaryForReview);
const doReview = vi.mocked(reviewPreSummary);
const getCases = vi.mocked(listOpenCases);
const doHandshake = vi.mocked(markConsultComplete);
const getMe = vi.mocked(fetchPartnerMe);
const getHistory = vi.mocked(readConsentedHistory);

function preSummary(overrides: Partial<PreSummaryView> = {}): PreSummaryView {
  return {
    pre_summary_id: 5,
    intake_id: 42,
    structured_fields: {
      chief_complaints: ["Fever"],
      symptoms: ["Headache", "Chills"],
      duration: "3 days",
    },
    structuring_confidence: 0.44,
    low_confidence: true,
    review_state: "draft",
    patient_edits: null,
    doctor_corrections: null,
    review_attribution: null,
    reviewed_by: null,
    reviewed_at: null,
    created_at: "2026-09-10T10:00:00Z",
    updated_at: "2026-09-10T10:00:00Z",
    ...overrides,
  };
}

function caseItem(
  id: number,
  overrides: Partial<CaseDetailView> = {},
): CaseDetailView {
  const { stage, ...rest } = overrides;
  return {
    case_id: id,
    patient_id: 3,
    doctor_id: 7,
    pre_summary_id: 5,
    stage: (stage ?? "pre_summary") as CareCaseStage,
    forced_review: false,
    closed_at: null,
    close_reason: null,
    created_at: "2026-09-12T10:00:00Z",
    updated_at: "2026-09-12T10:00:00Z",
    ...rest,
  };
}

function me(): PartnerMeView {
  return {
    partner_id: 7,
    status: "Active",
    partner_type: "doctor",
    round: 0,
  };
}

function reviewResult(): PreSummaryReviewResult {
  return {
    intake_id: 42,
    pre_summary_id: 5,
    review_state: "final",
    reviewed_copy: {
      chief_complaints: ["Fever"],
      symptoms: ["Headache", "Chills"],
      duration: "3 days",
    },
    changed_fields: [],
    review_attribution: "doctor",
    reviewed_by: 7,
    reviewed_at: "2026-09-16T09:00:00Z",
  };
}

function timeline(): RecordTimeline {
  return {
    record_id: 1,
    patient_id: 3,
    created_at: "2026-01-01T00:00:00Z",
    entries: [
      {
        entry_id: 11,
        entry_type: "consultation",
        payload: {},
        occurred_at: "2026-09-01T00:00:00Z",
        created_at: "2026-09-01T00:00:00Z",
      },
      {
        entry_id: 12,
        entry_type: "lab_report",
        payload: {},
        occurred_at: "2026-08-15T00:00:00Z",
        created_at: "2026-08-15T00:00:00Z",
      },
    ],
  };
}

function resolveLoaded() {
  getPre.mockResolvedValue(preSummary());
  getCases.mockResolvedValue([caseItem(11)]);
  getMe.mockResolvedValue(me());
  getHistory.mockResolvedValue(timeline());
}

beforeEach(() => {
  resolveLoaded();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  __resetLangForTests();
});

describe("ReviewWorkspacePage stage + forced review (US-13)", () => {
  it("renders the case stage chip for the pre-summary stage", async () => {
    render(<ReviewWorkspacePage params={{ intakeId: "42" }} />);
    await waitFor(() => screen.getByTestId("workspace-content"));

    expect(screen.getByTestId("stage-chip")).toHaveTextContent(
      consoleT.stagePreSummary,
    );
    expect(screen.getByTestId("stage-chip")).not.toHaveTextContent(
      consoleT.stagePrescriptionPending,
    );
  });

  it("shows the forced-review requirement on a low-confidence pre-summary", async () => {
    render(<ReviewWorkspacePage params={{ intakeId: "42" }} />);
    await waitFor(() => screen.getByTestId("workspace-content"));

    expect(screen.getByTestId("forced-review-banner")).toHaveTextContent(
      t.forcedReviewChip,
    );
    expect(screen.getByTestId("pre-summary-low-confidence")).toHaveTextContent(
      consoleT.verifyChip,
    );
  });

  it("does not show the forced-review banner on a high-confidence pre-summary", async () => {
    getPre.mockResolvedValue(preSummary({ low_confidence: false }));
    render(<ReviewWorkspacePage params={{ intakeId: "42" }} />);
    await waitFor(() => screen.getByTestId("workspace-content"));

    expect(
      screen.queryByTestId("forced-review-banner"),
    ).not.toBeInTheDocument();
  });
});

describe("ReviewWorkspacePage full pre-summary read (US-14)", () => {
  it("renders the chief complaints, symptoms, duration and confidence", async () => {
    render(<ReviewWorkspacePage params={{ intakeId: "42" }} />);
    await waitFor(() => screen.getByTestId("pre-summary"));

    expect(screen.getByTestId("pre-summary-complaints")).toHaveTextContent(
      "Fever",
    );
    expect(screen.getByTestId("pre-summary-symptoms")).toHaveTextContent(
      "Headache",
    );
    expect(screen.getByTestId("pre-summary-symptoms")).toHaveTextContent(
      "Chills",
    );
    expect(screen.getByTestId("pre-summary-duration")).toHaveTextContent(
      "3 days",
    );
    expect(screen.getByTestId("pre-summary-confidence")).toHaveTextContent(
      `${t.confidenceLabel} 44%`,
    );
  });

  it("shows a not-captured placeholder when duration is missing", async () => {
    getPre.mockResolvedValue(
      preSummary({
        structured_fields: {
          chief_complaints: ["Fever"],
          symptoms: [],
          duration: null,
        },
      }),
    );
    render(<ReviewWorkspacePage params={{ intakeId: "42" }} />);
    await waitFor(() => screen.getByTestId("pre-summary"));

    expect(screen.getByTestId("pre-summary-duration")).toHaveTextContent(
      t.durationNotSet,
    );
  });

  it("renders the draft review state with no attribution", async () => {
    render(<ReviewWorkspacePage params={{ intakeId: "42" }} />);
    await waitFor(() => screen.getByTestId("workspace-content"));

    expect(screen.getByTestId("pre-summary-review-state")).toHaveTextContent(
      t.reviewStateDraft,
    );
    expect(screen.getByTestId("pre-summary-attribution")).toHaveTextContent(
      t.notReviewedYet,
    );
  });

  it("shows a pre-finalized summary with attribution and reviewed timestamp", async () => {
    getPre.mockResolvedValue(
      preSummary({
        review_state: "final",
        review_attribution: "doctor",
        reviewed_by: 7,
        reviewed_at: "2026-09-16T09:00:00Z",
      }),
    );
    render(<ReviewWorkspacePage params={{ intakeId: "42" }} />);
    await waitFor(() => screen.getByTestId("pre-summary-attribution"));

    expect(screen.getByTestId("pre-summary-review-state")).toHaveTextContent(
      t.reviewStateFinal,
    );
    expect(screen.getByTestId("pre-summary-attribution")).toHaveTextContent(
      "doctor",
    );
  });
});

describe("ReviewWorkspacePage single-action finalize (US-14/#442)", () => {
  it("calls reviewPreSummary and shows the success state with attribution", async () => {
    doReview.mockResolvedValue(reviewResult());
    render(<ReviewWorkspacePage params={{ intakeId: "42" }} />);
    await waitFor(() => screen.getByTestId("finalize-action"));

    fireEvent.click(screen.getByTestId("finalize-action"));

    await waitFor(() =>
      expect(screen.getByTestId("finalize-success")).toBeTruthy(),
    );
    expect(doReview).toHaveBeenCalledWith(42);

    const state = screen.getByTestId("pre-summary-review-state");
    expect(state).toHaveTextContent(t.reviewStateFinal);
    expect(screen.getByTestId("pre-summary-attribution")).toHaveTextContent(
      "doctor",
    );
  });

  it("does not offer finalize once the summary is already final", async () => {
    getPre.mockResolvedValue(
      preSummary({
        review_state: "final",
        reviewed_by: 7,
        reviewed_at: "2026-09-16T09:00:00Z",
      }),
    );
    render(<ReviewWorkspacePage params={{ intakeId: "42" }} />);
    await waitFor(() => screen.getByTestId("workspace-content"));

    expect(screen.queryByTestId("finalize-action")).not.toBeInTheDocument();
  });

  it("surfaces a failure message when the review action errors", async () => {
    doReview.mockRejectedValue(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "t",
        details: {},
      }),
    );
    render(<ReviewWorkspacePage params={{ intakeId: "42" }} />);
    await waitFor(() => screen.getByTestId("finalize-action"));

    fireEvent.click(screen.getByTestId("finalize-action"));
    await waitFor(() => expect(screen.getByText(t.finalizeFail)).toBeTruthy());
    expect(screen.queryByTestId("finalize-success")).not.toBeInTheDocument();
  });
});

describe("ReviewWorkspacePage consented history", () => {
  it("reads the consented history for the matched care case patient", async () => {
    render(<ReviewWorkspacePage params={{ intakeId: "42" }} />);
    await waitFor(() => screen.getByTestId("history-list"));

    expect(getHistory).toHaveBeenCalledWith({
      patient_id: 3,
      scope: "consultations",
      counterparty_id: 7,
      counterparty_type: "doctor",
    });
    expect(screen.getAllByTestId("history-entry")).toHaveLength(2);
    expect(screen.getByText("Consultation")).toBeTruthy();
    expect(screen.getByText("Lab result")).toBeTruthy();
  });

  it("shows a denial-safe empty state when consent yields no history", async () => {
    getHistory.mockResolvedValue({
      record_id: 1,
      patient_id: 3,
      created_at: "2026-01-01T00:00:00Z",
      entries: [],
    });
    render(<ReviewWorkspacePage params={{ intakeId: "42" }} />);
    await waitFor(() => screen.getByText(t.historyEmpty));

    expect(screen.queryByTestId("history-list")).not.toBeInTheDocument();
  });

  it("shows a retryable error state when the history read fails", async () => {
    getHistory.mockRejectedValueOnce(
      new ApiError({
        code: "CONSENT_DENIED",
        message: "denied",
        trace_id: "t",
        details: {},
      }),
    );
    render(<ReviewWorkspacePage params={{ intakeId: "42" }} />);
    await waitFor(() => screen.getByTestId("history-error"));

    expect(screen.getByText(t.historyLoadFail)).toBeTruthy();

    getHistory.mockResolvedValue(timeline());
    fireEvent.click(screen.getByTestId("history-retry"));
    await waitFor(() => screen.getByTestId("history-list"));
  });
});

describe("ReviewWorkspacePage handshake (US-24)", () => {
  it("handshake is only offered once the review is final", async () => {
    render(<ReviewWorkspacePage params={{ intakeId: "42" }} />);
    await waitFor(() => screen.getByTestId("workspace-content"));

    expect(screen.queryByTestId("handshake-action")).not.toBeInTheDocument();
  });

  it("completes the consultation and moves the case to prescription pending", async () => {
    doReview.mockResolvedValue(reviewResult());
    doHandshake.mockResolvedValue(
      caseItem(11, { stage: "prescription_pending" }),
    );
    render(<ReviewWorkspacePage params={{ intakeId: "42" }} />);
    await waitFor(() => screen.getByTestId("finalize-action"));

    fireEvent.click(screen.getByTestId("finalize-action"));
    await waitFor(() => screen.getByTestId("handshake-action"));

    fireEvent.click(screen.getByTestId("handshake-action"));

    await waitFor(() =>
      expect(screen.getByTestId("handshake-success")).toBeTruthy(),
    );
    expect(doHandshake).toHaveBeenCalledWith(11);
    expect(screen.getByTestId("stage-chip")).toHaveTextContent(
      consoleT.stagePrescriptionPending,
    );
  });

  it("re-reads the case list after a queue-originated finalize so the handshake and history become reachable", async () => {
    // Queue path: at load no care case exists yet (the outbox consumer births
    // it on pre_summary.ready). The post-finalize re-read must pick it up.
    getCases.mockResolvedValueOnce([]);
    getCases.mockResolvedValueOnce([caseItem(11)]);
    doReview.mockResolvedValue(reviewResult());
    render(<ReviewWorkspacePage params={{ intakeId: "42" }} />);
    await waitFor(() => screen.getByTestId("workspace-content"));

    expect(screen.queryByTestId("workspace-handshake")).not.toBeInTheDocument();
    expect(screen.queryByTestId("workspace-history")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("finalize-action"));

    await waitFor(() => screen.getByTestId("handshake-action"));
    expect(screen.getByTestId("workspace-history")).toBeInTheDocument();
    expect(getCases.mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it("surfaces a failure message when the handshake errors", async () => {
    doReview.mockResolvedValue(reviewResult());
    doHandshake.mockRejectedValue(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "t",
        details: {},
      }),
    );
    render(<ReviewWorkspacePage params={{ intakeId: "42" }} />);
    await waitFor(() => screen.getByTestId("finalize-action"));
    fireEvent.click(screen.getByTestId("finalize-action"));
    await waitFor(() => screen.getByTestId("handshake-action"));

    fireEvent.click(screen.getByTestId("handshake-action"));
    await waitFor(() => expect(screen.getByText(t.handshakeFail)).toBeTruthy());
  });
});

describe("ReviewWorkspacePage failure paths", () => {
  it("shows a retryable error banner when the workspace feeds fail", async () => {
    getPre.mockRejectedValue(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "trace-rev001",
        details: {},
      }),
    );
    render(<ReviewWorkspacePage params={{ intakeId: "42" }} />);
    await waitFor(() => screen.getByTestId("error-banner"));

    expect(screen.getByText(t.loadFailed)).toBeTruthy();
  });

  it("retries the workspace feeds from the error state", async () => {
    getPre.mockRejectedValueOnce(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "t",
        details: {},
      }),
    );
    render(<ReviewWorkspacePage params={{ intakeId: "42" }} />);
    await waitFor(() => screen.getByTestId("error-banner"));

    fireEvent.click(screen.getByTestId("error-banner-retry"));
    await waitFor(() => screen.getByTestId("workspace-content"));
    expect(getPre).toHaveBeenCalledTimes(2);
  });
});

describe("ReviewWorkspacePage bilingual parity (REQ-006)", () => {
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
        <ReviewWorkspacePage params={{ intakeId: "42" }} />
      </>
    );
  }

  it("renders the workspace copy in Hindi when the locale flips", async () => {
    render(<LangFlipHost />);
    await waitFor(() => screen.getByTestId("workspace-content"));

    fireEvent.click(screen.getByText("flip-lang"));
    await waitFor(() =>
      expect(screen.getByTestId("stage-label")).toHaveTextContent(
        hiT.stageLabel,
      ),
    );

    expect(screen.getByText(hiT.title)).toBeInTheDocument();
    expect(screen.getByTestId("forced-review-banner")).toHaveTextContent(
      hiT.forcedReviewChip,
    );
    expect(screen.getByTestId("pre-summary")).toHaveTextContent(
      hiT.summaryHeading,
    );
  });
});
