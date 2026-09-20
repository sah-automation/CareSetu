// PHASE-8.1 T12 (#450): doctor console landing page suite. Covers the review
// queue (ranked low-confidence first with the amber Verify chip and a
// confidence flag, US-11/12), the open care-cases section with stage chips
// (US-15), the deep links into the workspace routes (review/[intakeId],
// cases/[caseId]) that #451-#453 fill, the coming-soon patients/profile tabs
// (US-26), the consultation-fee editor (blank until set, save + clear, US-25),
// load failure with retry, and bilingual EN/HI parity (REQ-006).

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import DoctorDashboardPage from "./page";
import { ApiError } from "@/lib/api-errors";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { __resetLangForTests, useLang } from "@/lib/i18n/LangContext";
import { fetchReviewQueue, type ReviewQueueItem } from "@/lib/intake/api";
import {
  listOpenCases,
  type CareCaseStage,
  type CaseDetailView,
} from "@/lib/care/api";
import { updateConsultationFee } from "@/lib/partner/api";

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
  return { ...mod, fetchReviewQueue: vi.fn() };
});

vi.mock("@/lib/care/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/care/api")>();
  return { ...mod, listOpenCases: vi.fn() };
});

vi.mock("@/lib/partner/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/partner/api")>();
  return { ...mod, updateConsultationFee: vi.fn() };
});

const t = STRINGS.en.doctorConsole;
const hiT = STRINGS.hi.doctorConsole;
const getQueue = vi.mocked(fetchReviewQueue);
const getCases = vi.mocked(listOpenCases);
const setFee = vi.mocked(updateConsultationFee);

function queueItem(overrides: Partial<ReviewQueueItem> = {}): ReviewQueueItem {
  return {
    pre_summary_id: 9,
    intake_id: 42,
    structuring_confidence: 0.54,
    low_confidence: true,
    review_state: "draft",
    patient_name: "Ravi Kumar",
    patient_age: 32,
    snippet: "Fever for three days, cough",
    section_count: 2,
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
    stage: (stage ?? "prescription_pending") as CareCaseStage,
    forced_review: false,
    has_doctor_input: false,
    closed_at: null,
    close_reason: null,
    created_at: "2026-09-12T10:00:00Z",
    updated_at: "2026-09-12T10:00:00Z",
    ...rest,
  };
}

function resolveLoaded() {
  getQueue.mockResolvedValue([]);
  getCases.mockResolvedValue([]);
}

beforeEach(() => {
  resolveLoaded();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  __resetLangForTests();
});

describe("DoctorDashboardPage review queue", () => {
  it("ranks low-confidence items first even when the API returns them last (US-11/12)", async () => {
    getQueue.mockResolvedValue([
      queueItem({
        pre_summary_id: 1,
        intake_id: 1,
        patient_name: "Asha",
        structuring_confidence: 0.91,
        low_confidence: false,
        created_at: "2026-09-10T09:00:00Z",
      }),
      queueItem({
        pre_summary_id: 2,
        intake_id: 2,
        patient_name: "Ravi",
        structuring_confidence: 0.44,
        low_confidence: true,
        created_at: "2026-09-10T11:00:00Z",
      }),
    ]);
    render(<DoctorDashboardPage />);

    await waitFor(() => screen.getByTestId("queue-list"));

    const titles = screen.getAllByTestId("queue-item-title");
    expect(titles[0]).toHaveTextContent("Ravi");
    expect(titles[1]).toHaveTextContent("Asha");
  });

  it("renders the triage-ready card: patient name/age, snippet, and section pill (#489)", async () => {
    getQueue.mockResolvedValue([queueItem()]);
    render(<DoctorDashboardPage />);

    await waitFor(() => screen.getByTestId("queue-item"));

    expect(screen.getByTestId("queue-item-title")).toHaveTextContent(
      "Ravi Kumar",
    );
    expect(screen.getByTestId("queue-item-age")).toHaveTextContent(
      t.patientAge(32),
    );
    expect(screen.getByTestId("queue-item-snippet")).toHaveTextContent(
      "Fever for three days, cough",
    );
    expect(screen.getByTestId("queue-item-sections")).toHaveTextContent(
      t.sectionsCount(2),
    );
    expect(screen.getByTestId("queue-item-intake")).toHaveTextContent(
      t.queueItemMeta(42),
    );
    expect(screen.getByTestId("queue-item-waiting")).toHaveTextContent(
      t.waitingFor(""),
    );
  });

  it("falls back to the patient label when the profile is missing (#489)", async () => {
    getQueue.mockResolvedValue([
      queueItem({
        patient_name: null,
        patient_age: null,
        snippet: null,
        section_count: 0,
      }),
    ]);
    render(<DoctorDashboardPage />);

    await waitFor(() => screen.getByTestId("queue-item"));

    expect(screen.getByTestId("queue-item-title")).toHaveTextContent(
      t.patientFallback,
    );
    expect(screen.queryByTestId("queue-item-age")).not.toBeInTheDocument();
    expect(screen.queryByTestId("queue-item-snippet")).not.toBeInTheDocument();
    expect(screen.getByTestId("queue-item-sections")).toHaveTextContent(
      t.sectionsCount(0),
    );
  });

  it("shows the amber Verify chip and confidence flag on low-confidence items", async () => {
    getQueue.mockResolvedValue([queueItem()]);
    render(<DoctorDashboardPage />);

    await waitFor(() => screen.getByTestId("queue-item"));

    expect(screen.getByTestId("queue-item-verify")).toHaveTextContent(
      t.verifyChip,
    );
    expect(screen.getByTestId("queue-item-confidence")).toHaveTextContent(
      `${t.confidenceLabel}: 54%`,
    );
  });

  it("does not show the Verify chip on a clean pre-summary", async () => {
    getQueue.mockResolvedValue([queueItem({ low_confidence: false })]);
    render(<DoctorDashboardPage />);

    await waitFor(() => screen.getByTestId("queue-item"));
    expect(screen.queryByTestId("queue-item-verify")).not.toBeInTheDocument();
  });

  it("deep-links each queue item into the review workspace (US-11/13)", async () => {
    getQueue.mockResolvedValue([queueItem({ intake_id: 42 })]);
    render(<DoctorDashboardPage />);

    await waitFor(() => screen.getByTestId("queue-item-review"));

    expect(screen.getByTestId("queue-item-review")).toHaveAttribute(
      "href",
      "/doctor/review/42",
    );
  });

  it("shows an empty state when nothing needs review", async () => {
    getCases.mockResolvedValue([caseItem(11)]);
    render(<DoctorDashboardPage />);
    await waitFor(() =>
      within(screen.getByTestId("review-queue")).getByTestId("empty-state"),
    );
    expect(
      within(screen.getByTestId("review-queue")).getByText(t.queueEmpty),
    ).toBeTruthy();
  });
});

describe("DoctorDashboardPage open cases", () => {
  it("renders open care cases with their stage chips (US-15)", async () => {
    getCases.mockResolvedValue([
      caseItem(11, { stage: "pre_summary" }),
      caseItem(12, { stage: "prescription_pending" }),
    ]);
    render(<DoctorDashboardPage />);

    await waitFor(() => screen.getByTestId("cases-list"));

    expect(screen.getByText("Case #11")).toBeTruthy();
    expect(screen.getByText("Case #12")).toBeTruthy();
    const stageChips = screen.getAllByTestId("case-item-stage");
    expect(stageChips[0]).toHaveTextContent(t.stagePreSummary);
    expect(stageChips[1]).toHaveTextContent(t.stagePrescriptionPending);
  });

  it("deep-links each open case into the case workspace", async () => {
    getCases.mockResolvedValue([caseItem(11)]);
    render(<DoctorDashboardPage />);

    await waitFor(() => screen.getByTestId("case-item-open"));
    expect(screen.getByTestId("case-item-open")).toHaveAttribute(
      "href",
      "/doctor/cases/11",
    );
  });

  it("shows an empty state when there are no open cases", async () => {
    getQueue.mockResolvedValue([queueItem()]);
    render(<DoctorDashboardPage />);
    await waitFor(() =>
      within(screen.getByTestId("open-cases")).getByTestId("empty-state"),
    );
    expect(
      within(screen.getByTestId("open-cases")).getByText(t.casesEmpty),
    ).toBeTruthy();
  });
});

describe("DoctorDashboardPage fee editor (US-25)", () => {
  it("starts blank until the doctor sets a fee", () => {
    render(<DoctorDashboardPage />);
    const input = screen.getByTestId("fee-input") as HTMLInputElement;
    expect(input.value).toBe("");
    expect(screen.queryByTestId("fee-current")).not.toBeInTheDocument();
  });

  it("saves the fee in paise and shows the saved value", async () => {
    setFee.mockResolvedValue({
      partner_id: 7,
      status: "Active",
      round: 0,
    });
    render(<DoctorDashboardPage />);

    const input = screen.getByTestId("fee-input");
    fireEvent.change(input, { target: { value: "400" } });
    fireEvent.click(screen.getByTestId("fee-save"));

    await waitFor(() =>
      expect(screen.getByTestId("fee-message")).toHaveTextContent(t.feeSaved),
    );
    expect(setFee).toHaveBeenCalledWith(40000);
    expect(screen.getByTestId("fee-current")).toHaveTextContent("\u20B9400");
  });

  it("clears the fee back to unset", async () => {
    setFee.mockResolvedValue({
      partner_id: 7,
      status: "Active",
      round: 0,
    });
    render(<DoctorDashboardPage />);

    const input = screen.getByTestId("fee-input");
    fireEvent.change(input, { target: { value: "400" } });
    fireEvent.click(screen.getByTestId("fee-save"));
    await waitFor(() => screen.getByTestId("fee-current"));

    fireEvent.click(screen.getByTestId("fee-clear"));
    await waitFor(() =>
      expect(screen.getByTestId("fee-message")).toHaveTextContent(t.feeSaved),
    );
    expect(setFee).toHaveBeenCalledWith(null);
    expect(screen.queryByTestId("fee-current")).not.toBeInTheDocument();
    expect((screen.getByTestId("fee-input") as HTMLInputElement).value).toBe(
      "",
    );
  });

  it("surfaces the save-failed message on a backend error", async () => {
    setFee.mockRejectedValue(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "t",
        details: {},
      }),
    );
    render(<DoctorDashboardPage />);

    const input = screen.getByTestId("fee-input");
    fireEvent.change(input, { target: { value: "400" } });
    fireEvent.click(screen.getByTestId("fee-save"));

    await waitFor(() =>
      expect(screen.getByTestId("fee-message")).toHaveTextContent(
        t.feeSaveFailed,
      ),
    );
  });
});

describe("DoctorDashboardPage coming-soon tabs (US-26)", () => {
  it("renders Patients and Profile as coming-soon, not broken links", async () => {
    render(<DoctorDashboardPage />);
    await waitFor(() => screen.getByTestId("coming-soon-patients"));

    expect(screen.getByTestId("coming-soon-patients")).toHaveTextContent(
      t.patientsComingSoon,
    );
    expect(screen.getByTestId("coming-soon-profile")).toHaveTextContent(
      t.profileComingSoon,
    );
    expect(screen.getByTestId("coming-soon-patients")).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    expect(screen.getByTestId("coming-soon-profile")).toHaveAttribute(
      "aria-disabled",
      "true",
    );
  });
});

describe("DoctorDashboardPage failure paths", () => {
  it("shows a retryable error banner when the feeds fail", async () => {
    getQueue.mockRejectedValue(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "trace-st999001",
        details: {},
      }),
    );
    render(<DoctorDashboardPage />);
    await waitFor(() => screen.getByTestId("error-banner"));
    expect(screen.getByText(t.loadFailed)).toBeTruthy();
  });

  it("retries both feeds from the error state", async () => {
    getQueue.mockRejectedValueOnce(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "t",
        details: {},
      }),
    );
    render(<DoctorDashboardPage />);
    await waitFor(() => screen.getByTestId("error-banner"));

    getQueue.mockResolvedValue([queueItem()]);
    getCases.mockResolvedValue([caseItem(11)]);

    fireEvent.click(screen.getByTestId("error-banner-retry"));
    await waitFor(() => screen.getByTestId("queue-item"));
    expect(getQueue).toHaveBeenCalledTimes(2);
  });
});

describe("DoctorDashboardPage bilingual parity (REQ-006)", () => {
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
        <DoctorDashboardPage />
      </>
    );
  }

  it("renders the console copy in Hindi when the locale flips", async () => {
    getQueue.mockResolvedValue([queueItem({ patient_name: null })]);
    getCases.mockResolvedValue([caseItem(11)]);
    render(<LangFlipHost />);
    await waitFor(() => screen.getByTestId("queue-item"));

    fireEvent.click(screen.getByText("flip-lang"));
    await waitFor(() =>
      expect(screen.getByTestId("queue-item-title")).toHaveTextContent(
        hiT.patientFallback,
      ),
    );
    expect(screen.getByTestId("queue-item-intake")).toHaveTextContent(
      hiT.queueItemMeta(42),
    );
    expect(screen.getByText(hiT.title)).toBeInTheDocument();
    expect(screen.getByTestId("coming-soon-patients")).toHaveTextContent(
      hiT.patientsComingSoon,
    );
  });
});
