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
//
// #676: the open-cases section reads the console's patient-enriched cases feed
// (listDoctorCases) and renders the shared DoctorListCard the cases index uses
// - patient name plus age, the amber Verify chip on a forced review, the
// citable case id + relative "updated" line, and one whole-card link whose
// accessible name includes the patient (US-66/67).

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
import {
  formatGreetingDate,
  greetingTimeText,
} from "@/lib/doctor/dashboardGreeting";
import { fetchReviewQueue, type ReviewQueueItem } from "@/lib/intake/api";
import {
  fetchDoctorProfile,
  listDoctorCases,
  listDoctorPatients,
  type DoctorCaseRow,
  type DoctorCasesListView,
  type DoctorProfileView,
} from "@/lib/doctor/api";

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

vi.mock("@/lib/doctor/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/doctor/api")>();
  return {
    ...mod,
    fetchDoctorProfile: vi.fn(),
    listDoctorCases: vi.fn(),
    listDoctorPatients: vi.fn(),
  };
});

const t = STRINGS.en.doctorConsole;
const hiT = STRINGS.hi.doctorConsole;
const getQueue = vi.mocked(fetchReviewQueue);
const getCases = vi.mocked(listDoctorCases);
const getProfile = vi.mocked(fetchDoctorProfile);
const getPatients = vi.mocked(listDoctorPatients);

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

function patientsView(total: number): { items: []; total: number } {
  return { items: [], total };
}

function resolveLoaded() {
  getQueue.mockResolvedValue([]);
  getCases.mockResolvedValue(casesView());
  getProfile.mockResolvedValue(doctorProfile());
  getPatients.mockResolvedValue(patientsView(0));
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
      <DoctorDashboardPage />
    </>
  );
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
    getCases.mockResolvedValue(casesView(caseItem(11)));
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
    getCases.mockResolvedValue(
      casesView(
        caseItem(11, { stage: "pre_summary" }),
        caseItem(12, { stage: "prescription_pending" }),
      ),
    );
    render(<DoctorDashboardPage />);

    await waitFor(() => screen.getByTestId("cases-list"));

    expect(screen.getByText("Case #11")).toBeTruthy();
    expect(screen.getByText("Case #12")).toBeTruthy();
    const stageChips = screen.getAllByTestId("case-item-stage");
    expect(stageChips[0]).toHaveTextContent(t.stagePreSummary);
    expect(stageChips[1]).toHaveTextContent(t.stagePrescriptionPending);
  });

  it("renders each case as the shared doctor card: patient name and age", async () => {
    getCases.mockResolvedValue(
      casesView(
        caseItem(11, { patient_name: "Asha Verma", patient_age: 45 }),
        caseItem(12, { patient_name: "Ravi Nair", patient_age: 31 }),
      ),
    );
    render(<DoctorDashboardPage />);

    await waitFor(() => screen.getByTestId("cases-list"));

    expect(screen.getAllByTestId("case-item-patient")[0]).toHaveTextContent(
      "Asha Verma",
    );
    expect(screen.getByText(t.patientAge(45))).toBeInTheDocument();
    expect(screen.getByText(t.patientAge(31))).toBeInTheDocument();
  });

  it("falls back to the patient word when the backend cannot name the patient", async () => {
    getCases.mockResolvedValue(
      casesView(caseItem(11, { patient_name: null, patient_age: null })),
    );
    render(<DoctorDashboardPage />);

    await waitFor(() => screen.getByTestId("cases-list"));

    expect(screen.getByTestId("case-item-patient")).toHaveTextContent(
      t.patientFallback,
    );
    expect(screen.queryByText(t.patientAge(45))).not.toBeInTheDocument();
  });

  it("shows the amber Verify chip only on a forced-review case", async () => {
    getCases.mockResolvedValue(
      casesView(caseItem(11, { forced_review: true }), caseItem(12)),
    );
    render(<DoctorDashboardPage />);

    await waitFor(() => screen.getByTestId("cases-list"));

    const verifyChips = screen.getAllByTestId("case-item-verify");
    expect(verifyChips).toHaveLength(1);
    expect(verifyChips[0]).toHaveTextContent(t.verifyChip);
    expect(verifyChips[0].className).toContain("bg-warn-soft");
    expect(verifyChips[0].className).toContain("text-warn-text");
  });

  it("shows how long ago the case was last updated", async () => {
    getCases.mockResolvedValue(casesView(caseItem(11)));
    render(<DoctorDashboardPage />);

    await waitFor(() => screen.getByTestId("cases-list"));

    expect(screen.getByTestId("case-item-updated")).toHaveTextContent(
      t.caseUpdatedAgo(t.timeAgoHours(3)),
    );
  });

  it("makes each whole card one focus stop whose accessible name includes the patient", async () => {
    getCases.mockResolvedValue(
      casesView(
        caseItem(11, { patient_name: "Asha Verma" }),
        caseItem(12, { patient_name: "Ravi Nair" }),
      ),
    );
    render(<DoctorDashboardPage />);

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

  it("deep-links each open case into the case workspace", async () => {
    getCases.mockResolvedValue(casesView(caseItem(11)));
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

describe("DoctorDashboardPage quick actions (#681)", () => {
  it("deep-links the Patients action to the live patients page", async () => {
    render(<DoctorDashboardPage />);
    await waitFor(() => screen.getByTestId("quick-action-patients"));

    const card = screen.getByTestId("quick-action-patients");
    expect(card).toHaveAttribute("href", "/doctor/patients");
    expect(card).toHaveTextContent(STRINGS.en.nav.patients);
    expect(card).toHaveTextContent(t.patientsEntryBody);
    // A real destination: not the coming-soon aria-disabled placeholder.
    expect(card).not.toHaveAttribute("aria-disabled");
  });

  it("deep-links the My cases action to the cases index", async () => {
    render(<DoctorDashboardPage />);
    await waitFor(() => screen.getByTestId("quick-action-cases"));

    const card = screen.getByTestId("quick-action-cases");
    expect(card).toHaveAttribute("href", "/doctor/cases");
    expect(card).toHaveTextContent(t.casesIndexTitle);
    expect(card).toHaveTextContent(t.casesEntryBody);
    expect(card).not.toHaveAttribute("aria-disabled");
  });

  it("deep-links the Profile action to the live profile page", async () => {
    render(<DoctorDashboardPage />);
    await waitFor(() => screen.getByTestId("quick-action-profile"));

    const card = screen.getByTestId("quick-action-profile");
    expect(card).toHaveAttribute("href", "/doctor/profile");
    expect(card).toHaveTextContent(STRINGS.en.nav.profile);
    expect(card).toHaveTextContent(t.profileEntryBody);
    expect(card).not.toHaveAttribute("aria-disabled");
  });

  it("heads the row Quick actions", async () => {
    render(<DoctorDashboardPage />);
    await waitFor(() => screen.getByTestId("quick-actions"));

    expect(screen.getByTestId("quick-actions")).toHaveTextContent(
      t.quickActionsHeading,
    );
  });

  it("drops the coming-soon placeholders entirely (US-26)", async () => {
    render(<DoctorDashboardPage />);
    await waitFor(() => screen.getByTestId("quick-action-patients"));

    expect(
      screen.queryByTestId("coming-soon-patients"),
    ).not.toBeInTheDocument();
    expect(screen.queryByTestId("coming-soon-profile")).not.toBeInTheDocument();
  });

  it("lays the actions 2-up on a phone, 3-up on a wide screen", async () => {
    render(<DoctorDashboardPage />);
    await waitFor(() => screen.getByTestId("quick-action-patients"));

    const grid = screen.getByTestId("quick-action-grid");
    expect(grid.className).toContain("grid-cols-2");
    expect(grid.className).toContain("gap-3");
    expect(grid.className).toContain("lg:grid-cols-3");
  });
});

describe("DoctorDashboardPage workload KPI row (#681)", () => {
  it("shows the four workload counts, each linked to the page it summarises", async () => {
    getQueue.mockResolvedValue([
      queueItem({ pre_summary_id: 1, intake_id: 1 }),
      queueItem({ pre_summary_id: 2, intake_id: 2 }),
    ]);
    getCases.mockResolvedValue(
      casesView(caseItem(11), caseItem(12), caseItem(13)),
    );
    getPatients.mockResolvedValue(patientsView(7));
    getProfile.mockResolvedValue(doctorProfile({ consultation_fee: 50000 }));
    render(<DoctorDashboardPage />);

    await waitFor(() =>
      expect(screen.getByTestId("kpi-open-cases-value")).toHaveTextContent("3"),
    );
    expect(screen.getByTestId("kpi-awaiting-review-value")).toHaveTextContent(
      "2",
    );
    await waitFor(() =>
      expect(
        screen.getByTestId("kpi-current-patients-value"),
      ).toHaveTextContent("7"),
    );
    await waitFor(() =>
      expect(
        screen.getByTestId("kpi-consultation-fee-value"),
      ).toHaveTextContent("₹500"),
    );

    expect(screen.getByTestId("kpi-open-cases")).toHaveAttribute(
      "href",
      "/doctor/cases",
    );
    expect(screen.getByTestId("kpi-awaiting-review")).toHaveAttribute(
      "href",
      "/doctor#review-queue",
    );
    expect(screen.getByTestId("kpi-current-patients")).toHaveAttribute(
      "href",
      "/doctor/patients",
    );
    expect(screen.getByTestId("kpi-consultation-fee")).toHaveAttribute(
      "href",
      "/doctor/profile#profile-section-fee",
    );
  });

  it("reads the current-patients count from the best-effort patients total", async () => {
    getPatients.mockResolvedValue(patientsView(12));
    render(<DoctorDashboardPage />);

    await waitFor(() =>
      expect(
        screen.getByTestId("kpi-current-patients-value"),
      ).toHaveTextContent("12"),
    );
    expect(getPatients).toHaveBeenCalledWith({ page: 1, perPage: 1 });
  });

  it("shows zero for a genuinely empty patients list, not an em dash", async () => {
    getPatients.mockResolvedValue(patientsView(0));
    render(<DoctorDashboardPage />);

    await waitFor(() =>
      expect(
        screen.getByTestId("kpi-current-patients-value"),
      ).toHaveTextContent("0"),
    );
  });

  it("degrades the patients tile to an em dash on a failed read, and the page still renders", async () => {
    getPatients.mockRejectedValue(new Error("offline"));
    getQueue.mockResolvedValue([queueItem()]);
    getCases.mockResolvedValue(casesView(caseItem(11)));
    render(<DoctorDashboardPage />);

    await waitFor(() => screen.getByTestId("queue-item"));

    expect(screen.getByTestId("kpi-current-patients-value")).toHaveTextContent(
      "\u2014",
    );
    // The console itself is healthy: the failure is scoped to its tile.
    expect(screen.getByTestId("case-item")).toBeInTheDocument();
    expect(screen.getByTestId("kpi-open-cases-value")).toHaveTextContent("1");
    expect(screen.queryByTestId("error-banner")).not.toBeInTheDocument();
  });

  it("shows a loading skeleton for the fee tile while the profile read is in flight", () => {
    getProfile.mockReturnValue(new Promise(() => {}));
    render(<DoctorDashboardPage />);

    expect(screen.getByTestId("kpi-consultation-fee-value")).toHaveClass(
      "animate-pulse",
    );
  });

  it("shows an em dash for the fee tile when the profile read fails", async () => {
    getProfile.mockRejectedValue(new Error("nope"));
    render(<DoctorDashboardPage />);

    await waitFor(() =>
      expect(
        screen.getByTestId("kpi-consultation-fee-value"),
      ).toHaveTextContent("\u2014"),
    );
  });

  it("labels the fee tile Not set when the shared profile read resolves without a fee", async () => {
    getProfile.mockResolvedValue(doctorProfile({ consultation_fee: null }));
    render(<DoctorDashboardPage />);

    await waitFor(() =>
      expect(
        screen.getByTestId("kpi-consultation-fee-value"),
      ).toHaveTextContent(t.feeUnset),
    );
  });

  it("shows loading skeletons for all four tiles while their reads are in flight", () => {
    render(<DoctorDashboardPage />);

    expect(screen.getByTestId("kpi-open-cases-value")).toHaveClass(
      "animate-pulse",
    );
    expect(screen.getByTestId("kpi-awaiting-review-value")).toHaveClass(
      "animate-pulse",
    );
    expect(screen.getByTestId("kpi-current-patients-value")).toHaveClass(
      "animate-pulse",
    );
    expect(screen.getByTestId("kpi-consultation-fee-value")).toHaveClass(
      "animate-pulse",
    );
  });

  it("shows em dashes for the feed tiles when the console feed fails", async () => {
    getQueue.mockRejectedValue(new Error("boom"));
    getCases.mockRejectedValue(new Error("boom"));
    render(<DoctorDashboardPage />);

    await waitFor(() => screen.getByTestId("queue-error"));

    expect(screen.getByTestId("kpi-open-cases-value")).toHaveTextContent(
      "\u2014",
    );
    expect(screen.getByTestId("kpi-awaiting-review-value")).toHaveTextContent(
      "\u2014",
    );
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
      "/doctor/profile#profile-section-fee",
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
    getCases.mockResolvedValue(casesView(caseItem(11)));
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
    getCases.mockResolvedValue(casesView(caseItem(11)));
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
    getCases.mockResolvedValue(
      casesView(caseItem(11), caseItem(12), caseItem(13)),
    );
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
    getCases.mockResolvedValue(casesView(caseItem(11)));
    render(<DoctorDashboardPage />);
    await waitFor(() =>
      within(screen.getByTestId("review-queue")).getByTestId("empty-state"),
    );

    expect(
      within(screen.getByTestId("review-queue")).getByTestId("empty-state"),
    ).toHaveTextContent(t.queueEmptyBody);
  });
});

describe("DoctorDashboardPage getting-started checklist (#674)", () => {
  it("appears for a brand-new doctor with no open cases and an empty review queue", async () => {
    render(<DoctorDashboardPage />);

    await waitFor(() => screen.getByTestId("getting-started"));
    expect(screen.getByTestId("getting-started")).toHaveTextContent(
      t.checklistHeading,
    );
    expect(screen.getByTestId("getting-started")).toHaveTextContent(
      t.checklistBody,
    );
  });

  it("marks each step done or pending from the same profile fields the profile-status card uses", async () => {
    // Default fixture: verified, fee set, no about text, no clinic name.
    render(<DoctorDashboardPage />);

    await waitFor(() => screen.getByTestId("getting-started"));

    expect(
      within(screen.getByTestId("checklist-step-verified")).getByText(
        t.checklistDone,
      ),
    ).toBeTruthy();
    expect(
      within(screen.getByTestId("checklist-step-fee")).getByText(
        t.checklistDone,
      ),
    ).toBeTruthy();
    expect(
      within(screen.getByTestId("checklist-step-about")).getByText(
        t.checklistPending,
      ),
    ).toBeTruthy();
    expect(
      within(screen.getByTestId("checklist-step-clinic")).getByText(
        t.checklistPending,
      ),
    ).toBeTruthy();
  });

  it("treats an unverified doctor as pending on the verified step", async () => {
    getProfile.mockResolvedValue(doctorProfile({ verified: false }));
    render(<DoctorDashboardPage />);

    await waitFor(() => screen.getByTestId("getting-started"));
    expect(
      within(screen.getByTestId("checklist-step-verified")).getByText(
        t.checklistPending,
      ),
    ).toBeTruthy();
  });

  it("marks every step done when the profile is complete", async () => {
    getProfile.mockResolvedValue(
      doctorProfile({
        verified: true,
        consultation_fee: 50000,
        about: "Twelve years of primary care.",
        clinic_name: "Sunrise Clinic",
      }),
    );
    render(<DoctorDashboardPage />);

    await waitFor(() => screen.getByTestId("getting-started"));

    for (const key of ["verified", "fee", "about", "clinic"]) {
      expect(
        within(screen.getByTestId(`checklist-step-${key}`)).getByText(
          t.checklistDone,
        ),
      ).toBeTruthy();
      expect(screen.getByTestId(`checklist-step-${key}`)).toHaveAttribute(
        "data-done",
        "true",
      );
    }
  });

  it("deep-links each step to the profile section where the doctor completes it", async () => {
    render(<DoctorDashboardPage />);

    await waitFor(() => screen.getByTestId("getting-started"));

    expect(screen.getByTestId("checklist-step-verified")).toHaveAttribute(
      "href",
      "/doctor/profile#profile-section-verified",
    );
    expect(screen.getByTestId("checklist-step-fee")).toHaveAttribute(
      "href",
      "/doctor/profile#profile-section-fee",
    );
    expect(screen.getByTestId("checklist-step-about")).toHaveAttribute(
      "href",
      "/doctor/profile#profile-section-about",
    );
    expect(screen.getByTestId("checklist-step-clinic")).toHaveAttribute(
      "href",
      "/doctor/profile#profile-section-practice",
    );
  });

  it("is absent once the doctor has an open care case", async () => {
    getCases.mockResolvedValue(casesView(caseItem(11)));
    render(<DoctorDashboardPage />);

    await waitFor(() => screen.getByTestId("case-item"));
    expect(screen.queryByTestId("getting-started")).not.toBeInTheDocument();
  });

  it("is absent when the review queue is not empty", async () => {
    getQueue.mockResolvedValue([queueItem()]);
    render(<DoctorDashboardPage />);

    await waitFor(() => screen.getByTestId("queue-item"));
    expect(screen.queryByTestId("getting-started")).not.toBeInTheDocument();
  });

  it("carries the checklist copy into Hindi (REQ-006)", async () => {
    render(<LangFlipHost />);
    await waitFor(() => screen.getByTestId("getting-started"));

    fireEvent.click(screen.getByText("flip-lang"));

    await waitFor(() =>
      expect(screen.getByTestId("getting-started")).toHaveTextContent(
        hiT.checklistHeading,
      ),
    );
    expect(screen.getByText(hiT.checklistStepVerified)).toBeInTheDocument();
    expect(screen.getByText(hiT.checklistStepFee)).toBeInTheDocument();
    expect(screen.getByText(hiT.checklistStepAbout)).toBeInTheDocument();
    expect(screen.getByText(hiT.checklistStepClinic)).toBeInTheDocument();
    // Two steps are done (verified, fee) and two are pending (about, clinic) in
    // the default fixture, so each state label appears twice.
    expect(screen.getAllByText(hiT.checklistDone)).toHaveLength(2);
    expect(screen.getAllByText(hiT.checklistPending)).toHaveLength(2);
  });
});

describe("DoctorDashboardPage greeting (#678)", () => {
  // One seam for the whole suite: the same `greetingTimeText` the component
  // renders, applied to "now". The component <-> test contract is the helper's
  // own boundary tests (dashboardGreeting.test.ts), which drive it with fixed
  // dates and concrete copy, so this suite only pins that the page uses the
  // seam and the right day part.
  const timeGreeting = () => greetingTimeText(t, new Date());

  it("greets the doctor by first name, honorific stripped, with the time of day", async () => {
    getProfile.mockResolvedValue(
      doctorProfile({ practice_name: "Dr. Anil Kumar" }),
    );
    render(<DoctorDashboardPage />);

    // The profile is still loading at first render: a name-free greeting.
    expect(screen.getByTestId("dashboard-greeting")).toHaveTextContent(
      timeGreeting(),
    );
    expect(screen.getByTestId("dashboard-greeting")).not.toHaveTextContent(
      "Anil",
    );

    await waitFor(() =>
      expect(screen.getByTestId("dashboard-greeting")).toHaveTextContent(
        "Anil",
      ),
    );
    expect(screen.getByTestId("dashboard-greeting")).toHaveTextContent(
      timeGreeting(),
    );
    expect(screen.getByTestId("dashboard-greeting")).not.toHaveTextContent(
      "Dr.",
    );
  });

  it("keeps the greeting name-free while the profile read never resolves", () => {
    getProfile.mockReturnValue(new Promise(() => {}));
    render(<DoctorDashboardPage />);

    const greeting = screen.getByTestId("dashboard-greeting");
    expect(greeting).toHaveTextContent(timeGreeting());
    expect(greeting).not.toHaveTextContent("Anil");
    expect(greeting).not.toHaveTextContent("Kumar");
  });

  it("renders today's date beneath the greeting", async () => {
    render(<DoctorDashboardPage />);

    expect(screen.getByTestId("greeting-date")).toHaveTextContent(
      formatGreetingDate(new Date(), "en"),
    );
  });

  it("uses the name-free greeting when the profile read fails", async () => {
    getProfile.mockRejectedValue(new Error("offline"));
    render(<DoctorDashboardPage />);
    await waitFor(() => screen.getByTestId("fee-summary-error"));

    const greeting = screen.getByTestId("dashboard-greeting");
    expect(greeting).toHaveTextContent(timeGreeting());
    expect(greeting).not.toHaveTextContent("Anil");
  });
});

describe("DoctorDashboardPage profile-status card (#678)", () => {
  it("shows the verified verdict, specialty chips and the consultation fee", async () => {
    getProfile.mockResolvedValue(
      doctorProfile({
        practice_name: "Dr. Anil Kumar",
        specialties: ["General Physician", "Dentist"],
        consultation_fee: 50000,
      }),
    );
    render(<DoctorDashboardPage />);
    await waitFor(() => screen.getByTestId("profile-status"));

    const card = screen.getByTestId("profile-status");
    expect(card).toHaveTextContent(t.statusHeading);
    expect(screen.getByTestId("profile-status-verified")).toHaveTextContent(
      STRINGS.en.doctorProfile.verified,
    );
    const chips = screen.getAllByTestId("profile-status-specialty");
    expect(chips).toHaveLength(2);
    expect(chips[0]).toHaveTextContent("General Physician");
    expect(chips[1]).toHaveTextContent("Dentist");
    expect(screen.getByTestId("profile-status-fee")).toHaveTextContent(
      t.feeHeading,
    );
    expect(screen.getByTestId("profile-status-fee")).toHaveTextContent("₹500");
  });

  it("labels the fee as unset and the verdict as not verified when they are", async () => {
    getProfile.mockResolvedValue(
      doctorProfile({ verified: false, specialties: [] }),
    );
    render(<DoctorDashboardPage />);
    await waitFor(() => screen.getByTestId("profile-status"));

    expect(screen.getByTestId("profile-status-verified")).toHaveTextContent(
      STRINGS.en.doctorProfile.notVerified,
    );
    expect(
      screen.queryByTestId("profile-status-specialty"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByTestId("profile-status-specialties-empty"),
    ).toHaveTextContent(STRINGS.en.doctorProfile.noSpecialtiesYet);
  });

  it("lists the missing items as hints - no about text, no clinic name", async () => {
    render(<DoctorDashboardPage />);
    await waitFor(() => screen.getByTestId("profile-status"));

    expect(screen.getByTestId("profile-status-hints")).toBeInTheDocument();
    expect(screen.getByTestId("profile-status-hint-about")).toHaveTextContent(
      t.statusHintNoAbout,
    );
    expect(screen.getByTestId("profile-status-hint-clinic")).toHaveTextContent(
      t.statusHintNoClinic,
    );
    expect(
      screen.queryByTestId("profile-status-hint-unverified"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("profile-status-hint-fee"),
    ).not.toBeInTheDocument();
  });

  it("hints an unverified profile and a missing fee", async () => {
    getProfile.mockResolvedValue(
      doctorProfile({ verified: false, consultation_fee: null }),
    );
    render(<DoctorDashboardPage />);
    await waitFor(() => screen.getByTestId("profile-status"));

    expect(
      screen.getByTestId("profile-status-hint-unverified"),
    ).toHaveTextContent(t.statusHintUnverified);
    expect(screen.getByTestId("profile-status-hint-fee")).toHaveTextContent(
      t.feeUnsetHelp,
    );
  });

  it("shows the complete line when nothing is missing", async () => {
    getProfile.mockResolvedValue(
      doctorProfile({
        verified: true,
        consultation_fee: 50000,
        about: "Twelve years of primary care.",
        clinic_name: "Sunrise Clinic",
      }),
    );
    render(<DoctorDashboardPage />);
    await waitFor(() => screen.getByTestId("profile-status"));

    expect(screen.getByTestId("profile-status-complete")).toHaveTextContent(
      t.statusComplete,
    );
    expect(
      screen.queryByTestId("profile-status-hints"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("profile-status-hint-about"),
    ).not.toBeInTheDocument();
  });

  it("links to the doctor profile to fix the gaps", async () => {
    render(<DoctorDashboardPage />);
    await waitFor(() => screen.getByTestId("profile-status"));

    expect(screen.getByTestId("profile-status-fix")).toHaveAttribute(
      "href",
      "/doctor/profile",
    );
    expect(screen.getByTestId("profile-status-fix")).toHaveTextContent(
      t.statusProfileAction,
    );
  });

  it("drives the greeting and the card from the dashboard's one profile read", async () => {
    getProfile.mockResolvedValue(
      doctorProfile({ practice_name: "Dr. Anil Kumar" }),
    );
    render(<DoctorDashboardPage />);
    await waitFor(() => screen.getByTestId("profile-status"));

    expect(getProfile).toHaveBeenCalledTimes(1);
  });

  it("carries the greeting and the profile-status copy into Hindi", async () => {
    getProfile.mockResolvedValue(
      doctorProfile({ practice_name: "डॉ. अनिल कुमार", verified: false }),
    );
    render(<LangFlipHost />);
    await waitFor(() => screen.getByTestId("profile-status"));

    fireEvent.click(screen.getByText("flip-lang"));
    await waitFor(() =>
      expect(screen.getByTestId("profile-status")).toHaveTextContent(
        hiT.statusHeading,
      ),
    );

    // The greeting strips the Hindi honorific into the first name in Hindi.
    expect(screen.getByTestId("dashboard-greeting")).toHaveTextContent("अनिल");
    expect(
      screen.getByTestId("profile-status-hint-unverified"),
    ).toHaveTextContent(hiT.statusHintUnverified);
    expect(screen.getByTestId("profile-status-fix")).toHaveTextContent(
      hiT.statusProfileAction,
    );
  });
});

describe("DoctorDashboardPage per-section resilient loading (#683)", () => {
  it("shows a skeleton in each section while its read is in flight", () => {
    getQueue.mockReturnValue(new Promise(() => {}));
    getCases.mockReturnValue(new Promise(() => {}));
    render(<DoctorDashboardPage />);

    expect(screen.getByTestId("queue-skeleton")).toBeInTheDocument();
    expect(screen.getByTestId("cases-skeleton")).toBeInTheDocument();
  });

  it("degrades only the failed feed's section, never blanking the page", async () => {
    getQueue.mockRejectedValue(new Error("boom"));
    render(<DoctorDashboardPage />);

    await waitFor(() => screen.getByTestId("queue-error"));
    expect(screen.getByTestId("queue-error")).toHaveTextContent(
      t.queueLoadFailed,
    );
    // The healthy open-cases section still renders and no page banner appears.
    expect(
      within(screen.getByTestId("open-cases")).getByTestId("empty-state"),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("error-banner")).not.toBeInTheDocument();
  });

  it("keeps the review queue when only the cases read fails", async () => {
    getCases.mockRejectedValue(new Error("boom"));
    getQueue.mockResolvedValue([queueItem()]);
    render(<DoctorDashboardPage />);

    await waitFor(() => screen.getByTestId("cases-error"));
    expect(screen.getByTestId("cases-error")).toHaveTextContent(
      t.casesLoadFailed,
    );
    expect(screen.getByTestId("queue-item")).toBeInTheDocument();
    expect(screen.queryByTestId("error-banner")).not.toBeInTheDocument();
  });

  it("retries only the failed section from its own fallback", async () => {
    getCases.mockRejectedValueOnce(new Error("offline"));
    render(<DoctorDashboardPage />);
    await waitFor(() => screen.getByTestId("cases-error"));

    getCases.mockResolvedValue(casesView(caseItem(11)));
    fireEvent.click(screen.getByTestId("cases-retry"));

    await waitFor(() => screen.getByTestId("case-item"));
    expect(getCases).toHaveBeenCalledTimes(2);
    // The scoped retry leaves the healthy queue read alone.
    expect(getQueue).toHaveBeenCalledTimes(1);
  });

  it("retries the review queue from its own fallback", async () => {
    getQueue.mockRejectedValueOnce(new Error("offline"));
    render(<DoctorDashboardPage />);
    await waitFor(() => screen.getByTestId("queue-error"));

    getQueue.mockResolvedValue([queueItem()]);
    fireEvent.click(screen.getByTestId("queue-retry"));

    await waitFor(() => screen.getByTestId("queue-item"));
    expect(getQueue).toHaveBeenCalledTimes(2);
    // The scoped retry leaves the healthy cases read alone.
    expect(getCases).toHaveBeenCalledTimes(1);
  });

  it("carries the per-section failure copy into Hindi (REQ-006)", async () => {
    getQueue.mockRejectedValue(new Error("offline"));
    getCases.mockRejectedValue(new Error("offline"));
    render(<LangFlipHost />);
    await waitFor(() => screen.getByTestId("queue-error"));

    fireEvent.click(screen.getByText("flip-lang"));

    await waitFor(() =>
      expect(screen.getByTestId("queue-error")).toHaveTextContent(
        hiT.queueLoadFailed,
      ),
    );
    expect(screen.getByTestId("cases-error")).toHaveTextContent(
      hiT.casesLoadFailed,
    );
  });
});

describe("DoctorDashboardPage bilingual parity (REQ-006)", () => {
  it("renders the console copy in Hindi when the locale flips", async () => {
    getQueue.mockResolvedValue([queueItem({ patient_name: null })]);
    getCases.mockResolvedValue(casesView(caseItem(11)));
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
    // #678: the generic console title is gone - the greeting is the heading. It
    // reads today's time-of-day greeting in the active locale.
    expect(screen.getByTestId("dashboard-greeting")).toHaveTextContent(
      greetingTimeText(hiT, new Date()),
    );
  });

  it("#676 carries the case card copy into Hindi", async () => {
    getCases.mockResolvedValue(
      casesView(caseItem(11, { forced_review: true })),
    );
    render(<LangFlipHost />);
    await waitFor(() => screen.getByTestId("case-item"));

    fireEvent.click(screen.getByText("flip-lang"));

    await waitFor(() =>
      expect(screen.getByTestId("case-item-patient")).toHaveTextContent(
        "Asha Verma",
      ),
    );
    // The card's own copy ships in Hindi too: the stage chip, the verify chip,
    // the accessible name, and the relative "updated" line.
    expect(screen.getByTestId("case-item-stage")).toHaveTextContent(
      hiT.stagePrescriptionPending,
    );
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

  it("#544 carries the quick actions, fee summary and empty-state bodies into Hindi", async () => {
    getProfile.mockResolvedValue(doctorProfile({ consultation_fee: 50000 }));
    render(<LangFlipHost />);
    await waitFor(() => screen.getByTestId("fee-summary-value"));

    fireEvent.click(screen.getByText("flip-lang"));
    await waitFor(() =>
      expect(screen.getByTestId("fee-summary")).toHaveTextContent(
        hiT.feeHeading,
      ),
    );

    expect(screen.getByTestId("quick-action-patients")).toHaveTextContent(
      STRINGS.hi.nav.patients,
    );
    expect(screen.getByTestId("quick-action-patients")).toHaveTextContent(
      hiT.patientsEntryBody,
    );
    expect(screen.getByTestId("quick-action-cases")).toHaveTextContent(
      hiT.casesIndexTitle,
    );
    expect(screen.getByTestId("quick-action-profile")).toHaveTextContent(
      hiT.profileEntryBody,
    );
    expect(screen.getByTestId("fee-summary")).toHaveTextContent(
      hiT.feeEditAction,
    );
  });

  it("#681 carries the KPI and quick-action copy into Hindi", async () => {
    getPatients.mockResolvedValue(patientsView(4));
    render(<LangFlipHost />);
    await waitFor(() => screen.getByTestId("quick-action-cases"));

    fireEvent.click(screen.getByText("flip-lang"));

    await waitFor(() =>
      expect(screen.getByTestId("kpi-awaiting-review")).toHaveTextContent(
        hiT.kpiAwaitingReview,
      ),
    );
    expect(screen.getByTestId("kpi-current-patients")).toHaveTextContent(
      hiT.kpiCurrentPatients,
    );
    expect(screen.getByTestId("quick-actions")).toHaveTextContent(
      hiT.quickActionsHeading,
    );
    expect(screen.getByTestId("quick-action-cases")).toHaveTextContent(
      hiT.casesEntryBody,
    );
  });
});
