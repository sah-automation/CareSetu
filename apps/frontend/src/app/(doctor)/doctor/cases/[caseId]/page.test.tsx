// PHASE-8.1 T13 (#451): case workspace route (/doctor/cases/[caseId]) suite.
// Covers: the stage chip for open stages (US-15), the forced-review
// requirement when the case demands one, the consented health history, the
// consult-complete handshake for pre_summary-stage cases (US-24), the closed
// terminal state, load failure with retry, and bilingual EN/HI parity
// (REQ-006). Prescription drafting/approval stages are out of scope (#452/453).

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import CaseWorkspacePage from "./page";
import { ApiError } from "@/lib/api-errors";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { __resetLangForTests, useLang } from "@/lib/i18n/LangContext";
import {
  fetchCareCase,
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

vi.mock("@/lib/care/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/care/api")>();
  return { ...mod, fetchCareCase: vi.fn(), markConsultComplete: vi.fn() };
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
const getCase = vi.mocked(fetchCareCase);
const doHandshake = vi.mocked(markConsultComplete);
const getMe = vi.mocked(fetchPartnerMe);
const getHistory = vi.mocked(readConsentedHistory);

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

function timeline(): RecordTimeline {
  return {
    record_id: 1,
    patient_id: 3,
    created_at: "2026-01-01T00:00:00Z",
    entries: [
      {
        entry_id: 11,
        entry_type: "prescription",
        payload: {},
        occurred_at: "2026-09-01T00:00:00Z",
        created_at: "2026-09-01T00:00:00Z",
      },
    ],
  };
}

function resolveLoaded() {
  getCase.mockResolvedValue(caseItem(11));
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

describe("CaseWorkspacePage stage + forced review (US-15)", () => {
  it("renders the case stage chip for the pre-summary stage", async () => {
    render(<CaseWorkspacePage params={{ caseId: "11" }} />);
    await waitFor(() => screen.getByTestId("case-content"));

    expect(screen.getByTestId("stage-chip")).toHaveTextContent(
      consoleT.stagePreSummary,
    );
  });

  it("renders the prescription-pending stage chip", async () => {
    getCase.mockResolvedValue(caseItem(11, { stage: "prescription_pending" }));
    render(<CaseWorkspacePage params={{ caseId: "11" }} />);
    await waitFor(() => screen.getByTestId("case-content"));

    expect(screen.getByTestId("stage-chip")).toHaveTextContent(
      consoleT.stagePrescriptionPending,
    );
  });

  it("shows the forced-review requirement when the case demands one", async () => {
    getCase.mockResolvedValue(caseItem(11, { forced_review: true }));
    render(<CaseWorkspacePage params={{ caseId: "11" }} />);
    await waitFor(() => screen.getByTestId("case-content"));

    expect(screen.getByTestId("forced-review-banner")).toHaveTextContent(
      t.forcedReviewChip,
    );
  });

  it("omits the forced-review banner when review is not required", async () => {
    render(<CaseWorkspacePage params={{ caseId: "11" }} />);
    await waitFor(() => screen.getByTestId("case-content"));

    expect(
      screen.queryByTestId("forced-review-banner"),
    ).not.toBeInTheDocument();
  });
});

describe("CaseWorkspacePage consented history", () => {
  it("reads the consented history for the case patient", async () => {
    render(<CaseWorkspacePage params={{ caseId: "11" }} />);
    await waitFor(() => screen.getByTestId("history-list"));

    expect(getHistory).toHaveBeenCalledWith({
      patient_id: 3,
      scope: "consultations",
      counterparty_id: 7,
      counterparty_type: "doctor",
    });
    expect(screen.getByText("Prescription")).toBeTruthy();
  });

  it("shows a denial-safe empty state when consent yields no history", async () => {
    getHistory.mockResolvedValue({
      record_id: 1,
      patient_id: 3,
      created_at: "2026-01-01T00:00:00Z",
      entries: [],
    });
    render(<CaseWorkspacePage params={{ caseId: "11" }} />);
    await waitFor(() => screen.getByText(t.historyEmpty));

    expect(screen.queryByTestId("history-list")).not.toBeInTheDocument();
  });
});

describe("CaseWorkspacePage handshake (US-24)", () => {
  it("completes the consultation and moves the case to prescription pending", async () => {
    doHandshake.mockResolvedValue(
      caseItem(11, { stage: "prescription_pending" }),
    );
    render(<CaseWorkspacePage params={{ caseId: "11" }} />);
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

  it("does not offer the handshake on a prescription-pending case", async () => {
    getCase.mockResolvedValue(caseItem(11, { stage: "prescription_pending" }));
    render(<CaseWorkspacePage params={{ caseId: "11" }} />);
    await waitFor(() => screen.getByTestId("case-content"));

    expect(screen.queryByTestId("handshake-action")).not.toBeInTheDocument();
    expect(screen.getByTestId("handshake-success")).toBeTruthy();
  });

  it("shows the closed terminal state without actions", async () => {
    getCase.mockResolvedValue(caseItem(11, { stage: "closed" }));
    render(<CaseWorkspacePage params={{ caseId: "11" }} />);
    await waitFor(() => screen.getByTestId("closed-state"));

    expect(screen.getByTestId("closed-state")).toHaveTextContent(
      consoleT.stageClosed,
    );
    expect(screen.queryByTestId("handshake-action")).not.toBeInTheDocument();
  });

  it("surfaces a failure message when the handshake errors", async () => {
    doHandshake.mockRejectedValue(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "t",
        details: {},
      }),
    );
    render(<CaseWorkspacePage params={{ caseId: "11" }} />);
    await waitFor(() => screen.getByTestId("handshake-action"));

    fireEvent.click(screen.getByTestId("handshake-action"));
    await waitFor(() => expect(screen.getByText(t.handshakeFail)).toBeTruthy());
  });
});

describe("CaseWorkspacePage failure paths", () => {
  it("shows a retryable error banner when the case fails to load", async () => {
    getCase.mockRejectedValue(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "trace-case001",
        details: {},
      }),
    );
    render(<CaseWorkspacePage params={{ caseId: "11" }} />);
    await waitFor(() => screen.getByTestId("error-banner"));

    expect(screen.getByText(t.loadFailed)).toBeTruthy();
  });

  it("retries the case load from the error state", async () => {
    getCase.mockRejectedValueOnce(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "t",
        details: {},
      }),
    );
    render(<CaseWorkspacePage params={{ caseId: "11" }} />);
    await waitFor(() => screen.getByTestId("error-banner"));

    fireEvent.click(screen.getByTestId("error-banner-retry"));
    await waitFor(() => screen.getByTestId("case-content"));
    expect(getCase).toHaveBeenCalledTimes(2);
  });
});

describe("CaseWorkspacePage bilingual parity (REQ-006)", () => {
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
        <CaseWorkspacePage params={{ caseId: "11" }} />
      </>
    );
  }

  it("renders the workspace copy in Hindi when the locale flips", async () => {
    render(<LangFlipHost />);
    await waitFor(() => screen.getByTestId("case-content"));

    fireEvent.click(screen.getByText("flip-lang"));
    await waitFor(() =>
      expect(screen.getByTestId("stage-label")).toHaveTextContent(
        hiT.stageLabel,
      ),
    );

    expect(screen.getByText(hiT.title)).toBeInTheDocument();
    expect(screen.getByTestId("case-history")).toHaveTextContent(
      hiT.historyHeading,
    );
  });
});
