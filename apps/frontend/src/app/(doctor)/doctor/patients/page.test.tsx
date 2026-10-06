// PHASE-8.1 (#541): doctor console Patients index suite (FEAT-008, MOD-012).
// Renders the derived Current/Past patient groups from the consent-gated list
// API (#539), with granted-scope badges and latest-case-stage chips, a light
// name search/filter, deep links into the per-patient detail view,
// empty/loading/error states, and bilingual EN/HI parity (REQ-006). Mirrors
// the Cases index suite (#483). #651: rows are the shared DoctorListCard -
// card grid per bucket, worded no-open-case state, patient-bearing accessible
// name, single focus stop.

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

import DoctorPatientsIndexPage from "./page";
import { ApiError } from "@/lib/api-errors";
import { listDoctorPatients, type DoctorPatientRow } from "@/lib/doctor/api";
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
  return { ...mod, listDoctorPatients: vi.fn() };
});

const t = STRINGS.en.doctorPatients;
const consoleT = STRINGS.en.doctorConsole;
const hiT = STRINGS.hi.doctorPatients;
const getPatients = vi.mocked(listDoctorPatients);

function row(
  id: number,
  overrides: Partial<DoctorPatientRow> = {},
): DoctorPatientRow {
  return {
    patient_id: id,
    name: `Patient ${id}`,
    age: 40,
    has_photo: false,
    bucket: "current",
    granted_scopes: ["consultations", "prescriptions"],
    latest_case_stage: "pre_summary",
    ...overrides,
  };
}

beforeEach(() => {
  getPatients.mockResolvedValue({ items: [], total: 0 });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  __resetLangForTests();
});

describe("DoctorPatientsIndexPage", () => {
  it("renders the Patients index header", async () => {
    getPatients.mockResolvedValue({
      items: [row(11), row(12, { bucket: "past" })],
      total: 2,
    });
    render(<DoctorPatientsIndexPage />);

    await waitFor(() => screen.getByTestId("patient-group-current"));

    expect(screen.getByText(t.title)).toBeInTheDocument();
    expect(screen.getByText(t.description)).toBeInTheDocument();
  });

  it("groups rows into Current and Past with scope badges + stage chips", async () => {
    getPatients.mockResolvedValue({
      items: [
        row(11, {
          name: "Asha Devi",
          granted_scopes: ["consultations", "full_record"],
          latest_case_stage: "pre_summary",
        }),
        row(12, {
          name: "Ravi Kumar",
          bucket: "past",
          granted_scopes: ["prescriptions"],
          latest_case_stage: "closed",
        }),
      ],
      total: 2,
    });
    render(<DoctorPatientsIndexPage />);

    await waitFor(() => screen.getByTestId("patient-list-current"));

    expect(screen.getByTestId("patient-group-current")).toBeInTheDocument();
    expect(screen.getByTestId("patient-group-past")).toBeInTheDocument();

    const currentList = within(screen.getByTestId("patient-list-current"));
    const pastList = within(screen.getByTestId("patient-list-past"));
    expect(currentList.getByText("Asha Devi")).toBeInTheDocument();
    expect(pastList.getByText("Ravi Kumar")).toBeInTheDocument();

    // Granted-scope badges per row.
    expect(
      screen.getByTestId("patient-row-scope-consultations"),
    ).toHaveTextContent(t.scopeBadge.consultations);
    expect(
      screen.getByTestId("patient-row-scope-full_record"),
    ).toHaveTextContent(t.scopeBadge.full_record);
    expect(
      screen.getByTestId("patient-row-scope-prescriptions"),
    ).toHaveTextContent(t.scopeBadge.prescriptions);

    // Latest case stage chips (labels from the doctorConsole block), each on
    // the shared map's tone so a stage reads the same as on the cases list.
    const stageChips = screen.getAllByTestId("patient-row-stage");
    expect(stageChips[0]).toHaveTextContent(consoleT.stagePreSummary);
    expect(stageChips[0].className).toContain("bg-warn-soft");
    expect(stageChips[1]).toHaveTextContent(consoleT.stageClosed);
    expect(stageChips[1].className).toContain("bg-hairline-soft");
  });

  it("shows the age in the row meta", async () => {
    getPatients.mockResolvedValue({
      items: [row(11, { age: 45 })],
      total: 1,
    });
    render(<DoctorPatientsIndexPage />);

    await waitFor(() => screen.getByTestId("patient-list-current"));
    expect(screen.getByText(consoleT.patientAge(45))).toBeInTheDocument();
  });

  it("deep-links each patient row into the detail view", async () => {
    getPatients.mockResolvedValue({
      items: [row(11), row(12, { bucket: "past" })],
      total: 2,
    });
    render(<DoctorPatientsIndexPage />);

    await waitFor(() => screen.getAllByTestId("patient-row-open"));

    const links = screen.getAllByTestId("patient-row-open");
    expect(links[0]).toHaveAttribute("href", "/doctor/patients/11");
    expect(links[1]).toHaveAttribute("href", "/doctor/patients/12");
  });

  it("filters rows by name through the search box", async () => {
    getPatients.mockResolvedValue({
      items: [row(11, { name: "Asha Devi" }), row(12, { name: "Ravi Kumar" })],
      total: 2,
    });
    render(<DoctorPatientsIndexPage />);

    await waitFor(() => screen.getByTestId("patient-list-current"));

    fireEvent.change(screen.getByTestId("patient-search"), {
      target: { value: "asha" },
    });

    expect(screen.getByText("Asha Devi")).toBeInTheDocument();
    expect(screen.queryByText("Ravi Kumar")).not.toBeInTheDocument();
  });

  it("shows a no-results state when the search matches nothing", async () => {
    getPatients.mockResolvedValue({
      items: [row(11, { name: "Asha Devi" })],
      total: 1,
    });
    render(<DoctorPatientsIndexPage />);

    await waitFor(() => screen.getByTestId("patient-list-current"));

    fireEvent.change(screen.getByTestId("patient-search"), {
      target: { value: "zzz" },
    });

    expect(screen.getByText(t.noResultsTitle)).toBeInTheDocument();
    expect(screen.getByText(t.noResultsBody)).toBeInTheDocument();
  });

  it("shows the page empty state when there are no patients at all", async () => {
    getPatients.mockResolvedValue({ items: [], total: 0 });
    render(<DoctorPatientsIndexPage />);

    await waitFor(() => screen.getByTestId("empty-state"));
    expect(screen.getByText(t.patientsEmpty)).toBeInTheDocument();
  });

  it("shows per-bucket empty states when one group is missing", async () => {
    getPatients.mockResolvedValue({
      items: [row(12, { bucket: "past" })],
      total: 1,
    });
    render(<DoctorPatientsIndexPage />);

    await waitFor(() => screen.getByTestId("patient-group-current"));

    const currentEmpty = within(
      screen.getByTestId("patient-group-current"),
    ).getByTestId("empty-state");
    expect(within(currentEmpty).getByText(t.currentEmpty)).toBeInTheDocument();
    expect(
      within(screen.getByTestId("patient-list-past")).getByText("Patient 12"),
    ).toBeInTheDocument();
  });

  it("shows a retryable error banner when the patients feed fails", async () => {
    getPatients.mockRejectedValue(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "trace-patients-001",
        details: {},
      }),
    );
    render(<DoctorPatientsIndexPage />);

    await waitFor(() => screen.getByTestId("error-banner"));
    expect(screen.getByText(t.loadFailed)).toBeInTheDocument();
  });

  it("retries the patients feed from the error state", async () => {
    getPatients.mockRejectedValueOnce(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "t",
        details: {},
      }),
    );
    render(<DoctorPatientsIndexPage />);

    await waitFor(() => screen.getByTestId("error-banner"));

    getPatients.mockResolvedValue({ items: [row(11)], total: 1 });
    screen.getByTestId("error-banner-retry").click();

    await waitFor(() => screen.getByTestId("patient-row"));
    expect(getPatients).toHaveBeenCalledTimes(2);
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
          <DoctorPatientsIndexPage />
        </>
      );
    }

    getPatients.mockResolvedValue({ items: [row(11)], total: 1 });
    render(<LangFlipHost />);

    await waitFor(() => screen.getByTestId("patient-row"));

    screen.getByText("flip-lang").click();
    await waitFor(() =>
      expect(screen.getByText(hiT.title)).toBeInTheDocument(),
    );
    expect(screen.getByText(hiT.scopeBadge.consultations)).toBeInTheDocument();
    expect(
      screen.getByLabelText(hiT.openPatientNamed("Patient 11")),
    ).toBeInTheDocument();
  });

  // FEAT-008 / #651 AC-3: cards per bucket on a grid that is multi-column at
  // the large breakpoint and single-column below. No horizontal scroll rests
  // on the blueprint's mechanism - every grid child keeps min-width:0, so
  // intrinsic widths can never push the page wider than the viewport.
  it("renders each bucket as a card grid that is single-column below the large breakpoint", async () => {
    getPatients.mockResolvedValue({
      items: [row(11), row(12, { bucket: "past" })],
      total: 2,
    });
    render(<DoctorPatientsIndexPage />);

    await waitFor(() => screen.getByTestId("patient-list-current"));

    for (const testId of ["patient-list-current", "patient-list-past"]) {
      const listClass = screen.getByTestId(testId).className;
      expect(listClass).toContain("grid");
      expect(listClass).toContain("grid-cols-1");
      expect(listClass).toContain("lg:grid-cols-2");
    }
    for (const rowEl of screen.getAllByTestId("patient-row")) {
      expect(rowEl.className).toContain("min-w-0");
    }
    expect(screen.getAllByTestId("patient-row").length).toBe(2);
  });

  // FEAT-008 / #651 AC-6 (US-18): an absent stage reads as words, never as an
  // empty chip that could be mistaken for an unknown stage.
  it("says in words when a patient has no open case instead of an empty chip", async () => {
    getPatients.mockResolvedValue({
      items: [row(11, { latest_case_stage: null })],
      total: 1,
    });
    render(<DoctorPatientsIndexPage />);

    await waitFor(() => screen.getByTestId("patient-row-stage"));

    const stage = screen.getByTestId("patient-row-stage");
    expect(stage).toHaveTextContent(t.noCaseStage);
    expect(stage.textContent?.trim()).not.toBe("");
  });

  // FEAT-008 / #651 AC-1/AC-2: one whole-card link per row, its accessible
  // name carrying the patient (US-66), so a list of cards is one stop each.
  it("carries the patient in each card link's accessible name as one focus stop", async () => {
    getPatients.mockResolvedValue({
      items: [row(11, { name: "Asha Devi" })],
      total: 1,
    });
    render(<DoctorPatientsIndexPage />);

    await waitFor(() => screen.getByTestId("patient-row-open"));

    expect(screen.getByTestId("patient-row-open")).toHaveAttribute(
      "aria-label",
      t.openPatientNamed("Asha Devi"),
    );
    const cardRoot = screen.getByTestId("patient-row");
    const focusables = cardRoot.querySelectorAll(
      "a[href], button, input, select, textarea, [tabindex]",
    );
    expect(focusables).toHaveLength(1);
  });
});
