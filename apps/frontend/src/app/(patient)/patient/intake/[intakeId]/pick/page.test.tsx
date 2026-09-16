// PHASE-8.1 T11 (#449): patient pick-a-doctor page suite. Covers the
// symptom-derived suggested specialty as a start-here filter (never a
// blocking verdict, US-2/US-3), the verified card fields incl. fee and
// fee-not-set (US-4/US-10), the consent sheet with an atomic Allow that
// records pick + consent and swaps to confirmation (US-5/US-6/US-9), the
// low-confidence symptom-edit link (US-8), load failure with retry, and
// bilingual EN/HI parity.

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PickDoctorPage from "./page";
import { ApiError } from "@/lib/api-errors";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { __resetLangForTests, useLang } from "@/lib/i18n/LangContext";
import { fetchPreSummary, type PreSummaryView } from "@/lib/intake/api";
import type { DirectoryEntry } from "@/lib/directory/search";

vi.mock("next/navigation", () => ({
  useParams: () => ({ intakeId: "42" }),
}));

vi.mock("next/link", () => {
  return {
    default: ({
      href,
      children,
      ...rest
    }: {
      href: string;
      children: React.ReactNode;
    }) => (
      <a href={href} {...rest}>
        {children}
      </a>
    ),
  };
});

vi.mock("@/lib/intake/api", () => ({
  fetchPreSummary: vi.fn(),
}));

const { searchDirectory } = vi.hoisted(() => ({ searchDirectory: vi.fn() }));

vi.mock("@/lib/directory/search", async (importOriginal) => {
  const original =
    await importOriginal<typeof import("@/lib/directory/search")>();
  return { ...original, searchDirectory };
});

const { pickDoctor } = vi.hoisted(() => ({ pickDoctor: vi.fn() }));

vi.mock("@/lib/pick/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/pick/api")>();
  return { ...original, pickDoctor };
});

const t = STRINGS.en.pick;
const hiT = STRINGS.hi.pick;
const directoryEn = STRINGS.en.directory;
const getPreSummary = vi.mocked(fetchPreSummary);
const search = vi.mocked(searchDirectory);
const pick = vi.mocked(pickDoctor);

function preSummary(overrides: Partial<PreSummaryView> = {}): PreSummaryView {
  return {
    pre_summary_id: 9,
    intake_id: 42,
    structured_fields: {
      chief_complaints: ["fever"],
      symptoms: [],
      duration: null,
    },
    structuring_confidence: 0.82,
    low_confidence: false,
    review_state: "draft",
    patient_edits: null,
    doctor_corrections: null,
    review_attribution: null,
    reviewed_by: null,
    reviewed_at: null,
    created_at: "2026-09-08T10:00:00Z",
    updated_at: "2026-09-08T10:00:00Z",
    ...overrides,
  };
}

function doctor(
  id: number,
  name: string,
  overrides: Partial<DirectoryEntry> = {},
): DirectoryEntry {
  return {
    partner_id: id,
    practice_name: name,
    partner_type: "doctor",
    specialty: "General Physician",
    area: "Medininagar Rd",
    distance_km: id,
    verified: true,
    consultation_fee: 40000,
    ...overrides,
  };
}

function apiError(code: string): ApiError {
  return new ApiError({
    code,
    message: "boom",
    trace_id: "trace-st999001",
    details: {},
  });
}

async function flush() {
  await act(async () => {});
}

async function renderPage() {
  render(<PickDoctorPage />);
  await flush();
}

async function renderWithCards(doctors: DirectoryEntry[]) {
  getPreSummary.mockResolvedValue(preSummary());
  search.mockResolvedValue({ items: doctors, fell_back: false });
  render(<PickDoctorPage />);
  await waitFor(() => screen.getByTestId("pick-cards"));
}

beforeEach(() => {
  __resetLangForTests();
  getPreSummary.mockReset();
  search.mockReset();
  pick.mockReset();
  getPreSummary.mockResolvedValue(preSummary());
  search.mockResolvedValue({ items: [], fell_back: false });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("PickDoctorPage suggested specialty", () => {
  it("derives the suggested specialty from symptoms and pre-filters the directory (US-2)", async () => {
    getPreSummary.mockResolvedValue(
      preSummary({
        structured_fields: {
          chief_complaints: ["child has fever"],
          symptoms: [],
          duration: null,
        },
      }),
    );
    search.mockResolvedValue({
      items: [doctor(1, "Dr. A. Kumar")],
      fell_back: false,
    });
    render(<PickDoctorPage />);
    await waitFor(() => screen.getByTestId("suggested-label"));

    expect(search).toHaveBeenLastCalledWith({
      partnerType: "doctor",
      specialty: "Pediatrician",
    });
    expect(screen.getByTestId("suggested-label")).toHaveTextContent(
      t.suggestedSpecialtyLabel,
    );
  });

  it("shows the suggestion as a start-here filter, not a blocking verdict (US-3)", async () => {
    getPreSummary.mockResolvedValue(
      preSummary({
        structured_fields: {
          chief_complaints: ["child has fever"],
          symptoms: [],
          duration: null,
        },
      }),
    );
    search.mockResolvedValue({ items: [], fell_back: false });
    render(<PickDoctorPage />);
    await waitFor(() => screen.getByTestId("suggestion-note"));

    expect(
      screen.getByTestId("specialty-chip-Pediatrician"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("specialty-chip-all")).toBeInTheDocument();
    expect(screen.getByTestId("suggestion-note")).toHaveTextContent(
      t.suggestionNote,
    );

    fireEvent.click(screen.getByTestId("specialty-chip-all"));
    await waitFor(() =>
      expect(search).toHaveBeenLastCalledWith({
        partnerType: "doctor",
        specialty: null,
      }),
    );
  });

  it("suggests General Physician for an unrelated chief complaint", async () => {
    render(<PickDoctorPage />);
    await waitFor(() =>
      expect(search).toHaveBeenLastCalledWith({
        partnerType: "doctor",
        specialty: "General Physician",
      }),
    );
  });
});

describe("PickDoctorPage cards", () => {
  it("renders verified tick, practice, distance, fee and credentials summary (US-4)", async () => {
    await renderWithCards([doctor(1, "Dr. A. Kumar")]);

    expect(screen.getByTestId("pick-doctor-card")).toBeInTheDocument();
    expect(screen.getByTestId("pick-verified")).toHaveTextContent("Verified");
    expect(
      screen.getByText(
        "General Physician \u00B7 Doctors \u00B7 Medininagar Rd",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("1.0 km")).toBeInTheDocument();
    expect(screen.getByTestId("pick-fee")).toHaveTextContent("\u20B9400");
    expect(screen.getByTestId("pick-credentials")).toHaveTextContent(
      "Verified",
    );
    expect(screen.getByTestId("pick-view-profile")).toHaveAttribute(
      "href",
      "/providers/1",
    );
  });

  it("shows fee-not-set when the doctor has not set a fee and still allows picking (US-10)", async () => {
    await renderWithCards([
      doctor(1, "Dr. A. Kumar", { consultation_fee: null }),
    ]);

    expect(screen.getByTestId("pick-fee")).toHaveTextContent(t.feeNotSet);
    expect(screen.getByTestId("pick-book")).toBeInTheDocument();
  });
});

describe("PickDoctorPage low-confidence pre-summary", () => {
  it("shows a symptom-edit link back to the pre-summary before the pick (US-8)", async () => {
    getPreSummary.mockResolvedValue(preSummary({ low_confidence: true }));
    search.mockResolvedValue({
      items: [doctor(1, "Dr. A. Kumar")],
      fell_back: false,
    });
    render(<PickDoctorPage />);
    await waitFor(() => screen.getByTestId("lowconf-hint"));

    expect(screen.getByTestId("pick-edit-symptoms")).toHaveTextContent(
      t.editSymptoms,
    );
    expect(screen.getByTestId("pick-edit-symptoms")).toHaveAttribute(
      "href",
      "/patient/intake/42/pre-summary",
    );
  });

  it("does not show the edit link on a clean pre-summary", async () => {
    await renderWithCards([doctor(1, "Dr. A. Kumar")]);
    expect(screen.queryByTestId("lowconf-hint")).not.toBeInTheDocument();
  });
});

describe("PickDoctorPage booking + confirmation", () => {
  it("Allow records pick + consent in one step and shows confirmation with what happens next", async () => {
    pick.mockResolvedValue({
      intake_id: 42,
      assigned_partner_id: 1,
      consent_id: 3,
      consent_lineage_ref: "C-42-001",
      consent_version: 1,
    });
    await renderWithCards([doctor(1, "Dr. A. Kumar")]);

    fireEvent.click(screen.getByTestId("pick-book"));
    await screen.findByTestId("pick-consent-title");
    fireEvent.click(screen.getByTestId("pick-consent-allow"));

    await waitFor(() =>
      expect(screen.getByTestId("pick-confirmation")).toBeInTheDocument(),
    );
    expect(pick).toHaveBeenCalledWith(42, 1, expect.any(String));
    expect(screen.getByTestId("pick-confirm-title")).toHaveTextContent(
      t.confirmTitle,
    );
    expect(screen.getByTestId("pick-confirm-doctor")).toHaveTextContent(
      "Dr. A. Kumar",
    );
    expect(screen.getByTestId("pick-confirm-fee")).toHaveTextContent(
      "\u20B9400",
    );
    expect(screen.getByTestId("pick-confirm-next")).toHaveTextContent(
      t.whatHappensNextItems,
    );
  });

  it("confirmation links back to the intake status", async () => {
    pick.mockResolvedValue({
      intake_id: 42,
      assigned_partner_id: 1,
      consent_id: 3,
      consent_lineage_ref: "C-42-001",
      consent_version: 1,
    });
    await renderWithCards([doctor(1, "Dr. A. Kumar")]);

    fireEvent.click(screen.getByTestId("pick-book"));
    await screen.findByTestId("pick-consent-title");
    fireEvent.click(screen.getByTestId("pick-consent-allow"));
    await waitFor(() =>
      expect(screen.getByTestId("pick-confirmation")).toBeInTheDocument(),
    );

    expect(screen.getByTestId("btn-case-status")).toHaveAttribute(
      "href",
      "/patient/intake/42/status",
    );
  });
});

describe("PickDoctorPage failure paths", () => {
  it("surfaces a retryable error when the pre-summary fails to load", async () => {
    getPreSummary.mockRejectedValue(apiError("INTERNAL_ERROR"));
    render(<PickDoctorPage />);
    await flush();
    await waitFor(() => screen.getByTestId("error-banner"));
  });

  it("surfaces a retryable error when the directory search fails", async () => {
    search.mockRejectedValue(apiError("INTERNAL_ERROR"));
    render(<PickDoctorPage />);
    await waitFor(() => screen.getByTestId("pick-error"));
  });

  it("retries the doctor list from the directory error state", async () => {
    search.mockRejectedValueOnce(apiError("INTERNAL_ERROR"));
    search.mockResolvedValueOnce({
      items: [doctor(1, "Dr. A. Kumar")],
      fell_back: false,
    });
    render(<PickDoctorPage />);
    await waitFor(() => screen.getByTestId("pick-error"));

    fireEvent.click(screen.getByRole("button", { name: t.retry }));
    await waitFor(() => screen.getByTestId("pick-cards"));
  });
});

describe("PickDoctorPage bilingual parity (REQ-006)", () => {
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
        <PickDoctorPage />
      </>
    );
  }

  it("renders the pick copy in Hindi when the locale flips", async () => {
    search.mockResolvedValue({
      items: [
        doctor(1, "\u0921\u0949. \u090F. \u0915\u0941\u092E\u093E\u0930"),
      ],
      fell_back: false,
    });
    render(<LangFlipHost />);
    await waitFor(() => screen.getByTestId("pick-cards"));

    fireEvent.click(screen.getByText("flip-lang"));
    await waitFor(() =>
      expect(screen.getByTestId("pick-book")).toHaveTextContent(hiT.bookCta),
    );
    expect(screen.getByText(hiT.subtitle)).toBeInTheDocument();
  });
});
