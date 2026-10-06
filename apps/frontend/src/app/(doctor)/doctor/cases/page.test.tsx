// PHASE-8.1 T8 (#483): doctor console Cases index suite. Renders the doctor's
// open care cases, each linking into its case workspace (cases/[caseId], US-8),
// with stage chips, an empty state, a retryable failure banner, and bilingual
// EN/HI parity (REQ-006). Mirrors the landing page's open-cases section but
// stands alone as the Cases tab's live destination.
//
// #652 / FEAT-008: rows are the shared DoctorListCard - avatar initial, name,
// age, citable case id, shared stage-chip tone map, the amber Verify chip on a
// forced-review case, a last-updated line, one overlay link per card whose
// accessible name includes the patient (US-66/67), on a grid that is
// single-column below the large breakpoint (US-68). This suite stubs the
// client module wholesale (the page's own seam); the client's runtime guards
// against the real wire shape are exercised separately in
// lib/doctor/patients.contract.test.ts with only the network stubbed (#624).

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
import { listDoctorCases, type DoctorCaseRow } from "@/lib/doctor/api";
import type { DoctorCasesListView } from "@/lib/doctor/api";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { __resetLangForTests, useLang } from "@/lib/i18n/LangContext";

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

vi.mock("@/lib/doctor/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/doctor/api")>();
  return { ...mod, listDoctorCases: vi.fn() };
});

const t = STRINGS.en.doctorConsole;
const hiT = STRINGS.hi.doctorConsole;
const getCases = vi.mocked(listDoctorCases);

function caseItem(
  id: number,
  overrides: Partial<DoctorCaseRow> = {},
): DoctorCaseRow {
  return {
    case_id: id,
    stage: "prescription_pending",
    created_at: "2026-09-12T10:00:00Z",
    // Three hours back, so the relative line lands in a fixed bucket no
    // matter when the suite runs.
    updated_at: new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString(),
    patient_id: 3,
    patient_age: 45,
    patient_name: "Asha Verma",
    forced_review: false,
    has_photo: true,
    ...overrides,
  };
}

function casesView(...rows: DoctorCaseRow[]): DoctorCasesListView {
  return { items: rows };
}

beforeEach(() => {
  getCases.mockResolvedValue(casesView());
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  __resetLangForTests();
});

describe("DoctorCasesIndexPage", () => {
  it("renders the Cases index header", async () => {
    getCases.mockResolvedValue(casesView(caseItem(11)));
    render(<DoctorCasesIndexPage />);

    await waitFor(() => screen.getByTestId("cases-list"));

    expect(screen.getByText(t.casesIndexTitle)).toBeInTheDocument();
    expect(screen.getByText(t.casesIndexDescription)).toBeInTheDocument();
  });

  it("renders open care cases with their stage chips", async () => {
    getCases.mockResolvedValue(
      casesView(
        caseItem(11, { stage: "pre_summary" }),
        caseItem(12, { stage: "prescription_pending" }),
      ),
    );
    render(<DoctorCasesIndexPage />);

    await waitFor(() => screen.getByTestId("cases-list"));

    expect(screen.getByText("Case #11")).toBeTruthy();
    expect(screen.getByText("Case #12")).toBeTruthy();
    const stageChips = screen.getAllByTestId("case-item-stage");
    expect(stageChips[0]).toHaveTextContent(t.stagePreSummary);
    expect(stageChips[1]).toHaveTextContent(t.stagePrescriptionPending);
  });

  it("shows each patient's avatar initial, name, and age", async () => {
    getCases.mockResolvedValue(
      casesView(
        caseItem(11, { patient_name: "Asha Verma", patient_age: 45 }),
        caseItem(12, { patient_name: "Ravi Nair", patient_age: 31 }),
      ),
    );
    render(<DoctorCasesIndexPage />);

    await waitFor(() => screen.getByTestId("cases-list"));

    expect(screen.getAllByTestId("case-item-patient")[0]).toHaveTextContent(
      "Asha Verma",
    );
    expect(screen.getByText(t.patientAge(45))).toBeInTheDocument();
    expect(screen.getByText(t.patientAge(31))).toBeInTheDocument();
    const firstCard = screen.getAllByTestId("case-item")[0];
    expect(within(firstCard).getByText("A")).toBeInTheDocument();
    const secondCard = screen.getAllByTestId("case-item")[1];
    expect(within(secondCard).getByText("R")).toBeInTheDocument();
  });

  it("falls back to the patient word when the backend cannot name the patient", async () => {
    getCases.mockResolvedValue(
      casesView(caseItem(11, { patient_name: null, patient_age: null })),
    );
    render(<DoctorCasesIndexPage />);

    await waitFor(() => screen.getByTestId("cases-list"));

    expect(screen.getByTestId("case-item-patient")).toHaveTextContent(
      t.patientFallback,
    );
    expect(screen.queryByText(t.patientAge(45))).not.toBeInTheDocument();
  });

  it("deep-links each open case into its case workspace", async () => {
    getCases.mockResolvedValue(casesView(caseItem(11), caseItem(12)));
    render(<DoctorCasesIndexPage />);

    await waitFor(() => screen.getAllByTestId("case-item-open"));

    const links = screen.getAllByTestId("case-item-open");
    expect(links[0]).toHaveAttribute("href", "/doctor/cases/11");
    expect(links[1]).toHaveAttribute("href", "/doctor/cases/12");
  });

  it("makes each whole card one focus stop whose accessible name includes the patient", async () => {
    getCases.mockResolvedValue(
      casesView(
        caseItem(11, { patient_name: "Asha Verma" }),
        caseItem(12, { patient_name: "Ravi Nair" }),
      ),
    );
    render(<DoctorCasesIndexPage />);

    await waitFor(() => screen.getAllByTestId("case-item-open"));

    const links = screen.getAllByTestId("case-item-open");
    expect(links).toHaveLength(2);
    expect(links[0]).toHaveAccessibleName(t.caseCardA11y("Asha Verma"));
    expect(links[1]).toHaveAccessibleName(t.caseCardA11y("Ravi Nair"));
    // One focus stop per card: the overlay link is the only focusable thing
    // inside it - no separate "Open" button left to tab past (US-67).
    for (const card of screen.getAllByTestId("case-item")) {
      expect(within(card).getAllByRole("link")).toHaveLength(1);
      expect(within(card).queryByRole("button")).not.toBeInTheDocument();
    }
  });

  it("shows the amber Verify chip only on a forced-review case", async () => {
    getCases.mockResolvedValue(
      casesView(caseItem(11, { forced_review: true }), caseItem(12)),
    );
    render(<DoctorCasesIndexPage />);

    await waitFor(() => screen.getByTestId("cases-list"));

    const verifyChips = screen.getAllByTestId("case-item-verify");
    expect(verifyChips).toHaveLength(1);
    expect(verifyChips[0]).toHaveTextContent(t.verifyChip);
    expect(verifyChips[0].className).toContain("bg-warn-soft");
    expect(verifyChips[0].className).toContain("text-warn-text");
  });

  it("shows how long ago the case was last updated", async () => {
    getCases.mockResolvedValue(casesView(caseItem(11)));
    render(<DoctorCasesIndexPage />);

    await waitFor(() => screen.getByTestId("cases-list"));

    expect(screen.getByTestId("case-item-updated")).toHaveTextContent(
      t.caseUpdatedAgo(t.timeAgoHours(3)),
    );
  });

  it("renders the list as a grid that is single-column below the large breakpoint", async () => {
    getCases.mockResolvedValue(casesView(caseItem(11), caseItem(12)));
    render(<DoctorCasesIndexPage />);

    await waitFor(() => screen.getByTestId("cases-list"));

    const listClass = screen.getByTestId("cases-list").className;
    expect(listClass).toContain("grid");
    expect(listClass).toContain("grid-cols-1");
    expect(listClass).toContain("lg:grid-cols-2");
    for (const item of screen.getAllByTestId("case-item")) {
      expect(item.className).toContain("min-w-0");
    }
  });

  it("preserves every historical testid on the list surface", async () => {
    getCases.mockResolvedValue(casesView(caseItem(11)));
    render(<DoctorCasesIndexPage />);

    await waitFor(() => screen.getByTestId("cases-list"));

    for (const testId of [
      "cases-list-wrapper",
      "cases-list",
      "case-item",
      "case-item-id",
      "case-item-stage",
      "case-item-open",
    ]) {
      expect(screen.getByTestId(testId)).toBeInTheDocument();
    }
    expect(screen.getByTestId("case-item-id")).toHaveTextContent(
      t.caseItemMeta(11),
    );
  });

  it("shows a card-shaped skeleton while the cases load", async () => {
    getCases.mockReturnValue(
      new Promise<DoctorCasesListView>(() => {
        // Never settles: the skeleton is the page's state for the whole wait.
      }),
    );
    render(<DoctorCasesIndexPage />);

    const skeleton = await screen.findByTestId("cases-skeleton");
    const placeholders = within(skeleton).getAllByTestId("cases-skeleton-card");
    expect(placeholders.length).toBeGreaterThan(0);
    expect(screen.queryByTestId("cases-list")).not.toBeInTheDocument();
    expect(screen.queryByTestId("empty-state-wrapper")).not.toBeInTheDocument();
  });

  it("shows an empty state when there are no open cases", async () => {
    getCases.mockResolvedValue(casesView());
    render(<DoctorCasesIndexPage />);

    await waitFor(() => screen.getByTestId("empty-state"));

    expect(
      within(screen.getByTestId("empty-state")).getByText(t.casesEmpty),
    ).toBeTruthy();
    expect(screen.getByTestId("empty-state-wrapper")).toBeInTheDocument();
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
    expect(screen.getByTestId("error-banner-trace-id")).toHaveTextContent(
      "trace-cases-001",
    );
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

    getCases.mockResolvedValue(casesView(caseItem(11)));
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

    getCases.mockResolvedValue(
      casesView(caseItem(11, { forced_review: true })),
    );
    render(<LangFlipHost />);

    await waitFor(() => screen.getByTestId("case-item"));

    screen.getByText("flip-lang").click();
    await waitFor(() =>
      expect(screen.getByText(hiT.casesIndexTitle)).toBeInTheDocument(),
    );
    expect(screen.getByText(hiT.caseItemMeta(11))).toBeInTheDocument();
    // The card's own new copy ships in Hindi too: the chip, the link's
    // accessible name, and the relative line (typecheck already pins key
    // parity; this pins that the page actually renders them).
    expect(screen.getByTestId("case-item-verify")).toHaveTextContent(
      hiT.verifyChip,
    );
    expect(screen.getByTestId("case-item-open")).toHaveAccessibleName(
      hiT.caseCardA11y("Asha Verma"),
    );
    expect(screen.getByTestId("case-item-updated")).toHaveTextContent(
      hiT.caseUpdatedAgo(hiT.timeAgoHours(3)),
    );
  });
});
