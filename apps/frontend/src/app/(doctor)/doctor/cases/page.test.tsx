// PHASE-8.1 T8 (#483): doctor console Cases index suite. Renders the doctor's
// open care cases from the existing open-cases read, each linking into its
// case workspace (cases/[caseId], US-8), with stage chips, an empty state,
// a retryable failure banner, and bilingual EN/HI parity (REQ-006). Mirrors
// the landing page's open-cases section but stands alone as the Cases tab's
// live destination.

import {
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import DoctorCasesIndexPage from "./page";
import { ApiError } from "@/lib/api-errors";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { __resetLangForTests, useLang } from "@/lib/i18n/LangContext";
import {
  listOpenCases,
  type CareCaseStage,
  type CaseDetailView,
} from "@/lib/care/api";

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
  return { ...mod, listOpenCases: vi.fn() };
});

const t = STRINGS.en.doctorConsole;
const hiT = STRINGS.hi.doctorConsole;
const getCases = vi.mocked(listOpenCases);

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

beforeEach(() => {
  getCases.mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  __resetLangForTests();
});

describe("DoctorCasesIndexPage", () => {
  it("renders the Cases index header", async () => {
    getCases.mockResolvedValue([caseItem(11)]);
    render(<DoctorCasesIndexPage />);

    await waitFor(() => screen.getByTestId("cases-list"));

    expect(screen.getByText(t.casesIndexTitle)).toBeInTheDocument();
    expect(screen.getByText(t.casesIndexDescription)).toBeInTheDocument();
  });

  it("renders open care cases with their stage chips", async () => {
    getCases.mockResolvedValue([
      caseItem(11, { stage: "pre_summary" }),
      caseItem(12, { stage: "prescription_pending" }),
    ]);
    render(<DoctorCasesIndexPage />);

    await waitFor(() => screen.getByTestId("cases-list"));

    expect(screen.getByText("Case #11")).toBeTruthy();
    expect(screen.getByText("Case #12")).toBeTruthy();
    const stageChips = screen.getAllByTestId("case-item-stage");
    expect(stageChips[0]).toHaveTextContent(t.stagePreSummary);
    expect(stageChips[1]).toHaveTextContent(t.stagePrescriptionPending);
  });

  it("deep-links each open case into its case workspace", async () => {
    getCases.mockResolvedValue([caseItem(11), caseItem(12)]);
    render(<DoctorCasesIndexPage />);

    await waitFor(() => screen.getAllByTestId("case-item-open"));

    const links = screen.getAllByTestId("case-item-open");
    expect(links[0]).toHaveAttribute("href", "/doctor/cases/11");
    expect(links[1]).toHaveAttribute("href", "/doctor/cases/12");
  });

  it("shows an empty state when there are no open cases", async () => {
    getCases.mockResolvedValue([]);
    render(<DoctorCasesIndexPage />);

    await waitFor(() => screen.getByTestId("empty-state"));

    expect(
      within(screen.getByTestId("empty-state")).getByText(t.casesEmpty),
    ).toBeTruthy();
  });

  it("shows a retryable error banner when the cases feed fails", async () => {
    getCases.mockRejectedValue(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "trace-cases-001",
        details: {},
      }),
    );
    render(<DoctorCasesIndexPage />);

    await waitFor(() => screen.getByTestId("error-banner"));
    expect(screen.getByText(t.loadFailed)).toBeTruthy();
  });

  it("retries the cases feed from the error state", async () => {
    getCases.mockRejectedValueOnce(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "t",
        details: {},
      }),
    );
    render(<DoctorCasesIndexPage />);

    await waitFor(() => screen.getByTestId("error-banner"));

    getCases.mockResolvedValue([caseItem(11)]);
    const retry = screen.getByTestId("error-banner-retry");
    retry.click();

    await waitFor(() => screen.getByTestId("case-item"));
    expect(getCases).toHaveBeenCalledTimes(2);
  });

  it("renders in Hindi when the locale flips", async () => {
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
          <DoctorCasesIndexPage />
        </>
      );
    }

    getCases.mockResolvedValue([caseItem(11)]);
    render(<LangFlipHost />);

    await waitFor(() => screen.getByTestId("case-item"));

    screen.getByText("flip-lang").click();
    await waitFor(() =>
      expect(screen.getByText(hiT.casesIndexTitle)).toBeInTheDocument(),
    );
    expect(screen.getByText(hiT.caseItemMeta(11))).toBeInTheDocument();
  });
});
