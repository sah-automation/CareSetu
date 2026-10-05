// PRD trace: FEAT-005 (Provider Profiles and Credential Display).
// PHASE-8.1 T12 (#450): doctor console landing page suite. Covers the review
// queue (ranked low-confidence first with the amber Verify chip and a
// confidence flag, US-11/12), the open care-cases section with stage chips
// (US-15), the deep links into the workspace routes (review/[intakeId],
// cases/[caseId]) that #451-#453 fill, load failure with retry, and bilingual
// EN/HI parity (REQ-006). The consultation-fee editor that used to live here
// moved to the Profile page in #543 and is covered by its own suite.
//
// #544: the coming-soon Patients/Profile tabs are replaced by real entry cards
// that deep-link to the live pages, a compact consultation-fee summary card
// reads the private profile and links into the moved editor, and the whole
// landing adopts the patient shell's card/chip/responsive language.

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
import { fetchDoctorProfile, type DoctorProfileView } from "@/lib/doctor/api";

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

vi.mock("@/lib/doctor/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/doctor/api")>();
  return { ...mod, fetchDoctorProfile: vi.fn() };
});

const t = STRINGS.en.doctorConsole;
const hiT = STRINGS.hi.doctorConsole;
const getQueue = vi.mocked(fetchReviewQueue);
const getCases = vi.mocked(listOpenCases);
const getProfile = vi.mocked(fetchDoctorProfile);

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

function doctorProfile(
  overrides: Partial<DoctorProfileView> = {},
): DoctorProfileView {
  return {
    partner_id: 7,
    photo_ref: null,
    practice_name: "Kumar Clinic",
    clinic_name: null,
    specialties: ["General physician"],
    verified: true,
    practice_address: "12 MG Road",
    address_line: null,
    landmark: null,
    locality: "Indiranagar",
    city: "Bengaluru",
    pin_code: null,
    practice_latitude: 12.9716,
    practice_longitude: 77.5946,
    area: "Indiranagar",
    languages: ["English", "Kannada"],
    experience_years: 9,
    about: null,
    consultation_fee: 50000,
    consulting_days: [],
    consulting_hours: null,
    credentials: [],
    notification_preferences: {},
    ...overrides,
  };
}

function resolveLoaded() {
  getQueue.mockResolvedValue([]);
  getCases.mockResolvedValue([]);
  getProfile.mockResolvedValue(doctorProfile());
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

describe("DoctorDashboardPage entry cards (#544)", () => {
  it("deep-links the Patients card to the live patients page", async () => {
    render(<DoctorDashboardPage />);
    await waitFor(() => screen.getByTestId("entry-patients"));

    const card = screen.getByTestId("entry-patients");
    expect(card).toHaveAttribute("href", "/doctor/patients");
    expect(card).toHaveTextContent(STRINGS.en.nav.patients);
    expect(card).toHaveTextContent(t.patientsEntryBody);
    // A real destination: not the coming-soon aria-disabled placeholder.
    expect(card).not.toHaveAttribute("aria-disabled");
  });

  it("deep-links the Profile card to the live profile page", async () => {
    render(<DoctorDashboardPage />);
    await waitFor(() => screen.getByTestId("entry-profile"));

    const card = screen.getByTestId("entry-profile");
    expect(card).toHaveAttribute("href", "/doctor/profile");
    expect(card).toHaveTextContent(STRINGS.en.nav.profile);
    expect(card).toHaveTextContent(t.profileEntryBody);
    expect(card).not.toHaveAttribute("aria-disabled");
  });

  it("drops the coming-soon placeholders entirely (US-26)", async () => {
    render(<DoctorDashboardPage />);
    await waitFor(() => screen.getByTestId("entry-patients"));

    expect(
      screen.queryByTestId("coming-soon-patients"),
    ).not.toBeInTheDocument();
    expect(screen.queryByTestId("coming-soon-profile")).not.toBeInTheDocument();
  });

  it("lays the two cards out 2-up on a phone, like the patient services grid", async () => {
    render(<DoctorDashboardPage />);
    await waitFor(() => screen.getByTestId("entry-patients"));

    const grid = screen.getByTestId("entry-cards");
    expect(grid.className).toContain("grid-cols-2");
    expect(grid.className).toContain("gap-3");
  });
});

describe("DoctorDashboardPage consultation-fee summary (#544)", () => {
  it("shows the current fee and links into the moved editor on the profile", async () => {
    getProfile.mockResolvedValue(doctorProfile({ consultation_fee: 50000 }));
    render(<DoctorDashboardPage />);

    await waitFor(() => screen.getByTestId("fee-summary-value"));

    expect(screen.getByTestId("fee-summary-value")).toHaveTextContent("₹500");
    expect(screen.getByTestId("fee-summary-edit")).toHaveAttribute(
      "href",
      "/doctor/profile#fee-editor",
    );
    expect(screen.getByTestId("fee-summary")).toHaveTextContent(t.feeHeading);
  });

  it("skeletons the fee while the private profile read is in flight", () => {
    render(<DoctorDashboardPage />);
    expect(screen.getByTestId("fee-summary-skeleton")).toBeInTheDocument();
  });

  it("says the fee is not set rather than showing a zero amount", async () => {
    getProfile.mockResolvedValue(doctorProfile({ consultation_fee: null }));
    render(<DoctorDashboardPage />);

    await waitFor(() => screen.getByTestId("fee-summary-value"));

    expect(screen.getByTestId("fee-summary-value")).toHaveTextContent(
      t.feeUnset,
    );
    expect(screen.getByTestId("fee-summary")).toHaveTextContent(t.feeUnsetHelp);
  });

  it("keeps a failed fee read off the console: the queue and cases still load", async () => {
    getProfile.mockRejectedValue(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "trace-fee-01",
        details: {},
      }),
    );
    getQueue.mockResolvedValue([queueItem()]);
    getCases.mockResolvedValue([caseItem(11)]);
    render(<DoctorDashboardPage />);

    await waitFor(() => screen.getByTestId("fee-summary-error"));
    // The console itself is healthy: the failure is scoped to the fee card.
    expect(screen.getByTestId("queue-item")).toBeInTheDocument();
    expect(screen.getByTestId("case-item")).toBeInTheDocument();
    expect(screen.queryByTestId("error-banner")).not.toBeInTheDocument();
    expect(screen.getByTestId("fee-summary-error")).toHaveTextContent(
      t.feeLoadFailed,
    );
  });

  it("retries just the fee read from the card", async () => {
    getProfile.mockRejectedValueOnce(new Error("offline"));
    render(<DoctorDashboardPage />);
    await waitFor(() => screen.getByTestId("fee-summary-error"));

    getProfile.mockResolvedValue(doctorProfile({ consultation_fee: 300 }));
    fireEvent.click(screen.getByTestId("fee-summary-retry"));

    await waitFor(() => screen.getByTestId("fee-summary-value"));
    expect(screen.getByTestId("fee-summary-value")).toHaveTextContent("₹3");
    expect(getProfile).toHaveBeenCalledTimes(2);
    // The retry is scoped: the console feeds are not refetched with it.
    expect(getQueue).toHaveBeenCalledTimes(1);
  });
});

describe("DoctorDashboardPage patient-shell restyle (#544)", () => {
  it("renders the queue and cases sections as surface cards, not bare headings", async () => {
    getQueue.mockResolvedValue([queueItem()]);
    getCases.mockResolvedValue([caseItem(11)]);
    render(<DoctorDashboardPage />);

    await waitFor(() => screen.getByTestId("queue-item"));

    for (const testId of ["review-queue", "open-cases"]) {
      const className = screen.getByTestId(testId).className;
      expect(className).toContain("rounded-lg");
      expect(className).toContain("border-hairline");
      expect(className).toContain("bg-surface");
    }
  });

  it("counts the queue and the cases in status chips on the section headers", async () => {
    getQueue.mockResolvedValue([
      queueItem({ pre_summary_id: 1 }),
      queueItem({ pre_summary_id: 2 }),
    ]);
    getCases.mockResolvedValue([caseItem(11), caseItem(12), caseItem(13)]);
    render(<DoctorDashboardPage />);

    await waitFor(() => screen.getByTestId("queue-count"));

    expect(screen.getByTestId("queue-count")).toHaveTextContent("2");
    expect(screen.getByTestId("cases-count")).toHaveTextContent("3");
  });

  it("hides the count chips when there is nothing to count", async () => {
    render(<DoctorDashboardPage />);
    await waitFor(() =>
      within(screen.getByTestId("review-queue")).getByTestId("empty-state"),
    );

    expect(screen.queryByTestId("queue-count")).not.toBeInTheDocument();
    expect(screen.queryByTestId("cases-count")).not.toBeInTheDocument();
  });

  it("splits a row onto a full-width action below 720px, in-line above it", async () => {
    getQueue.mockResolvedValue([queueItem()]);
    render(<DoctorDashboardPage />);

    await waitFor(() => screen.getByTestId("queue-item-review"));

    const action = screen.getByTestId("queue-item-review");
    expect(action.className).toContain("w-full");
    expect(action.className).toContain("min-[720px]:w-auto");
    // The wrapper owns the responsive switch, so the action never squeezes the
    // text column on a phone.
    const row = screen.getByTestId("queue-item");
    expect(row.className).toContain("min-[720px]:flex-row");
  });

  it("gives each empty state a body so it explains itself", async () => {
    getCases.mockResolvedValue([caseItem(11)]);
    render(<DoctorDashboardPage />);
    await waitFor(() =>
      within(screen.getByTestId("review-queue")).getByTestId("empty-state"),
    );

    expect(
      within(screen.getByTestId("review-queue")).getByTestId("empty-state"),
    ).toHaveTextContent(t.queueEmptyBody);
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
    getProfile.mockResolvedValue(doctorProfile({ consultation_fee: 50000 }));
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
  });

  it("#544 carries the entry cards, fee summary and empty-state bodies into Hindi", async () => {
    getProfile.mockResolvedValue(doctorProfile({ consultation_fee: 50000 }));
    render(<LangFlipHost />);
    await waitFor(() => screen.getByTestId("fee-summary-value"));

    fireEvent.click(screen.getByText("flip-lang"));
    await waitFor(() =>
      expect(screen.getByTestId("fee-summary")).toHaveTextContent(
        hiT.feeHeading,
      ),
    );

    expect(screen.getByTestId("entry-patients")).toHaveTextContent(
      STRINGS.hi.nav.patients,
    );
    expect(screen.getByTestId("entry-patients")).toHaveTextContent(
      hiT.patientsEntryBody,
    );
    expect(screen.getByTestId("entry-profile")).toHaveTextContent(
      hiT.profileEntryBody,
    );
    expect(screen.getByTestId("fee-summary")).toHaveTextContent(
      hiT.feeEditAction,
    );
  });
});
