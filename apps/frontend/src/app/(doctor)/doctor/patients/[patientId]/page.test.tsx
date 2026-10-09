// PHASE-8.1 (#541): doctor console patient detail suite. The section-gated
// read renders exactly what the gated detail API (#540) answers: contact with
// the streamed photo, consultation history, health background under their
// live grants, the case workspace deep link, and a calm locked "not shared"
// state for ungranted sections (never an error). Covers load/error/retry,
// photo degrade, and bilingual EN/HI parity (REQ-006).
//
// #659: the header band (large avatar + name + inline age/gender chips), the
// health-background chip rows instead of a comma-joined run-on, the
// Hindi-wrapping guarantee for long labels, and the preserved locked/photo
// behaviour.

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
const enGenders = STRINGS.en.profile.genders;
const hiGenders = STRINGS.hi.profile.genders;
const getDetail = vi.mocked(fetchDoctorPatientDetail);
const getPhoto = vi.mocked(fetchDoctorPatientPhoto);

/** Locale-flipping host so a test can assert the Hindi render mid-flight. */
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

/** The header's two inline chips, asserted for one locale (#659 AC-2/AC-8). */
function expectHeaderChips(
  tv: typeof t,
  genders: typeof enGenders,
  age = "40",
) {
  const chips = within(screen.getByTestId("patient-header-chips"));
  expect(chips.getByTestId("patient-age-chip")).toHaveTextContent(
    `${tv.ageLabel}: ${age}`,
  );
  expect(chips.getByTestId("patient-gender-chip")).toHaveTextContent(
    `${tv.genderLabel}: ${genders.female}`,
  );
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
    expect(values.some((el) => el.textContent === "Daltonganj")).toBe(true);
    expect(values.some((el) => el.textContent === "+911234567890")).toBe(true);
  });

  it("leads the header band with a large avatar and the patient's name (#659 AC-1)", async () => {
    render(<DoctorPatientDetailPage />);

    await waitFor(() => screen.getByTestId("patient-header-band"));

    // One band: the large avatar, the name, and the chips share a row - the
    // age/gender fields no longer stack as form rows beneath them (#659).
    const band = within(screen.getByTestId("patient-header-band"));
    const avatar = band.getByTestId("patient-photo-fallback");
    expect(avatar.className).toContain("h-20 w-20");
    expect(band.getByTestId("patient-detail-name")).toHaveTextContent(
      "Asha Devi",
    );
    expect(band.getByTestId("patient-age-chip")).toBeInTheDocument();
    expect(band.getByTestId("patient-gender-chip")).toBeInTheDocument();
    expect(band.queryByTestId("detail-field-value")).not.toBeInTheDocument();
  });

  it("renders age and gender as inline header chips, not stacked rows (#659 AC-2)", async () => {
    render(<DoctorPatientDetailPage />);

    await waitFor(() => screen.getByTestId("patient-header-chips"));

    expectHeaderChips(t, enGenders);

    // ...and neither value lingers as a stacked detail-field row.
    const values = screen.getAllByTestId("detail-field-value");
    expect(values.some((el) => el.textContent === "40")).toBe(false);
    expect(values.some((el) => el.textContent === enGenders.female)).toBe(
      false,
    );
  });

  it("streams the gated profile photo into an object-URL image (#659 AC-6)", async () => {
    getPhoto.mockResolvedValue(new Blob(["x"], { type: "image/jpeg" }));
    const originalCreate = URL.createObjectURL;
    URL.createObjectURL = vi.fn(
      () => "blob:mock-photo",
    ) as typeof URL.createObjectURL;

    render(<DoctorPatientDetailPage />);

    await waitFor(() => screen.getByTestId("patient-photo"));
    // The header band renders the gated route's bytes - the src is the object
    // URL, never a reference read off the detail payload (#659 / US-61).
    expect(getPhoto).toHaveBeenCalledWith(11);
    const band = within(screen.getByTestId("patient-header-band"));
    expect(band.getByTestId("patient-photo")).toHaveAttribute(
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

  it("renders each entry's per-type detail through the shared renderer (#680 AC-1/AC-2)", async () => {
    getDetail.mockResolvedValue(
      detail({
        consultation_history: {
          ...timeline(),
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
              payload: {
                status: "active",
                attributed_doctor_name: "Dr. A. Kumar",
                items: [
                  {
                    name: "Amlodipine",
                    dose: "5 mg",
                    frequency: "once daily",
                    duration: "30 days",
                  },
                ],
              },
              occurred_at: "2026-08-20T00:00:00Z",
              created_at: "2026-08-20T00:00:00Z",
            },
            {
              entry_id: 13,
              entry_type: "lab_report",
              payload: { filename: "cbc-report.pdf", order_id: 42 },
              occurred_at: "2026-08-10T00:00:00Z",
              created_at: "2026-08-10T00:00:00Z",
            },
            {
              entry_id: 14,
              entry_type: "settlement",
              payload: { amount_paise: 50000, order_ref: "ORD-9" },
              occurred_at: "2026-08-01T00:00:00Z",
              created_at: "2026-08-01T00:00:00Z",
            },
          ],
        },
      }),
    );
    render(<DoctorPatientDetailPage />);

    await waitFor(() => screen.getByTestId("consultation-list"));

    const entries = screen.getAllByTestId("consultation-entry");
    expect(entries).toHaveLength(4);

    // Type tag and date stay on every entry; the payload-less consultation
    // keeps the scan line only, never a half card (#680 AC-2).
    const consult = within(entries[0]);
    expect(consult.getByTestId("consultation-entry-type")).toHaveTextContent(
      recordT.badge.consultation,
    );
    expect(
      consult.queryByTestId("consultation-entry-detail"),
    ).not.toBeInTheDocument();
    expect(entries[0]).toHaveTextContent(/1 Sep/);

    // Prescription: each medicine line plus the attributed doctor (US-33).
    const rx = within(entries[1]);
    expect(rx.getByTestId("consultation-entry-type")).toHaveTextContent(
      recordT.badge.prescription,
    );
    const rxDetail = rx.getByTestId("consultation-entry-detail");
    expect(rxDetail).toHaveTextContent(recordT.prescribedBy);
    expect(rxDetail).toHaveTextContent("Dr. A. Kumar");
    expect(rx.getByTestId("consultation-entry-medicine")).toHaveTextContent(
      "Amlodipine",
    );
    expect(rxDetail).toHaveTextContent("Dose: 5 mg");

    // Lab report: file name plus order reference.
    const lab = within(entries[2]);
    const labDetail = lab.getByTestId("consultation-entry-detail");
    expect(labDetail).toHaveTextContent(recordT.history.file);
    expect(labDetail).toHaveTextContent("cbc-report.pdf");
    expect(labDetail).toHaveTextContent("#42");

    // Settlement: amount plus order reference.
    const settlement = within(entries[3]);
    const settlementDetail = settlement.getByTestId(
      "consultation-entry-detail",
    );
    expect(settlementDetail).toHaveTextContent(recordT.history.amount);
    expect(settlementDetail).toHaveTextContent("#ORD-9");
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
    // Populated areas chip; the empty ones render the plain none-recorded
    // text with no chip that could be misread as data.
    expect(set.getAllByTestId("health-chip")).toHaveLength(2);
  });

  it("renders health-background values as scannable chips, never a comma-joined run-on (#659 AC-3)", async () => {
    getDetail.mockResolvedValue(
      detail({
        health_background: {
          set: true,
          acknowledged: true,
          background: {
            blood_group: "B+",
            conditions: ["Hypertension", "Type 2 diabetes"],
            allergies: ["Penicillin", "Dust mite"],
            medications: ["Amlodipine"],
            immunizations: ["TT"],
            family_history: ["Father: diabetes"],
          },
        },
      }),
    );
    render(<DoctorPatientDetailPage />);

    await waitFor(() => screen.getByTestId("health-background-set"));

    const set = within(screen.getByTestId("health-background-set"));
    expect(
      set.getAllByTestId("health-chip").map((chip) => chip.textContent),
    ).toEqual([
      "Hypertension",
      "Type 2 diabetes",
      "Penicillin",
      "Dust mite",
      "Amlodipine",
      "TT",
      "Father: diabetes",
    ]);
    expect(
      set.queryByText("Hypertension, Type 2 diabetes"),
    ).not.toBeInTheDocument();
    // The chip row wraps instead of overflowing - a long list becomes more
    // rows rather than one horizontal line.
    const firstChip = set.getAllByTestId("health-chip")[0];
    expect(firstChip.parentElement?.className).toContain("flex-wrap");
    expect(set.getAllByTestId("health-chip")).toHaveLength(7);
  });

  it("wraps long Hindi health labels away from their values (#659 AC-4)", async () => {
    render(<LangFlipHost />);

    await waitFor(() => screen.getByTestId("health-background-set"));
    screen.getByText("flip-lang").click();
    // Scope to the section: the granted-scope badge carries the same words.
    await waitFor(() =>
      expect(
        within(screen.getByTestId("detail-health-background")).getByText(
          hiT.healthBackgroundHeading,
        ),
      ).toBeInTheDocument(),
    );

    const set = within(screen.getByTestId("health-background-set"));
    const familyLabel = set
      .getAllByTestId("health-area-label")
      .find((el) => el.textContent === hiT.familyHistoryLabel);
    expect(familyLabel).toBeDefined();
    // The label may wrap (break-words) but is never pinned to one line or a
    // fixed-width column, so a long Devanagari label cannot collide with the
    // chips below it (#659 / US-59).
    expect(familyLabel?.className).toContain("break-words");
    expect(familyLabel?.className).not.toContain("whitespace-nowrap");
    expect(familyLabel?.parentElement?.className).toContain("space-y-1.5");
    // The empty granted areas still show the plain none-recorded text in
    // Hindi - not chips, not the locked card.
    expect(
      set.getAllByText(hiT.noneRecorded, { selector: "span" }).length,
    ).toBeGreaterThan(0);
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

  it("renders a locked not-shared state when health background is denied (#659 AC-5)", async () => {
    getDetail.mockResolvedValue(detail({ health_background: null }));
    render(<DoctorPatientDetailPage />);

    await waitFor(() => screen.getByTestId("detail-health-background"));

    // The scope-badge chip also carries the "Health background" label, so
    // scope the heading assertion to the section itself.
    const section = within(screen.getByTestId("detail-health-background"));
    expect(section.getByText(t.healthBackgroundHeading)).toBeInTheDocument();
    expect(section.getByTestId("locked-section")).toBeInTheDocument();
    // The locked section stays calm: no chips, no empty chip row that could
    // read as "no conditions" when the truth is "not shared" (#659 / US-60).
    expect(section.getByText(t.notSharedTitle)).toBeInTheDocument();
    expect(section.getByText(t.notSharedBody)).toBeInTheDocument();
    expect(section.queryByTestId("health-chip")).not.toBeInTheDocument();
    expect(
      section.queryByTestId("health-background-set"),
    ).not.toBeInTheDocument();
  });

  it("renders a locked not-shared state when the whole contact block is denied (#659 AC-5)", async () => {
    getDetail.mockResolvedValue(detail({ contact: null }));
    render(<DoctorPatientDetailPage />);

    await waitFor(() => screen.getByTestId("detail-contact"));

    const section = within(screen.getByTestId("detail-contact"));
    expect(section.getByText(t.contactHeading)).toBeInTheDocument();
    expect(section.getByTestId("locked-section")).toBeInTheDocument();
    expect(section.getByText(t.notSharedTitle)).toBeInTheDocument();
    expect(
      section.queryByTestId("patient-header-band"),
    ).not.toBeInTheDocument();
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
    // Every header chip ships in Hindi too: the label comes from the hi
    // dictionary, the gender value from the shared bilingual vocabulary.
    expectHeaderChips(hiT, hiGenders);
  });
});
