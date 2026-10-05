// PHASE-8.1 (#541): doctor console patient detail suite. The section-gated
// read renders exactly what the gated detail API (#540) answers: contact with
// the streamed photo, consultation history, health background under their
// live grants, the case workspace deep link, and a calm locked "not shared"
// state for ungranted sections (never an error). Covers load/error/retry,
// photo degrade, and bilingual EN/HI parity (REQ-006).

import {
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import DoctorPatientDetailPage from "./page";
import { ApiError } from "@/lib/api-errors";
import { useParams } from "next/navigation";
import {
  fetchDoctorPatientDetail,
  fetchDoctorPatientPhoto,
  type DoctorPatientDetailView,
} from "@/lib/doctor/api";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { __resetLangForTests, useLang } from "@/lib/i18n/LangContext";
import type { RecordTimeline } from "@/lib/record/api";

vi.mock("next/navigation", () => ({
  useParams: vi.fn(() => ({ patientId: "11" })),
}));

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
  return {
    ...mod,
    fetchDoctorPatientDetail: vi.fn(),
    fetchDoctorPatientPhoto: vi.fn(),
  };
});

const t = STRINGS.en.doctorPatients;
const consoleT = STRINGS.en.doctorConsole;
const recordT = STRINGS.en.record;
const hiT = STRINGS.hi.doctorPatients;
const getDetail = vi.mocked(fetchDoctorPatientDetail);
const getPhoto = vi.mocked(fetchDoctorPatientPhoto);

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
        entry_type: "prescription",
        payload: {},
        occurred_at: "2026-08-20T00:00:00Z",
        created_at: "2026-08-20T00:00:00Z",
      },
    ],
  };
}

function healthBackground() {
  return {
    set: true,
    acknowledged: true,
    background: {
      blood_group: "B+",
      conditions: ["Hypertension"],
      allergies: [],
      medications: ["Amlodipine"],
      immunizations: [],
      family_history: [],
    },
  };
}

function detail(
  overrides: Partial<DoctorPatientDetailView> = {},
): DoctorPatientDetailView {
  return {
    patient_id: 11,
    bucket: "current",
    granted_scopes: ["consultations", "health_background"],
    latest_case_stage: "pre_summary",
    case_workspace: { case_id: 31, stage: "pre_summary" },
    contact: {
      name: "Asha Devi",
      age: 40,
      gender: "female",
      area: "Daltonganj",
      emergency_contact: "+911234567890",
      has_photo: true,
    },
    consultation_history: timeline(),
    health_background: healthBackground(),
    ...overrides,
  };
}

beforeEach(() => {
  getDetail.mockResolvedValue(detail());
  getPhoto.mockRejectedValue(new Error("photo unavailable"));
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  __resetLangForTests();
});

describe("DoctorPatientDetailPage", () => {
  it("renders the contact section with the patient's profile fields", async () => {
    render(<DoctorPatientDetailPage />);

    await waitFor(() => screen.getByTestId("detail-contact"));

    // The name appears once in the page heading and once in the contact card.
    expect(
      screen.getByRole("heading", { name: "Asha Devi", level: 1 }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("patient-detail-name")).toHaveTextContent(
      "Asha Devi",
    );
    const values = screen.getAllByTestId("detail-field-value");
    expect(values.some((el) => el.textContent === "40")).toBe(true);
    expect(values.some((el) => el.textContent === "female")).toBe(true);
    expect(values.some((el) => el.textContent === "Daltonganj")).toBe(true);
    expect(values.some((el) => el.textContent === "+911234567890")).toBe(true);
  });

  it("streams the gated profile photo into an object-URL image", async () => {
    getPhoto.mockResolvedValue(new Blob(["x"], { type: "image/jpeg" }));
    const originalCreate = URL.createObjectURL;
    URL.createObjectURL = vi.fn(
      () => "blob:mock-photo",
    ) as typeof URL.createObjectURL;

    render(<DoctorPatientDetailPage />);

    await waitFor(() => screen.getByTestId("patient-photo"));
    expect(screen.getByTestId("patient-photo")).toHaveAttribute(
      "src",
      "blob:mock-photo",
    );
    expect(screen.getByAltText(t.photoAlt("Asha Devi"))).toBeInTheDocument();

    URL.createObjectURL = originalCreate;
  });

  it("falls back to the avatar when the patient has no photo", async () => {
    getDetail.mockResolvedValue(
      detail({ contact: { ...detail().contact!, has_photo: false } }),
    );
    render(<DoctorPatientDetailPage />);

    await waitFor(() => screen.getByTestId("patient-photo-fallback"));
    expect(screen.queryByTestId("patient-photo")).not.toBeInTheDocument();
  });

  it("falls back to the avatar when the gated photo read fails", async () => {
    getPhoto.mockRejectedValue(
      new ApiError({
        code: "RECORD_ACCESS_DENIED",
        message: "no grant",
        trace_id: "t",
        details: {},
      }),
    );
    render(<DoctorPatientDetailPage />);

    await waitFor(() => screen.getByTestId("patient-photo-fallback"));
    expect(screen.queryByTestId("patient-photo")).not.toBeInTheDocument();
  });

  it("renders granted-scope badges", async () => {
    render(<DoctorPatientDetailPage />);

    await waitFor(() => screen.getByTestId("detail-scope-badges"));

    expect(
      within(screen.getByTestId("detail-scope-badges")).getByText(
        t.scopeBadge.consultations,
      ),
    ).toBeInTheDocument();
    expect(
      within(screen.getByTestId("detail-scope-badges")).getByText(
        t.scopeBadge.health_background,
      ),
    ).toBeInTheDocument();
  });

  it("renders the consultation history with entry type labels", async () => {
    render(<DoctorPatientDetailPage />);

    await waitFor(() => screen.getByTestId("consultation-list"));

    const entries = screen.getAllByTestId("consultation-entry");
    expect(entries).toHaveLength(2);
    const types = screen.getAllByTestId("consultation-entry-type");
    expect(types[0]).toHaveTextContent(recordT.badge.consultation);
    expect(types[1]).toHaveTextContent(recordT.badge.prescription);
  });

  it("shows an empty message for an empty consultation history", async () => {
    getDetail.mockResolvedValue(
      detail({ consultation_history: { ...timeline(), entries: [] } }),
    );
    render(<DoctorPatientDetailPage />);

    await waitFor(() => screen.getByTestId("consultation-empty"));
    expect(screen.getByText(t.consultationHistoryEmpty)).toBeInTheDocument();
  });

  it("renders a locked not-shared state when consultation history is denied", async () => {
    getDetail.mockResolvedValue(detail({ consultation_history: null }));
    render(<DoctorPatientDetailPage />);

    await waitFor(() => screen.getByText(t.consultationHistoryHeading));

    expect(screen.getByTestId("locked-section")).toBeInTheDocument();
    expect(screen.getByText(t.notSharedTitle)).toBeInTheDocument();
    expect(screen.getByText(t.notSharedBody)).toBeInTheDocument();
  });

  it("renders the health background content under its live grant", async () => {
    render(<DoctorPatientDetailPage />);

    await waitFor(() => screen.getByTestId("health-background-set"));

    const set = within(screen.getByTestId("health-background-set"));
    expect(set.getByText(t.bloodGroupLabel)).toBeInTheDocument();
    const values = set.getAllByTestId("detail-field-value");
    expect(values.some((el) => el.textContent === "B+")).toBe(true);
    expect(values.some((el) => el.textContent === "Hypertension")).toBe(true);
    expect(values.some((el) => el.textContent === "Amlodipine")).toBe(true);
    expect(values.some((el) => el.textContent === t.noneRecorded)).toBe(true);
  });

  it("shows an empty message when the health background is not recorded", async () => {
    getDetail.mockResolvedValue(
      detail({
        health_background: {
          set: false,
          acknowledged: false,
          background: null,
        },
      }),
    );
    render(<DoctorPatientDetailPage />);

    await waitFor(() => screen.getByTestId("health-background-empty"));
    expect(screen.getByText(t.healthBackgroundEmpty)).toBeInTheDocument();
  });

  it("renders a locked not-shared state when health background is denied", async () => {
    getDetail.mockResolvedValue(detail({ health_background: null }));
    render(<DoctorPatientDetailPage />);

    await waitFor(() => screen.getByTestId("detail-health-background"));

    // The scope-badge chip also carries the "Health background" label, so
    // scope the heading assertion to the section itself.
    const section = within(screen.getByTestId("detail-health-background"));
    expect(section.getByText(t.healthBackgroundHeading)).toBeInTheDocument();
    expect(section.getByTestId("locked-section")).toBeInTheDocument();
  });

  it("renders a locked not-shared state when the whole contact block is denied", async () => {
    getDetail.mockResolvedValue(detail({ contact: null }));
    render(<DoctorPatientDetailPage />);

    await waitFor(() => screen.getByTestId("detail-contact"));

    const section = within(screen.getByTestId("detail-contact"));
    expect(section.getByText(t.contactHeading)).toBeInTheDocument();
    expect(section.getByTestId("locked-section")).toBeInTheDocument();
  });

  it("deep-links into the case workspace with its stage chip", async () => {
    render(<DoctorPatientDetailPage />);

    await waitFor(() => screen.getByTestId("case-workspace-link"));

    expect(screen.getByTestId("case-workspace-link")).toHaveAttribute(
      "href",
      "/doctor/cases/31",
    );
    expect(screen.getByTestId("case-workspace-stage")).toHaveTextContent(
      consoleT.stagePreSummary,
    );
  });

  it("shows a muted no-case state without a case workspace link", async () => {
    getDetail.mockResolvedValue(detail({ case_workspace: null }));
    render(<DoctorPatientDetailPage />);

    await waitFor(() => screen.getByTestId("case-workspace-none"));
    expect(screen.getByText(t.noCaseStage)).toBeInTheDocument();
    expect(screen.queryByTestId("case-workspace-link")).not.toBeInTheDocument();
  });

  it("shows a retryable error banner when the detail read fails", async () => {
    getDetail.mockRejectedValue(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "trace-detail-001",
        details: {},
      }),
    );
    render(<DoctorPatientDetailPage />);

    await waitFor(() => screen.getByTestId("error-banner"));
    expect(screen.getByText(t.loadFailedDetail)).toBeInTheDocument();
  });

  it("retries the detail read from the error state", async () => {
    getDetail.mockRejectedValueOnce(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "t",
        details: {},
      }),
    );
    render(<DoctorPatientDetailPage />);

    await waitFor(() => screen.getByTestId("error-banner"));

    getDetail.mockResolvedValue(detail());
    screen.getByTestId("error-banner-retry").click();

    await waitFor(() => screen.getByTestId("detail-contact"));
    expect(getDetail).toHaveBeenCalledTimes(2);
  });

  it("bails out with a calm error surface for a non-numeric patient id", () => {
    const params = vi.mocked(useParams);
    params.mockReturnValue({ patientId: "nope" });
    render(<DoctorPatientDetailPage />);

    expect(screen.getByTestId("error-banner")).toBeInTheDocument();
    expect(screen.getByText(t.loadFailedDetail)).toBeInTheDocument();
    expect(getDetail).not.toHaveBeenCalled();
    params.mockReturnValue({ patientId: "11" });
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
          <DoctorPatientDetailPage />
        </>
      );
    }

    render(<LangFlipHost />);

    await waitFor(() => screen.getByTestId("detail-contact"));

    screen.getByText("flip-lang").click();
    await waitFor(() =>
      expect(screen.getByText(hiT.contactHeading)).toBeInTheDocument(),
    );
    expect(
      within(screen.getByTestId("detail-consultation-history")).getByText(
        hiT.consultationHistoryHeading,
      ),
    ).toBeInTheDocument();
    expect(
      within(screen.getByTestId("detail-health-background")).getByText(
        hiT.healthBackgroundHeading,
      ),
    ).toBeInTheDocument();
  });
});
