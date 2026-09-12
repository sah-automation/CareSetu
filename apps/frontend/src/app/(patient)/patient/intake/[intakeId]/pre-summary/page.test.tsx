// PHASE-7 T18 (#362): pre-summary review page suite - the clean variant (honesty
// cue "AI draft - doctor will verify", never "AI diagnosis" per ADR-0001;
// structuring confidence value + light indicator; structured fields as
// read-only cards; edit/save/cancel; confirm -> continuation CTA toward
// consultation booking), the low-confidence variant (calm amber
// doctor-must-check notice + forced-review framing, amber-not-red, low-tag on
// the fields card, "Continue to consultation" + verify book sub), patient
// edits persisting via the save-edits route and rendering as corrections
// (only changed fields sent; existing patient_edits render as corrected), load
// failure paths with trace id + retry, the degraded raw-doctor-review surface
// (#389: ready_for_review + INTAKE_NOT_FOUND on first load and mid-poll, raw
// text or recording-shared evidence, no confirm affordance, live refresh into
// the ready state), and bilingual EN/HI. The intake API is
// mocked at the seam (the client smoke-tests the real route contracts).

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PreSummaryReviewPage from "./page";
import PatientGroupLayout from "@/app/(patient)/layout";
import { ApiError } from "@/lib/api-errors";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { __resetLangForTests, useLang } from "@/lib/i18n/LangContext";
import {
  fetchIntake,
  fetchPreSummary,
  savePatientEdits,
  type PreSummaryView,
  type StructuredFields,
} from "@/lib/intake/api";

vi.mock("next/navigation", () => ({
  useParams: () => ({ intakeId: "42" }),
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/patient/intake/42/pre-summary",
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

vi.mock("@/lib/auth/AuthContext", () => ({
  useAuth: () => ({
    user: { id: 7, phone: "+911234567890", roles: ["patient"] },
    selectedRole: "patient",
    switchRole: vi.fn(),
    logout: vi.fn(),
    isAuthenticated: true,
    isLoading: false,
  }),
}));

vi.mock("@/lib/intake/api", () => ({
  fetchPreSummary: vi.fn(),
  fetchIntake: vi.fn(),
  savePatientEdits: vi.fn(),
}));

const t = STRINGS.en.intake.preSummary;
const hiT = STRINGS.hi.intake.preSummary;
const getSummary = vi.mocked(fetchPreSummary);
const getIntake = vi.mocked(fetchIntake);
const saveEdits = vi.mocked(savePatientEdits);

function preSummary(overrides: Partial<PreSummaryView> = {}): PreSummaryView {
  return {
    pre_summary_id: 9,
    intake_id: 42,
    structured_fields: {
      chief_complaints: ["fever", "dry cough"],
      symptoms: ["fever since 2 days", "dry cough persistent"],
      duration: "2 days",
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

function intakeDetail(overrides: Record<string, unknown> = {}) {
  return {
    intake_id: 42,
    patient_id: 7,
    mode: "voice" as const,
    language: "en" as const,
    status: "structuring" as const,
    record_attempts: 1,
    text: null,
    transcript: null,
    transcript_usability: null,
    forced_text: false,
    media_refs: [],
    created_at: "2026-09-08T10:00:00Z",
    updated_at: "2026-09-08T10:00:00Z",
    ...overrides,
  };
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
      <PreSummaryReviewPage />
    </>
  );
}

async function flush() {
  await act(async () => {});
}

async function renderLoaded(overrides: Partial<PreSummaryView> = {}) {
  getSummary.mockResolvedValue(preSummary(overrides));
  render(<PreSummaryReviewPage />);
  await flush();
}

beforeEach(() => {
  __resetLangForTests();
  getSummary.mockReset();
  getIntake.mockReset();
  // Safe default so bare renders (which don't call renderLoaded) don't
  // blow up on .then(undefined). Individual tests still override as needed.
  getSummary.mockResolvedValue(preSummary());
  saveEdits.mockReset();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("PreSummaryReviewPage (inside the patient shell)", () => {
  it("mounts within the patient AppShell", async () => {
    render(
      <PatientGroupLayout>
        <PreSummaryReviewPage />
      </PatientGroupLayout>,
    );
    await flush();
    expect(screen.getByTestId("app-shell")).toBeInTheDocument();
  });
});

describe("PreSummaryReviewPage clean variant (FEAT-007 happy path)", () => {
  it("shows the honesty cue, confidence value + indicator, and structured fields", async () => {
    await renderLoaded();

    // Honesty cue - always "AI draft - doctor will verify", never "AI
    // diagnosis" (ADR-0001).
    expect(screen.getByTestId("honesty-banner")).toBeInTheDocument();
    expect(screen.getByTestId("honesty-cue")).toHaveTextContent(t.bannerLine1);

    expect(screen.getByTestId("confidence-value")).toHaveTextContent("0.82");
    expect(screen.getByTestId("confidence-bar-fill")).toHaveStyle({
      width: "82%",
    });

    // Structured fields from the DTO render as read-only rows.
    expect(screen.getByTestId("field-row-chief_complaints")).toHaveTextContent(
      "Chief complaints",
    );
    expect(
      screen.getByTestId("field-value-chief_complaints"),
    ).toHaveTextContent("fever, dry cough");
    expect(screen.getByTestId("field-value-duration")).toHaveTextContent(
      "2 days",
    );

    // No low-confidence framing on the clean path.
    expect(screen.queryByTestId("lowconf-banner")).not.toBeInTheDocument();
    expect(screen.queryByTestId("low-tag")).not.toBeInTheDocument();
  });

  it("never says 'AI diagnosis' anywhere on the page", async () => {
    await renderLoaded();
    expect(screen.getByTestId("pre-summary-page").textContent).not.toMatch(
      /AI diagnosis/i,
    );
  });

  it("toggles to inputs, discards on cancel, and saves only-changed edits as corrections", async () => {
    await renderLoaded();

    fireEvent.click(screen.getByTestId("btn-edit"));
    expect(screen.getByTestId("field-input-duration")).toBeInTheDocument();
    expect(screen.getByTestId("btn-save")).toBeDisabled();

    fireEvent.change(screen.getByTestId("field-input-duration"), {
      target: { value: "3 days" },
    });
    expect(screen.getByTestId("btn-save")).not.toBeDisabled();

    // Cancel discards the draft.
    fireEvent.click(screen.getByTestId("btn-cancel"));
    expect(
      screen.queryByTestId("field-input-duration"),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("field-value-duration")).toHaveTextContent(
      "2 days",
    );

    // Edit again, change one field, save: only the diff is posted.
    fireEvent.click(screen.getByTestId("btn-edit"));
    fireEvent.change(screen.getByTestId("field-input-duration"), {
      target: { value: "3 days" },
    });
    saveEdits.mockResolvedValue({
      intake_id: 42,
      pre_summary_id: 9,
      patient_edits: { duration: "3 days" },
    });
    fireEvent.click(screen.getByTestId("btn-save"));
    await flush();

    expect(saveEdits).toHaveBeenCalledWith(42, { duration: "3 days" });
    expect(screen.getByTestId("correction-tag-duration")).toHaveTextContent(
      t.correctionsTag,
    );
    expect(screen.getByTestId("field-value-duration")).toHaveTextContent(
      "3 days",
    );
    expect(
      screen.queryByTestId("correction-tag-chief_complaints"),
    ).not.toBeInTheDocument();
  });

  it("shows corrections already persisted on load (patient_edits render as corrections)", async () => {
    await renderLoaded({
      patient_edits: { duration: "3 days" },
    });

    expect(screen.getByTestId("correction-tag-duration")).toHaveTextContent(
      t.correctionsTag,
    );
    expect(screen.getByTestId("field-value-duration")).toHaveTextContent(
      "3 days",
    );
    // Uncorrected AI fields stay uncorrected.
    expect(
      screen.queryByTestId("correction-tag-chief_complaints"),
    ).not.toBeInTheDocument();
  });

  it("confirm opens the continuation CTA toward consultation booking", async () => {
    await renderLoaded();

    fireEvent.click(screen.getByTestId("btn-confirm"));

    const zone = screen.getByTestId("confirmed-zone");
    expect(zone).toBeInTheDocument();
    expect(screen.getByTestId("done-line")).toHaveTextContent(t.doneClean);
    expect(screen.getByTestId("btn-book")).toHaveAttribute(
      "href",
      "/doctors?intake=42",
    );
    expect(screen.getByTestId("book-sub")).toHaveTextContent(t.bookSub);
  });
});

describe("PreSummaryReviewPage low-confidence variant (FEAT-007 scenario 2)", () => {
  it("shows the calm amber doctor-must-check notice with forced-review framing", async () => {
    await renderLoaded({
      structuring_confidence: 0.54,
      low_confidence: true,
    });

    const banner = screen.getByTestId("lowconf-banner");
    expect(banner).toHaveTextContent(t.lowBannerLine1);
    expect(screen.getByTestId("lowconf-verify")).toHaveTextContent(
      t.lowVerifyLine,
    );
    expect(screen.getByTestId("low-tag")).toHaveTextContent(t.lowTag);
    expect(screen.getByTestId("confidence-value")).toHaveTextContent("0.54");

    // Never red: the notice lives on the warn (amber) surface, not danger.
    expect(banner.className).toContain("warn-soft");
    expect(banner.className).not.toContain("danger");
  });

  it("uses the amber notice as the sole framing on low confidence", async () => {
    await renderLoaded({ low_confidence: true });
    // Binding pre-summary-low-confidence.html copy spec: the amber notice
    // replaces the separate honesty banner - never an "AI diagnosis" label
    // anywhere, the amber framing itself carries the honesty.
    expect(screen.queryByTestId("honesty-banner")).not.toBeInTheDocument();
    expect(screen.queryByTestId("honesty-cue")).not.toBeInTheDocument();
    expect(screen.getByTestId("lowconf-banner")).toBeInTheDocument();
  });

  it("offers continuation with doctor-will-verify framing", async () => {
    await renderLoaded({ low_confidence: true });

    expect(screen.getByTestId("btn-confirm")).toHaveTextContent(
      t.confirmBtnLow,
    );
    fireEvent.click(screen.getByTestId("btn-confirm"));
    expect(screen.getByTestId("done-line")).toHaveTextContent(t.doneLow);
    expect(screen.getByTestId("book-sub")).toHaveTextContent(t.bookSubLow);
    expect(screen.getByTestId("btn-book")).toHaveAttribute(
      "href",
      "/doctors?intake=42",
    );
  });
});

describe("PreSummaryReviewPage failure and edge cases", () => {
  it("shows a trace-id error banner when the pre-summary fails to load, and retries", async () => {
    const apiError = new ApiError({
      code: "INTERNAL_ERROR",
      message: "boom",
      trace_id: "trace-ps012345",
      details: {},
    });
    getSummary.mockRejectedValueOnce(apiError);
    render(<PreSummaryReviewPage />);
    await flush();

    expect(screen.getByTestId("error-banner")).toHaveTextContent(
      t.loadFailedTitle,
    );
    expect(screen.getByTestId("error-banner-trace-id")).toHaveTextContent(
      "trace-ps012345",
    );

    getSummary.mockResolvedValue(preSummary());
    fireEvent.click(screen.getByTestId("error-banner-retry"));
    await flush();

    expect(screen.getByTestId("honesty-banner")).toBeInTheDocument();
    expect(getSummary).toHaveBeenCalledTimes(2);
  });

  it("renders the empty structured-fields state without crashing", async () => {
    await renderLoaded({ structured_fields: {} as StructuredFields });
    expect(screen.getByTestId("fields-empty")).toHaveTextContent(t.emptyTitle);
  });

  it("shows the save-failure banner and retries the same save", async () => {
    await renderLoaded();
    fireEvent.click(screen.getByTestId("btn-edit"));
    fireEvent.change(screen.getByTestId("field-input-duration"), {
      target: { value: "3 days" },
    });

    saveEdits.mockRejectedValueOnce(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "trace-psabc999",
        details: {},
      }),
    );
    fireEvent.click(screen.getByTestId("btn-save"));
    await flush();

    expect(screen.getByTestId("error-banner")).toHaveTextContent(
      t.saveFailedTitle,
    );
    expect(screen.getByTestId("error-banner-trace-id")).toHaveTextContent(
      "trace-psabc999",
    );

    saveEdits.mockResolvedValue({
      intake_id: 42,
      pre_summary_id: 9,
      patient_edits: { duration: "3 days" },
    });
    fireEvent.click(screen.getByTestId("error-banner-retry"));
    await flush();

    expect(saveEdits).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("correction-tag-duration")).toBeInTheDocument();
  });

  it("reads the intake id from the route params and fetches that pre-summary", async () => {
    getSummary.mockResolvedValue(preSummary());
    render(<PreSummaryReviewPage />);
    await flush();
    expect(getSummary).toHaveBeenCalledWith(42);
  });
});

describe("PreSummaryReviewPage still-processing poll state (issue 2: 404 race)", () => {
  const notFound = new ApiError({
    code: "INTAKE_NOT_FOUND",
    message: "not found",
    trace_id: "",
    details: {},
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("enters the still-processing state on 404 while structuring, then resolves when the pipeline finishes", async () => {
    vi.useFakeTimers();
    getSummary.mockRejectedValueOnce(notFound).mockResolvedValue(preSummary());
    getIntake.mockResolvedValue(intakeDetail({ status: "structuring" }));

    render(<PreSummaryReviewPage />);
    await flush();

    // The row does not exist yet: the page shows the calm preparing state
    // instead of an error banner, and the intake detail was consulted.
    expect(screen.getByTestId("load-processing")).toHaveTextContent(
      t.processingTitle,
    );
    expect(screen.queryByTestId("error-banner")).not.toBeInTheDocument();
    expect(getIntake).toHaveBeenCalledWith(42);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    expect(screen.getByTestId("honesty-banner")).toBeInTheDocument();
    expect(getSummary).toHaveBeenCalledTimes(2);
  });

  it("waits for the pre-summary past the voice/text page handoff window", async () => {
    vi.useFakeTimers();
    // 404s for the first 14 polls (structuring), then the row appears.
    getSummary
      .mockRejectedValueOnce(notFound) // initial load
      .mockRejectedValueOnce(notFound) // poll 1
      .mockRejectedValueOnce(notFound) // poll 2
      .mockResolvedValue(preSummary()); // poll 3
    getIntake.mockResolvedValue(intakeDetail({ status: "structuring" }));

    render(<PreSummaryReviewPage />);
    await flush();
    expect(screen.getByTestId("load-processing")).toBeInTheDocument();

    for (let i = 0; i < 3; i += 1) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2000);
      });
    }

    expect(screen.getByTestId("honesty-banner")).toBeInTheDocument();
    expect(getSummary).toHaveBeenCalledTimes(4);
  });

  it("shows the timeout banner when the pre-summary never appears after all polls", async () => {
    vi.useFakeTimers();
    getSummary.mockRejectedValue(notFound);
    getIntake.mockResolvedValue(intakeDetail({ status: "structuring" }));

    render(<PreSummaryReviewPage />);
    await flush();
    expect(screen.getByTestId("load-processing")).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(15 * 2000 + 100);
    });

    const banner = screen.getByTestId("error-banner");
    expect(banner).toHaveTextContent(t.processingFailedTitle);
    expect(screen.queryByTestId("load-processing")).not.toBeInTheDocument();
  });

  it("shows the load-failure banner when the intake has already failed", async () => {
    getSummary.mockRejectedValueOnce(notFound);
    getIntake.mockResolvedValue(intakeDetail({ status: "failed" }));

    render(<PreSummaryReviewPage />);
    await flush();

    expect(screen.getByTestId("error-banner")).toHaveTextContent(
      t.loadFailedTitle,
    );
    expect(getSummary).toHaveBeenCalledTimes(1);
  });

  it("enters the still-processing state when the intake is still captured", async () => {
    getSummary.mockRejectedValueOnce(notFound);
    getIntake.mockResolvedValue(intakeDetail({ status: "captured" }));

    render(<PreSummaryReviewPage />);
    await flush();

    expect(screen.getByTestId("load-processing")).toBeInTheDocument();
    expect(screen.queryByTestId("error-banner")).not.toBeInTheDocument();
  });
});

describe("PreSummaryReviewPage degraded raw doctor review surface (#389)", () => {
  const notFound = new ApiError({
    code: "INTAKE_NOT_FOUND",
    message: "not found",
    trace_id: "",
    details: {},
  });
  const readyIntake = (overrides: Record<string, unknown> = {}) =>
    intakeDetail({ status: "ready_for_review", ...overrides });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders the doctor-reviews-directly surface (not the error banner) on first load for a text intake", async () => {
    getSummary.mockRejectedValueOnce(notFound);
    getIntake.mockResolvedValue(
      readyIntake({
        mode: "text",
        text: "fever since 2 days and a dry cough",
      }),
    );

    render(<PreSummaryReviewPage />);
    await flush();

    expect(screen.getByTestId("degraded-surface")).toBeInTheDocument();
    // The degraded state never shows a technical error surface.
    expect(screen.queryByTestId("error-banner")).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("error-banner-trace-id"),
    ).not.toBeInTheDocument();
    // Evidence under review: the raw symptom text for a text intake.
    expect(screen.getByTestId("degraded-evidence-text")).toHaveTextContent(
      "fever since 2 days and a dry cough",
    );
    // Patient-language explanation that the doctor reviews directly.
    expect(screen.getByTestId("degraded-note")).toHaveTextContent(
      t.degradedBody,
    );
    // Live refresh so the patient is notified when the doctor acts.
    expect(screen.getByTestId("degraded-refresh")).toHaveTextContent(
      t.degradedRefresh,
    );
    // Links back to the status page.
    expect(screen.getByTestId("btn-degraded-status")).toHaveAttribute(
      "href",
      "/patient/intake/42/status",
    );
    // No confirm / continue-to-consultation affordance in the degraded state.
    expect(screen.queryByTestId("btn-confirm")).not.toBeInTheDocument();
    expect(screen.queryByTestId("confirmed-zone")).not.toBeInTheDocument();
  });

  it("shows the recording-shared confirmation for a voice intake, not the raw text", async () => {
    getSummary.mockRejectedValueOnce(notFound);
    getIntake.mockResolvedValue(readyIntake({ mode: "voice" }));

    render(<PreSummaryReviewPage />);
    await flush();

    expect(screen.getByTestId("degraded-surface")).toBeInTheDocument();
    expect(screen.getByTestId("degraded-evidence-voice")).toHaveTextContent(
      t.degradedVoiceNote,
    );
    expect(
      screen.queryByTestId("degraded-evidence-text"),
    ).not.toBeInTheDocument();
  });

  it("enters the degraded surface from the poll loop when the intake flips to ready_for_review, not the took-too-long banner", async () => {
    vi.useFakeTimers();
    getSummary.mockRejectedValue(notFound);
    getIntake
      .mockResolvedValueOnce(intakeDetail({ status: "structuring" }))
      .mockResolvedValue(readyIntake());

    render(<PreSummaryReviewPage />);
    await flush();
    expect(screen.getByTestId("load-processing")).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    expect(screen.getByTestId("degraded-surface")).toBeInTheDocument();
    expect(screen.queryByTestId("load-processing")).not.toBeInTheDocument();
    expect(screen.queryByTestId("error-banner")).not.toBeInTheDocument();
  });

  it("flips to the ready summary when the doctor acts and the pre-summary row appears (live refresh)", async () => {
    vi.useFakeTimers();
    getSummary.mockRejectedValueOnce(notFound).mockResolvedValue(preSummary());
    getIntake.mockResolvedValue(readyIntake({ mode: "text", text: "fever" }));

    render(<PreSummaryReviewPage />);
    await flush();
    expect(screen.getByTestId("degraded-surface")).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    expect(screen.getByTestId("honesty-banner")).toBeInTheDocument();
    expect(screen.queryByTestId("degraded-surface")).not.toBeInTheDocument();
    expect(getSummary).toHaveBeenCalledTimes(2);
  });

  it("renders the degraded copy in Hindi when the locale flips", async () => {
    getSummary.mockRejectedValueOnce(notFound);
    getIntake.mockResolvedValue(readyIntake({ mode: "text", text: "बुखार" }));

    render(<LangFlipHost />);
    await flush();
    expect(screen.getByTestId("degraded-surface")).toBeInTheDocument();

    fireEvent.click(screen.getByText("flip-lang"));
    await flush();

    expect(screen.getByTestId("degraded-note")).toHaveTextContent(
      hiT.degradedBody,
    );
    expect(screen.getByTestId("btn-degraded-status")).toHaveTextContent(
      hiT.degradedStatusLink,
    );
  });
});

describe("PreSummaryReviewPage bilingual EN/HI (REQ-006)", () => {
  it("renders all visible copy in Hindi when the locale flips", async () => {
    getSummary.mockResolvedValue(preSummary());
    render(<LangFlipHost />);
    await flush();

    fireEvent.click(screen.getByText("flip-lang"));
    await flush();

    expect(screen.getByTestId("honesty-cue")).toHaveTextContent(
      hiT.bannerLine1,
    );
    expect(screen.getByTestId("confidence-value")).toHaveTextContent("0.82");
    expect(screen.getByText(hiT.groupTitle)).toBeInTheDocument();
    expect(screen.getByTestId("btn-edit")).toHaveTextContent(hiT.editBtn);
    expect(screen.getByTestId("btn-confirm")).toHaveTextContent(hiT.confirmBtn);
  });
});
