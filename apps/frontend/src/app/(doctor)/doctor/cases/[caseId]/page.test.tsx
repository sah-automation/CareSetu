// PHASE-8.1 T13/T14/T15 (#451/#452/#453): case workspace route
// (/doctor/cases/[caseId]) suite. Covers: the stage chip for open stages
// (US-15), the forced-review requirement when the case demands one, the
// consented health history, the consult-complete handshake for pre_summary-
// stage cases (US-24), the closed terminal state, prescription drafting
// (US-18/#452: request AI draft, edit items, save revision, refresh-reload
// from the working-rx read, drafting-cap error), approval/rejection/closure
// (US-19..22/#453: declaration-gated approve + issued rx view, reject with a
// recorded reason, close-without-prescription to Closed), load failure with
// retry, and bilingual EN/HI parity (REQ-006). Every care mutation still
// emits the Idempotency-Key header - asserted at the client level in
// lib/care/api.test.ts.

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

import CaseWorkspacePage from "./page";
import { ApiError } from "@/lib/api-errors";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { __resetLangForTests, useLang } from "@/lib/i18n/LangContext";
import {
  approvePrescription,
  closeCaseWithoutRx,
  createRxDraft,
  fetchCareCase,
  fetchWorkingPrescription,
  markConsultComplete,
  rejectPrescription,
  saveRxRevision,
  submitDoctorInput,
  type CareCaseStage,
  type CaseDetailView,
  type DoctorInputResult,
  type PrescriptionDetailView,
} from "@/lib/care/api";
import {
  fetchIntakeDetailForDoctor,
  fetchIntakeMediaBlob,
  fetchPreSummaryForReview,
  uploadDoctorMedia,
  type IntakeDetailView,
  type MediaRefView,
  type MediaUploadRef,
  type PreSummaryView,
} from "@/lib/intake/api";
import { fetchPartnerMe, type PartnerMeView } from "@/lib/partner/api";
import { readConsentedHistory, type RecordTimeline } from "@/lib/record/api";

vi.mock("next/navigation", () => ({
  useParams: () => ({ caseId: "11" }),
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

vi.mock("@/lib/care/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/care/api")>();
  return {
    ...mod,
    fetchCareCase: vi.fn(),
    markConsultComplete: vi.fn(),
    fetchWorkingPrescription: vi.fn(),
    createRxDraft: vi.fn(),
    saveRxRevision: vi.fn(),
    submitDoctorInput: vi.fn(),
    approvePrescription: vi.fn(),
    rejectPrescription: vi.fn(),
    closeCaseWithoutRx: vi.fn(),
  };
});

vi.mock("@/lib/partner/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/partner/api")>();
  return { ...mod, fetchPartnerMe: vi.fn() };
});

vi.mock("@/lib/intake/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/intake/api")>();
  return {
    ...mod,
    fetchIntakeDetailForDoctor: vi.fn(),
    fetchPreSummaryForReview: vi.fn(),
    fetchIntakeMediaBlob: vi.fn(),
    uploadDoctorMedia: vi.fn(),
  };
});

vi.mock("@/lib/record/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/record/api")>();
  return { ...mod, readConsentedHistory: vi.fn() };
});

const t = STRINGS.en.caseWorkspace;
const consoleT = STRINGS.en.doctorConsole;
const hiT = STRINGS.hi.caseWorkspace;
const getCase = vi.mocked(fetchCareCase);
const doHandshake = vi.mocked(markConsultComplete);
const getMe = vi.mocked(fetchPartnerMe);
const getHistory = vi.mocked(readConsentedHistory);
const getWorkingRx = vi.mocked(fetchWorkingPrescription);
const doDraft = vi.mocked(createRxDraft);
const doSaveRevision = vi.mocked(saveRxRevision);
const doSubmitDoctorInput = vi.mocked(submitDoctorInput);
const doUploadDoctorMedia = vi.mocked(uploadDoctorMedia);
const doApprove = vi.mocked(approvePrescription);
const doReject = vi.mocked(rejectPrescription);
const doCloseCase = vi.mocked(closeCaseWithoutRx);
const getIntakeDetail = vi.mocked(fetchIntakeDetailForDoctor);
const getPreSummary = vi.mocked(fetchPreSummaryForReview);
const getMediaBlob = vi.mocked(fetchIntakeMediaBlob);

function caseItem(
  id: number,
  overrides: Partial<CaseDetailView> = {},
): CaseDetailView {
  const { stage, ...rest } = overrides;
  return {
    case_id: id,
    patient_id: 3,
    doctor_id: 7,
    pre_summary_id: 7,
    stage: (stage ?? "pre_summary") as CareCaseStage,
    forced_review: false,
    closed_at: null,
    close_reason: null,
    created_at: "2026-09-12T10:00:00Z",
    updated_at: "2026-09-12T10:00:00Z",
    ...rest,
  };
}

function me(): PartnerMeView {
  return {
    partner_id: 7,
    status: "Active",
    partner_type: "doctor",
    round: 0,
  };
}

function timeline(): RecordTimeline {
  return {
    record_id: 1,
    patient_id: 3,
    created_at: "2026-01-01T00:00:00Z",
    entries: [
      {
        entry_id: 11,
        entry_type: "prescription",
        payload: {},
        occurred_at: "2026-09-01T00:00:00Z",
        created_at: "2026-09-01T00:00:00Z",
      },
    ],
  };
}

function prescription(
  overrides: Partial<PrescriptionDetailView> = {},
): PrescriptionDetailView {
  return {
    prescription_id: 21,
    case_id: 11,
    status: "doctor_reviewed",
    source: "ai_draft",
    attempt_no: 1,
    draft_snapshot: { rx_items: [] },
    issued_at: null,
    attributed_doctor: 7,
    attributed_doctor_name: null,
    items: [
      {
        rx_item_id: 31,
        prescription_id: 21,
        sequence: 1,
        name: "Paracetamol",
        dose: "500mg",
        duration: "3 days",
        frequency: "3 times daily",
      },
    ],
    created_at: "2026-09-13T00:00:00Z",
    updated_at: "2026-09-13T00:00:00Z",
    ...overrides,
  };
}

function rxItem(
  id: number,
  overrides: Partial<PrescriptionDetailView["items"][number]> = {},
): PrescriptionDetailView["items"][number] {
  return {
    rx_item_id: id,
    prescription_id: 21,
    sequence: 1,
    name: "Paracetamol",
    dose: "500mg",
    duration: "3 days",
    frequency: "3 times daily",
    ...overrides,
  };
}

function noDraftError(): ApiError {
  return new ApiError({
    code: "CARE_NOT_FOUND",
    message: "no working revision",
    trace_id: "t-rx-none",
    details: {},
  });
}

function mediaRef(overrides: Partial<MediaRefView> = {}): MediaRefView {
  return {
    media_ref_id: 302,
    media_type: "audio/mpeg",
    object_key: "in/5/302.mp3",
    audio_duration_ms: 17090,
    file_size_bytes: 132096,
    record_attempt: 2,
    ...overrides,
  };
}

function uploadTicket(overrides: Partial<MediaUploadRef> = {}): MediaUploadRef {
  return {
    object_key: "rx_input/7/opaque.enc",
    media_type: "audio/mpeg",
    audio_duration_ms: null,
    file_size_bytes: 4000,
    record_attempt: 1,
    ...overrides,
  };
}

function doctorInput(
  overrides: Partial<DoctorInputResult> = {},
): DoctorInputResult {
  return {
    input_id: 41,
    case_id: 11,
    input_type: "voice",
    media_ref: "rx_input/7/opaque.enc",
    sensitive_class: null,
    ...overrides,
  };
}

function intakeDetail(
  overrides: Partial<IntakeDetailView> = {},
): IntakeDetailView {
  return {
    intake_id: 5,
    patient_id: 3,
    mode: "voice",
    language: "hi",
    status: "ready_for_review",
    record_attempts: 2,
    text: null,
    transcript: "मुझे लगातार सिरदर्द रहता है।",
    transcript_usability: "ok",
    forced_text: false,
    media_refs: [],
    created_at: "2026-09-12T10:00:00Z",
    updated_at: "2026-09-12T11:00:00Z",
    ...overrides,
  };
}

function preSummary(overrides: Partial<PreSummaryView> = {}): PreSummaryView {
  return {
    pre_summary_id: 7,
    intake_id: 5,
    structured_fields: {
      chief_complaints: ["Fever"],
      symptoms: ["Headache"],
      duration: "3 days",
    },
    structuring_confidence: 0.44,
    low_confidence: true,
    review_state: "final",
    patient_edits: null,
    doctor_corrections: null,
    review_attribution: "dr-42",
    reviewed_by: 7,
    reviewed_at: "2026-09-12T12:00:00Z",
    created_at: "2026-09-12T10:00:00Z",
    updated_at: "2026-09-12T12:00:00Z",
    ...overrides,
  };
}

function resolveLoaded() {
  getCase.mockResolvedValue(caseItem(11));
  getMe.mockResolvedValue(me());
  getHistory.mockResolvedValue(timeline());
  getWorkingRx.mockResolvedValue(prescription());
  getIntakeDetail.mockResolvedValue(intakeDetail());
  getPreSummary.mockResolvedValue(preSummary());
}

beforeEach(() => {
  resolveLoaded();
  doUploadDoctorMedia.mockResolvedValue(uploadTicket());
  doSubmitDoctorInput.mockResolvedValue(doctorInput());
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
  __resetLangForTests();
});

function attachFileToTestId(testid: string, fileName: string, mime: string) {
  const input = screen.getByTestId(testid) as HTMLInputElement;
  fireEvent.change(input, {
    target: { files: [new File(["clip"], fileName, { type: mime })] },
  });
}

describe("CaseWorkspacePage stage + forced review (US-15)", () => {
  it("renders the case stage chip for the pre-summary stage", async () => {
    render(<CaseWorkspacePage />);
    await waitFor(() => screen.getByTestId("case-content"));

    expect(screen.getByTestId("stage-chip")).toHaveTextContent(
      consoleT.stagePreSummary,
    );
  });

  it("renders the prescription-pending stage chip", async () => {
    getCase.mockResolvedValue(caseItem(11, { stage: "prescription_pending" }));
    render(<CaseWorkspacePage />);
    await waitFor(() => screen.getByTestId("case-content"));

    expect(screen.getByTestId("stage-chip")).toHaveTextContent(
      consoleT.stagePrescriptionPending,
    );
  });

  it("shows the forced-review requirement when the case demands one", async () => {
    getCase.mockResolvedValue(caseItem(11, { forced_review: true }));
    render(<CaseWorkspacePage />);
    await waitFor(() => screen.getByTestId("case-content"));

    expect(screen.getByTestId("forced-review-banner")).toHaveTextContent(
      t.forcedReviewChip,
    );
  });

  it("omits the forced-review banner when review is not required", async () => {
    render(<CaseWorkspacePage />);
    await waitFor(() => screen.getByTestId("case-content"));

    expect(
      screen.queryByTestId("forced-review-banner"),
    ).not.toBeInTheDocument();
  });
});

describe("CaseWorkspacePage consented history", () => {
  it("reads the consented history for the case patient", async () => {
    render(<CaseWorkspacePage />);
    await waitFor(() => screen.getByTestId("history-list"));

    expect(getHistory).toHaveBeenCalledWith({
      patient_id: 3,
      scope: "consultations",
      counterparty_id: 7,
      counterparty_type: "doctor",
    });
    expect(
      within(screen.getByTestId("case-history")).getByText("Prescription"),
    ).toBeTruthy();
  });

  it("shows a denial-safe empty state when consent yields no history", async () => {
    getHistory.mockResolvedValue({
      record_id: 1,
      patient_id: 3,
      created_at: "2026-01-01T00:00:00Z",
      entries: [],
    });
    render(<CaseWorkspacePage />);
    await waitFor(() => screen.getByText(t.historyEmpty));

    expect(screen.queryByTestId("history-list")).not.toBeInTheDocument();
  });
});

describe("CaseWorkspacePage inner tabs, transcript and audio (US-14, #484)", () => {
  it("renders the three workspace tabs with the pre-summary panel active", async () => {
    render(<CaseWorkspacePage />);
    await waitFor(() => screen.getByTestId("case-content"));

    expect(screen.getByRole("tab", { name: t.tabPreSummary })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("tab", { name: t.tabHistory })).toHaveAttribute(
      "aria-selected",
      "false",
    );
    expect(
      screen.getByRole("tab", { name: t.tabPrescription }),
    ).toHaveAttribute("aria-selected", "false");
    expect(screen.getByTestId("tab-panel-pre-summary")).not.toHaveAttribute(
      "hidden",
    );
    expect(screen.getByTestId("tab-panel-history")).toHaveAttribute("hidden");
    expect(screen.getByTestId("tab-panel-prescription")).toHaveAttribute(
      "hidden",
    );
  });

  it("switches tabs on click and via arrow-key rotation", async () => {
    render(<CaseWorkspacePage />);
    await waitFor(() => screen.getByTestId("case-content"));

    fireEvent.click(screen.getByRole("tab", { name: t.tabHistory }));
    expect(screen.getByTestId("tab-panel-history")).not.toHaveAttribute(
      "hidden",
    );
    expect(screen.getByTestId("tab-panel-pre-summary")).toHaveAttribute(
      "hidden",
    );

    fireEvent.keyDown(screen.getByRole("tab", { name: t.tabHistory }), {
      key: "ArrowRight",
    });
    expect(
      screen.getByRole("tab", { name: t.tabPrescription }),
    ).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("tab-panel-prescription")).not.toHaveAttribute(
      "hidden",
    );

    fireEvent.keyDown(screen.getByRole("tab", { name: t.tabPrescription }), {
      key: "ArrowLeft",
    });
    expect(screen.getByRole("tab", { name: t.tabHistory })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("shows the original transcript and the finalized summary on the pre-summary tab", async () => {
    render(<CaseWorkspacePage />);
    await waitFor(() => screen.getByTestId("transcript-text"));

    expect(getIntakeDetail).toHaveBeenCalledWith(7);
    expect(getPreSummary).toHaveBeenCalledWith(5);
    expect(screen.getByTestId("transcript-text")).toHaveTextContent(
      "मुझे लगातार सिरदर्द रहता है।",
    );
    expect(screen.getByTestId("case-pre-summary")).toHaveTextContent(
      t.summaryHeading,
    );
    expect(screen.getByTestId("case-pre-summary-confidence")).toHaveTextContent(
      "44%",
    );
    expect(
      screen.getByTestId("case-pre-summary-review-state"),
    ).toHaveTextContent(t.reviewStateFinal);
  });

  it("shows the transcript empty state when the intake has no transcript", async () => {
    getIntakeDetail.mockResolvedValue(
      intakeDetail({ transcript: null, text: null }),
    );
    render(<CaseWorkspacePage />);
    await waitFor(() => screen.getByTestId("transcript-empty"));

    expect(screen.getByTestId("transcript-empty")).toHaveTextContent(
      t.transcriptEmpty,
    );
    expect(screen.queryByTestId("transcript-text")).not.toBeInTheDocument();
  });

  it("surfaces an intake-detail load failure distinctly from an empty transcript", async () => {
    getIntakeDetail.mockRejectedValue(
      new ApiError({
        code: "INTAKE_NOT_FOUND",
        message: "boom",
        trace_id: "t",
        details: {},
      }),
    );
    render(<CaseWorkspacePage />);
    await waitFor(() => screen.getByTestId("transcript-load-error"));

    expect(screen.getByTestId("transcript-load-error")).toHaveTextContent(
      t.transcriptLoadFail,
    );
    expect(screen.queryByTestId("transcript-empty")).not.toBeInTheDocument();
    expect(screen.queryByTestId("case-content")).toBeInTheDocument();
  });

  it("plays the latest recording attempt through an object URL", async () => {
    const originalCreate = URL.createObjectURL;
    const originalRevoke = URL.revokeObjectURL;
    const createSpy = vi.fn(() => "blob:mock-audio");
    const revokeSpy = vi.fn();
    URL.createObjectURL = createSpy as typeof URL.createObjectURL;
    URL.revokeObjectURL = revokeSpy as typeof URL.revokeObjectURL;
    getIntakeDetail.mockResolvedValue(
      intakeDetail({
        media_refs: [
          mediaRef({ record_attempt: 1, audio_duration_ms: 10000 }),
          mediaRef({ record_attempt: 2, audio_duration_ms: 17090 }),
        ],
      }),
    );
    getMediaBlob.mockResolvedValue(new Blob(["audio"], { type: "audio/mpeg" }));
    try {
      render(<CaseWorkspacePage />);

      await waitFor(() => screen.getByTestId("audio-element"));

      expect(getMediaBlob).toHaveBeenCalledWith(5, 302);
      expect(createSpy).toHaveBeenCalledWith(expect.any(Blob));
      expect(screen.getByTestId("audio-playback")).toHaveTextContent(
        t.audioPlayLabel,
      );
      expect(screen.getByTestId("audio-playback")).toHaveTextContent("0:17");
    } finally {
      URL.createObjectURL = originalCreate;
      URL.revokeObjectURL = originalRevoke;
    }
  });

  it("surfaces a recording load failure without failing the workspace", async () => {
    getIntakeDetail.mockResolvedValue(
      intakeDetail({ media_refs: [mediaRef()] }),
    );
    getMediaBlob.mockRejectedValue(
      new ApiError({
        code: "MEDIA_TRANSFER_ERROR",
        message: "boom",
        trace_id: "t",
        details: {},
      }),
    );
    render(<CaseWorkspacePage />);

    await waitFor(() => screen.getByTestId("audio-load-error"));
    expect(screen.getByTestId("audio-load-error")).toHaveTextContent(
      t.audioLoadFail,
    );
    expect(screen.queryByTestId("audio-element")).not.toBeInTheDocument();
  });

  it("locks the prescription tab on a pre-summary case and jumps to the handshake", async () => {
    render(<CaseWorkspacePage />);
    await waitFor(() => screen.getByTestId("prescription-lock"));

    expect(screen.getByTestId("rx-lock-done")).toHaveTextContent(t.rxLockDone);
    expect(screen.getByTestId("rx-lock-pending")).toHaveTextContent(
      t.rxLockPending,
    );

    fireEvent.click(screen.getByRole("tab", { name: t.tabPrescription }));
    expect(screen.getByTestId("tab-panel-prescription")).not.toHaveAttribute(
      "hidden",
    );

    fireEvent.click(screen.getByTestId("rx-lock-action"));
    expect(screen.getByTestId("tab-panel-pre-summary")).not.toHaveAttribute(
      "hidden",
    );
    expect(screen.getByTestId("tab-panel-prescription")).toHaveAttribute(
      "hidden",
    );
    expect(screen.getByTestId("handshake-action")).toBeTruthy();
  });

  it("does not lock the prescription tab once the consult is complete", async () => {
    getCase.mockResolvedValue(caseItem(11, { stage: "prescription_pending" }));
    render(<CaseWorkspacePage />);
    await waitFor(() => screen.getByTestId("case-prescription"));

    expect(screen.queryByTestId("prescription-lock")).not.toBeInTheDocument();
  });
});

describe("CaseWorkspacePage handshake (US-24)", () => {
  it("completes the consultation and moves the case to prescription pending", async () => {
    doHandshake.mockResolvedValue(
      caseItem(11, { stage: "prescription_pending" }),
    );
    render(<CaseWorkspacePage />);
    await waitFor(() => screen.getByTestId("handshake-action"));

    fireEvent.click(screen.getByTestId("handshake-action"));

    await waitFor(() =>
      expect(screen.getByTestId("handshake-success")).toBeTruthy(),
    );
    expect(doHandshake).toHaveBeenCalledWith(11);
    expect(screen.getByTestId("stage-chip")).toHaveTextContent(
      consoleT.stagePrescriptionPending,
    );
    await waitFor(() => screen.getByTestId("prescription-editor"));
    expect(screen.getByTestId("rx-item-name-0")).toHaveValue("Paracetamol");
  });

  it("does not offer the handshake on a prescription-pending case", async () => {
    getCase.mockResolvedValue(caseItem(11, { stage: "prescription_pending" }));
    render(<CaseWorkspacePage />);
    await waitFor(() => screen.getByTestId("case-content"));

    expect(screen.queryByTestId("handshake-action")).not.toBeInTheDocument();
    expect(screen.getByTestId("handshake-success")).toBeTruthy();
  });

  it("shows the closed terminal state without actions", async () => {
    getCase.mockResolvedValue(caseItem(11, { stage: "closed" }));
    render(<CaseWorkspacePage />);
    await waitFor(() => screen.getByTestId("closed-state"));

    expect(screen.getByTestId("closed-state")).toHaveTextContent(
      consoleT.stageClosed,
    );
    expect(screen.queryByTestId("handshake-action")).not.toBeInTheDocument();
  });

  it("surfaces a failure message when the handshake errors", async () => {
    doHandshake.mockRejectedValue(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "t",
        details: {},
      }),
    );
    render(<CaseWorkspacePage />);
    await waitFor(() => screen.getByTestId("handshake-action"));

    fireEvent.click(screen.getByTestId("handshake-action"));
    await waitFor(() => expect(screen.getByText(t.handshakeFail)).toBeTruthy());
  });
});

describe("CaseWorkspacePage prescription drafting (US-18/#452)", () => {
  it("reloads the in-progress revision into the editor on a pending case", async () => {
    getCase.mockResolvedValue(caseItem(11, { stage: "prescription_pending" }));
    getWorkingRx.mockResolvedValue(prescription());
    render(<CaseWorkspacePage />);

    await waitFor(() => screen.getByTestId("prescription-editor"));

    expect(getWorkingRx).toHaveBeenCalledWith(11);
    expect(screen.getByTestId("rx-source")).toHaveTextContent(t.sourceAiDraft);
    expect(screen.getByTestId("rx-item-name-0")).toHaveValue("Paracetamol");
    expect(screen.getByTestId("rx-item-dose-0")).toHaveValue("500mg");
    expect(screen.getByTestId("rx-item-duration-0")).toHaveValue("3 days");
    expect(screen.getByTestId("rx-item-frequency-0")).toHaveValue(
      "3 times daily",
    );
  });

  it("offers the doctor-input capture and gates the AI-draft path", async () => {
    getCase.mockResolvedValue(caseItem(11, { stage: "prescription_pending" }));
    getWorkingRx.mockRejectedValue(noDraftError());
    render(<CaseWorkspacePage />);

    await waitFor(() => screen.getByTestId("prescription-empty"));

    expect(screen.getByText(t.noDraftYet)).toBeTruthy();
    // PHASE-8.1 T6 (#490): voice/photo/addendum capture is always available.
    expect(screen.getByTestId("rx-input-capture")).toBeInTheDocument();
    expect(screen.getByTestId("rx-input-voice")).toBeInTheDocument();
    expect(screen.getByTestId("rx-input-photo")).toBeInTheDocument();
    expect(screen.getByTestId("rx-input-addendum")).toBeInTheDocument();
    expect(screen.queryByTestId("rx-input-received")).not.toBeInTheDocument();
    // The AI draft stays locked until a doctor input has been attached.
    expect(screen.getByTestId("request-draft-action")).toBeDisabled();
    expect(screen.getByTestId("request-draft-blocked-help")).toHaveTextContent(
      t.requestDraftBlocked,
    );
    expect(screen.getByTestId("manual-authoring-action")).toHaveTextContent(
      t.manualAuthoringAction,
    );
    expect(screen.queryByTestId("prescription-editor")).not.toBeInTheDocument();
  });

  it("attaches a voice note via the doctor media route and unlocks the AI draft", async () => {
    getCase.mockResolvedValue(caseItem(11, { stage: "prescription_pending" }));
    getWorkingRx.mockRejectedValue(noDraftError());
    doDraft.mockResolvedValue(prescription());
    render(<CaseWorkspacePage />);

    await waitFor(() => screen.getByTestId("rx-input-voice"));
    attachFileToTestId("rx-input-voice", "note.webm", "audio/webm");

    await waitFor(() =>
      expect(screen.getByTestId("rx-input-received")).toBeTruthy(),
    );
    expect(screen.getByText(t.doctorInputReceived)).toBeTruthy();
    expect(doUploadDoctorMedia).toHaveBeenCalledWith(
      expect.any(File),
      expect.objectContaining({ filename: "note.webm" }),
    );
    expect(doSubmitDoctorInput).toHaveBeenCalledWith(11, {
      input_type: "voice",
      media_ref: "rx_input/7/opaque.enc",
    });
    expect(screen.getByTestId("request-draft-action")).toBeEnabled();
    expect(
      screen.queryByTestId("request-draft-blocked-help"),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("request-draft-action"));
    await waitFor(() => screen.getByTestId("prescription-editor"));
    expect(doDraft).toHaveBeenCalledWith(11, { source: "ai_draft" });
    expect(screen.getByTestId("rx-item-name-0")).toHaveValue("Paracetamol");
  });

  it("attaches a photo and posts its media ticket to doctor-input", async () => {
    getCase.mockResolvedValue(caseItem(11, { stage: "prescription_pending" }));
    getWorkingRx.mockRejectedValue(noDraftError());
    render(<CaseWorkspacePage />);

    await waitFor(() => screen.getByTestId("rx-input-photo"));
    attachFileToTestId("rx-input-photo", "scan.jpg", "image/jpeg");

    await waitFor(() =>
      expect(screen.getByTestId("rx-input-received")).toBeTruthy(),
    );
    expect(doUploadDoctorMedia).toHaveBeenCalledWith(
      expect.any(File),
      expect.objectContaining({
        filename: "scan.jpg",
        fileSizeBytes: expect.any(Number),
      }),
    );
    expect(doSubmitDoctorInput).toHaveBeenCalledWith(11, {
      input_type: "photo",
      media_ref: "rx_input/7/opaque.enc",
    });
  });

  it("persists a typed addendum and posts the media ticket as voice input", async () => {
    getCase.mockResolvedValue(caseItem(11, { stage: "prescription_pending" }));
    getWorkingRx.mockRejectedValue(noDraftError());
    render(<CaseWorkspacePage />);

    await waitFor(() => screen.getByTestId("rx-input-addendum"));
    fireEvent.change(screen.getByTestId("rx-input-addendum"), {
      target: { value: "Amoxicillin 500 mg thrice daily" },
    });
    fireEvent.click(screen.getByTestId("rx-input-addendum-submit"));

    await waitFor(() =>
      expect(screen.getByTestId("rx-input-received")).toBeTruthy(),
    );
    expect(doUploadDoctorMedia).toHaveBeenCalledWith(
      expect.any(Blob),
      expect.objectContaining({ filename: "addendum.txt" }),
    );
    expect(doSubmitDoctorInput).toHaveBeenCalledWith(11, {
      input_type: "voice",
      media_ref: "rx_input/7/opaque.enc",
    });
  });

  it("keeps the AI draft locked and surfaces an error when an attach fails", async () => {
    getCase.mockResolvedValue(caseItem(11, { stage: "prescription_pending" }));
    getWorkingRx.mockRejectedValue(noDraftError());
    doUploadDoctorMedia.mockRejectedValue(
      new ApiError({
        code: "NETWORK_ERROR",
        message: "offline",
        trace_id: "t",
        details: {},
      }),
    );
    render(<CaseWorkspacePage />);

    await waitFor(() => screen.getByTestId("rx-input-voice"));
    attachFileToTestId("rx-input-voice", "note.webm", "audio/webm");

    await waitFor(() =>
      expect(screen.getByTestId("rx-input-error")).toBeTruthy(),
    );
    expect(screen.getByText(t.doctorInputFail)).toBeTruthy();
    expect(doSubmitDoctorInput).not.toHaveBeenCalled();
    expect(screen.getByTestId("request-draft-action")).toBeDisabled();
  });

  it("keeps the submit button disabled until the addendum has text", async () => {
    getCase.mockResolvedValue(caseItem(11, { stage: "prescription_pending" }));
    getWorkingRx.mockRejectedValue(noDraftError());
    render(<CaseWorkspacePage />);

    await waitFor(() => screen.getByTestId("rx-input-addendum-submit"));
    expect(screen.getByTestId("rx-input-addendum-submit")).toBeDisabled();
    fireEvent.change(screen.getByTestId("rx-input-addendum"), {
      target: { value: "   " },
    });
    expect(screen.getByTestId("rx-input-addendum-submit")).toBeDisabled();
    fireEvent.change(screen.getByTestId("rx-input-addendum"), {
      target: { value: "ORS sachet" },
    });
    expect(screen.getByTestId("rx-input-addendum-submit")).toBeEnabled();
  });

  it("opens the manual editor with a fresh empty row and saves a manual draft", async () => {
    getCase.mockResolvedValue(caseItem(11, { stage: "prescription_pending" }));
    getWorkingRx.mockRejectedValue(noDraftError());
    doDraft.mockResolvedValue(prescription({ source: "manual" }));
    render(<CaseWorkspacePage />);

    await waitFor(() => screen.getByTestId("prescription-empty"));
    fireEvent.click(screen.getByTestId("manual-authoring-action"));

    // The editor renders without any working revision or doctor input.
    await waitFor(() => screen.getByTestId("prescription-editor"));
    expect(screen.getByTestId("rx-item-name-0")).toHaveValue("");
    expect(doSubmitDoctorInput).not.toHaveBeenCalled();

    fireEvent.change(screen.getByTestId("rx-item-name-0"), {
      target: { value: "Amoxicillin" },
    });
    fireEvent.click(screen.getByTestId("save-revision-action"));

    await waitFor(() =>
      expect(screen.getByTestId("revision-saved")).toBeTruthy(),
    );
    expect(doDraft).toHaveBeenCalledWith(11, {
      source: "manual",
      items: [
        {
          name: "Amoxicillin",
          dose: null,
          duration: null,
          frequency: null,
        },
      ],
    });
    expect(screen.getByTestId("rx-source")).toHaveTextContent(t.sourceManual);
  });

  it("persists edited and added items when the revision is saved", async () => {
    getCase.mockResolvedValue(caseItem(11, { stage: "prescription_pending" }));
    getWorkingRx.mockResolvedValue(prescription());
    doSaveRevision.mockResolvedValue(prescription());
    render(<CaseWorkspacePage />);

    await waitFor(() => screen.getByTestId("prescription-editor"));
    fireEvent.change(screen.getByTestId("rx-item-dose-0"), {
      target: { value: "650mg" },
    });
    fireEvent.click(screen.getByTestId("add-rx-item"));
    fireEvent.change(screen.getByTestId("rx-item-name-1"), {
      target: { value: "ORS" },
    });
    fireEvent.click(screen.getByTestId("save-revision-action"));

    await waitFor(() =>
      expect(screen.getByTestId("revision-saved")).toBeTruthy(),
    );
    expect(doSaveRevision).toHaveBeenCalledWith(11, 21, {
      rx_items: [
        {
          name: "Paracetamol",
          dose: "650mg",
          duration: "3 days",
          frequency: "3 times daily",
        },
        { name: "ORS", dose: null, duration: null, frequency: null },
      ],
    });
    expect(screen.getByText(t.revisionSaved)).toBeTruthy();
  });

  it("removes a row from the draft before saving", async () => {
    getCase.mockResolvedValue(caseItem(11, { stage: "prescription_pending" }));
    getWorkingRx.mockResolvedValue(
      prescription({
        items: [
          {
            rx_item_id: 31,
            prescription_id: 21,
            sequence: 1,
            name: "Paracetamol",
            dose: "500mg",
            duration: "3 days",
            frequency: null,
          },
          {
            rx_item_id: 32,
            prescription_id: 21,
            sequence: 2,
            name: "ORS",
            dose: null,
            duration: null,
            frequency: null,
          },
        ],
      }),
    );
    doSaveRevision.mockResolvedValue(prescription());
    render(<CaseWorkspacePage />);

    await waitFor(() => screen.getByTestId("prescription-editor"));
    fireEvent.click(screen.getByTestId("rx-item-remove-1"));

    fireEvent.click(screen.getByTestId("save-revision-action"));
    await waitFor(() =>
      expect(screen.getByTestId("revision-saved")).toBeTruthy(),
    );
    expect(doSaveRevision).toHaveBeenCalledWith(11, 21, {
      rx_items: [
        {
          name: "Paracetamol",
          dose: "500mg",
          duration: "3 days",
          frequency: null,
        },
      ],
    });
  });

  it("persists an edited frequency when the revision is saved", async () => {
    getCase.mockResolvedValue(caseItem(11, { stage: "prescription_pending" }));
    getWorkingRx.mockResolvedValue(prescription());
    doSaveRevision.mockResolvedValue(prescription());
    render(<CaseWorkspacePage />);

    await waitFor(() => screen.getByTestId("prescription-editor"));
    fireEvent.change(screen.getByTestId("rx-item-frequency-0"), {
      target: { value: "4 times daily" },
    });
    fireEvent.click(screen.getByTestId("save-revision-action"));

    await waitFor(() =>
      expect(screen.getByTestId("revision-saved")).toBeTruthy(),
    );
    expect(doSaveRevision).toHaveBeenCalledWith(11, 21, {
      rx_items: [
        {
          name: "Paracetamol",
          dose: "500mg",
          duration: "3 days",
          frequency: "4 times daily",
        },
      ],
    });
  });

  it("surfaces the drafting-cap message when the backend refuses a new draft", async () => {
    getCase.mockResolvedValue(caseItem(11, { stage: "prescription_pending" }));
    getWorkingRx.mockRejectedValue(noDraftError());
    doDraft.mockRejectedValue(
      new ApiError({
        code: "ILLEGAL_PRESCRIPTION_TRANSITION",
        message: "cap reached",
        trace_id: "t",
        details: {},
      }),
    );
    render(<CaseWorkspacePage />);

    await waitFor(() => screen.getByTestId("rx-input-voice"));
    attachFileToTestId("rx-input-voice", "note.webm", "audio/webm");
    await waitFor(() =>
      expect(screen.getByTestId("rx-input-received")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("request-draft-action"));

    await waitFor(() => expect(screen.getByTestId("draft-error")).toBeTruthy());
    expect(screen.getByText(t.draftCapReached)).toBeTruthy();
  });

  it("surfaces a generic error when the draft request fails", async () => {
    getCase.mockResolvedValue(caseItem(11, { stage: "prescription_pending" }));
    getWorkingRx.mockRejectedValue(noDraftError());
    doDraft.mockRejectedValue(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "t",
        details: {},
      }),
    );
    render(<CaseWorkspacePage />);

    await waitFor(() => screen.getByTestId("rx-input-voice"));
    attachFileToTestId("rx-input-voice", "note.webm", "audio/webm");
    await waitFor(() =>
      expect(screen.getByTestId("rx-input-received")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("request-draft-action"));

    await waitFor(() =>
      expect(screen.getByText(t.requestDraftFail)).toBeTruthy(),
    );
  });

  describe.each([
    ["CARE_RX_CONSENT_DENIED", "draftConsentDenied"],
    ["CARE_RX_NO_DOCTOR_INPUT", "draftNoDoctorInput"],
    ["CARE_RX_DRAFT_CAP_REACHED", "draftCapReached"],
    ["CARE_CASE_CLOSED", "draftCaseClosed"],
    ["CARE_NOT_FOUND", "draftCaseNotFound"],
  ] as const)(
    "draft refusal code %s maps to an in-language message (#490)",
    (code, key) => {
      it(`surfaces the ${key} message`, async () => {
        getCase.mockResolvedValue(
          caseItem(11, { stage: "prescription_pending" }),
        );
        getWorkingRx.mockRejectedValue(noDraftError());
        doDraft.mockRejectedValue(
          new ApiError({
            code,
            message: "refused",
            trace_id: "t",
            details: {},
          }),
        );
        render(<CaseWorkspacePage />);

        await waitFor(() => screen.getByTestId("rx-input-voice"));
        attachFileToTestId("rx-input-voice", "note.webm", "audio/webm");
        await waitFor(() =>
          expect(screen.getByTestId("rx-input-received")).toBeTruthy(),
        );
        fireEvent.click(screen.getByTestId("request-draft-action"));

        await waitFor(() =>
          expect(screen.getByTestId("draft-error")).toBeTruthy(),
        );
        expect(screen.getByTestId("draft-error")).toHaveTextContent(t[key]);
      });
    },
  );

  it("surfaces a save failure without clearing the draft", async () => {
    getCase.mockResolvedValue(caseItem(11, { stage: "prescription_pending" }));
    getWorkingRx.mockResolvedValue(prescription());
    doSaveRevision.mockRejectedValue(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "t",
        details: {},
      }),
    );
    render(<CaseWorkspacePage />);

    await waitFor(() => screen.getByTestId("prescription-editor"));
    fireEvent.click(screen.getByTestId("save-revision-action"));

    await waitFor(() =>
      expect(screen.getByTestId("revision-save-error")).toBeTruthy(),
    );
    expect(screen.getByText(t.saveRevisionFail)).toBeTruthy();
    expect(screen.getByTestId("rx-item-name-0")).toHaveValue("Paracetamol");
  });

  it("shows a retryable error when the working-rx load fails", async () => {
    getCase.mockResolvedValue(caseItem(11, { stage: "prescription_pending" }));
    getWorkingRx.mockRejectedValueOnce(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "t",
        details: {},
      }),
    );
    render(<CaseWorkspacePage />);

    await waitFor(() => screen.getByTestId("prescription-load-error"));
    expect(screen.getByText(t.workingRxLoadFail)).toBeTruthy();

    fireEvent.click(screen.getByTestId("prescription-load-retry"));
    await waitFor(() => screen.getByTestId("prescription-editor"));
    expect(getWorkingRx).toHaveBeenCalledTimes(2);
  });
});

describe("CaseWorkspacePage approval, rejection, close (#453, US-19..22)", () => {
  it("blocks approval until the verification declaration is ticked", async () => {
    getCase.mockResolvedValue(caseItem(11, { stage: "prescription_pending" }));
    getWorkingRx.mockResolvedValue(prescription());
    render(<CaseWorkspacePage />);

    await waitFor(() => screen.getByTestId("approve-issue-action"));
    const approve = screen.getByTestId("approve-issue-action");
    expect(approve).toBeDisabled();
    expect(screen.getByText(t.approveBlockedHelp)).toBeTruthy();

    fireEvent.click(approve);
    expect(doApprove).not.toHaveBeenCalled();
  });

  it("approves only once declared and renders the issued prescription", async () => {
    getCase.mockResolvedValue(caseItem(11, { stage: "prescription_pending" }));
    getWorkingRx.mockResolvedValue(prescription());
    doApprove.mockResolvedValue({
      ...prescription(),
      status: "issued",
      issued_at: "2026-09-14T09:30:00Z",
    });
    render(<CaseWorkspacePage />);

    await waitFor(() => screen.getByTestId("approve-issue-action"));
    fireEvent.click(screen.getByTestId("verification-declaration"));
    fireEvent.click(screen.getByTestId("approve-issue-action"));

    await waitFor(() => expect(doApprove).toHaveBeenCalledWith(11, 21));
    await waitFor(() => screen.getByTestId("issued-rx"));
    expect(screen.getByTestId("rx-status")).toHaveTextContent(t.rxStatusIssued);
    expect(screen.getByTestId("issued-rx-item")).toHaveTextContent(
      "Paracetamol",
    );
    expect(screen.getByTestId("issued-rx-item")).toHaveTextContent(
      "3 times daily",
    );
    expect(screen.getByText(t.issuedHeading)).toBeTruthy();
    expect(screen.getByTestId("issued-attribution")).toHaveTextContent(
      t.issuedAttributedTo,
    );
    expect(screen.getByTestId("issued-at")).toBeTruthy();
  });

  it("renders the issuing doctor's name in place of the attribution copy", async () => {
    getCase.mockResolvedValue(caseItem(11, { stage: "prescription_pending" }));
    getWorkingRx.mockResolvedValue(prescription());
    doApprove.mockResolvedValue({
      ...prescription(),
      status: "issued",
      issued_at: "2026-09-14T09:30:00Z",
      attributed_doctor_name: "Dr. Priya Verma",
    });
    render(<CaseWorkspacePage />);

    await waitFor(() => screen.getByTestId("approve-issue-action"));
    fireEvent.click(screen.getByTestId("verification-declaration"));
    fireEvent.click(screen.getByTestId("approve-issue-action"));

    await waitFor(() => screen.getByTestId("issued-rx"));
    const attribution = screen.getByTestId("issued-attribution");
    expect(attribution).toHaveTextContent("Dr. Priya Verma");
    expect(attribution).not.toHaveTextContent(t.issuedAttributedTo);
  });

  it("surfaces an approval failure without issuing", async () => {
    getCase.mockResolvedValue(caseItem(11, { stage: "prescription_pending" }));
    getWorkingRx.mockResolvedValue(prescription());
    doApprove.mockRejectedValue(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "t",
        details: {},
      }),
    );
    render(<CaseWorkspacePage />);

    await waitFor(() => screen.getByTestId("approve-issue-action"));
    fireEvent.click(screen.getByTestId("verification-declaration"));
    fireEvent.click(screen.getByTestId("approve-issue-action"));

    await waitFor(() =>
      expect(screen.getByTestId("approve-error")).toBeTruthy(),
    );
    expect(screen.getByText(t.approveFail)).toBeTruthy();
    expect(screen.queryByTestId("issued-rx")).not.toBeInTheDocument();
  });

  it("rejects a draft with a reason the patient can understand", async () => {
    getCase.mockResolvedValue(caseItem(11, { stage: "prescription_pending" }));
    getWorkingRx.mockResolvedValue(prescription());
    doReject.mockResolvedValue({ ...prescription(), status: "rejected" });
    render(<CaseWorkspacePage />);

    await waitFor(() => screen.getByTestId("reject-reason"));
    fireEvent.change(screen.getByTestId("reject-reason"), {
      target: { value: "needs a consultation first" },
    });
    fireEvent.click(screen.getByTestId("reject-action"));

    await waitFor(() =>
      expect(doReject).toHaveBeenCalledWith(11, 21, {
        reason: "needs a consultation first",
      }),
    );
    await waitFor(() => screen.getByTestId("rx-rejected"));
    expect(screen.getByText(t.rejectedHeading)).toBeTruthy();
    expect(screen.getByTestId("recorded-reason")).toHaveTextContent(
      "needs a consultation first",
    );
    expect(screen.queryByTestId("prescription-editor")).not.toBeInTheDocument();
    // A rejected draft never auto-closes: the re-draft path stays available.
    expect(screen.getByTestId("reject-redraft-action")).toBeTruthy();
  });

  it("keeps the reject disabled until a reason is typed", async () => {
    getCase.mockResolvedValue(caseItem(11, { stage: "prescription_pending" }));
    getWorkingRx.mockResolvedValue(prescription());
    render(<CaseWorkspacePage />);

    await waitFor(() => screen.getByTestId("reject-action"));
    expect(screen.getByTestId("reject-action")).toBeDisabled();

    fireEvent.change(screen.getByTestId("reject-reason"), {
      target: { value: "another consultation is scheduled" },
    });
    await waitFor(() =>
      expect(screen.getByTestId("reject-action")).not.toBeDisabled(),
    );
    expect(doReject).not.toHaveBeenCalled();
  });

  it("surfaces a rejection failure without losing the reviewable draft", async () => {
    getCase.mockResolvedValue(caseItem(11, { stage: "prescription_pending" }));
    getWorkingRx.mockResolvedValue(prescription());
    doReject.mockRejectedValue(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "t",
        details: {},
      }),
    );
    render(<CaseWorkspacePage />);

    await waitFor(() => screen.getByTestId("reject-reason"));
    fireEvent.change(screen.getByTestId("reject-reason"), {
      target: { value: "needs a consultation first" },
    });
    fireEvent.click(screen.getByTestId("reject-action"));

    await waitFor(() =>
      expect(screen.getByTestId("reject-error")).toBeTruthy(),
    );
    expect(screen.getByText(t.rejectFail)).toBeTruthy();
    // The drafted review remains editable and approvable.
    expect(screen.getByTestId("prescription-editor")).toBeTruthy();
    expect(screen.getByTestId("approve-issue-action")).toBeTruthy();
  });

  it("close-without-prescription moves the case to Closed and off pending", async () => {
    getCase.mockResolvedValue(caseItem(11, { stage: "prescription_pending" }));
    getWorkingRx.mockResolvedValue(prescription());
    doCloseCase.mockResolvedValue(
      caseItem(11, { stage: "closed", close_reason: "no_show" }),
    );
    render(<CaseWorkspacePage />);

    await waitFor(() => screen.getByTestId("close-reason-input"));
    fireEvent.change(screen.getByTestId("close-reason-input"), {
      target: { value: "no_show" },
    });
    fireEvent.click(screen.getByTestId("close-case-action"));

    await waitFor(() =>
      expect(doCloseCase).toHaveBeenCalledWith(11, {
        close_reason: "no_show",
      }),
    );
    await waitFor(() => screen.getByTestId("closed-state"));
    expect(screen.getByTestId("stage-chip")).toHaveTextContent(
      consoleT.stageClosed,
    );
    expect(screen.queryByTestId("case-prescription")).not.toBeInTheDocument();
    expect(screen.queryByTestId("case-close")).not.toBeInTheDocument();
  });

  it("surfaces a close failure without leaving the pending state", async () => {
    getCase.mockResolvedValue(caseItem(11, { stage: "prescription_pending" }));
    getWorkingRx.mockResolvedValue(prescription());
    doCloseCase.mockRejectedValue(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "t",
        details: {},
      }),
    );
    render(<CaseWorkspacePage />);

    await waitFor(() => screen.getByTestId("close-reason-input"));
    fireEvent.change(screen.getByTestId("close-reason-input"), {
      target: { value: "patient_withdrawn" },
    });
    fireEvent.click(screen.getByTestId("close-case-action"));

    await waitFor(() => expect(screen.getByTestId("close-error")).toBeTruthy());
    expect(screen.getByText(t.closeFail)).toBeTruthy();
    expect(screen.getByTestId("stage-chip")).toHaveTextContent(
      consoleT.stagePrescriptionPending,
    );
    expect(screen.getByTestId("case-close")).toBeTruthy();
  });
});

describe("CaseWorkspacePage edited-items tracker (#494)", () => {
  it("counts items whose name/dose/duration/frequency differ from the snapshot", async () => {
    getCase.mockResolvedValue(caseItem(11, { stage: "prescription_pending" }));
    getWorkingRx.mockResolvedValue(
      prescription({
        items: [
          rxItem(31, {
            name: "Paracetamol",
            dose: "650mg",
            duration: "3 days",
            frequency: "3 times daily",
          }),
          rxItem(32, {
            sequence: 2,
            name: "Azithromycin",
            dose: "500mg",
            duration: "5 days",
            frequency: "1 time daily",
          }),
        ],
        draft_snapshot: {
          rx_items: [
            {
              name: "Paracetamol",
              dose: "500mg",
              duration: "3 days",
              frequency: "3 times daily",
            },
            {
              name: "Azithromycin",
              dose: "500mg",
              duration: "5 days",
              frequency: "1 time daily",
            },
          ],
        },
      }),
    );
    render(<CaseWorkspacePage />);

    await waitFor(() => screen.getByTestId("edited-tracker"));
    expect(screen.getByTestId("edited-tracker")).toHaveTextContent(
      t.editedTracker(1),
    );
  });

  it("reads an unedited AI draft as 0 items edited", async () => {
    getCase.mockResolvedValue(caseItem(11, { stage: "prescription_pending" }));
    getWorkingRx.mockResolvedValue(
      prescription({
        items: [
          rxItem(31, {
            name: "Paracetamol",
            dose: "500mg",
            duration: "3 days",
            frequency: "3 times daily",
          }),
          rxItem(32, {
            sequence: 2,
            name: "Azithromycin",
            dose: "500mg",
            duration: "5 days",
            frequency: "1 time daily",
          }),
        ],
        draft_snapshot: {
          rx_items: [
            {
              name: "Paracetamol",
              dose: "500mg",
              duration: "3 days",
              frequency: "3 times daily",
            },
            {
              name: "Azithromycin",
              dose: "500mg",
              duration: "5 days",
              frequency: "1 time daily",
            },
          ],
        },
      }),
    );
    render(<CaseWorkspacePage />);

    await waitFor(() => screen.getByTestId("edited-tracker"));
    expect(screen.getByTestId("edited-tracker")).toHaveTextContent(
      t.editedTracker(0),
    );
  });

  it("counts a frequency-only edit as edited", async () => {
    getCase.mockResolvedValue(caseItem(11, { stage: "prescription_pending" }));
    getWorkingRx.mockResolvedValue(
      prescription({
        items: [
          rxItem(31, {
            name: "Paracetamol",
            dose: "500mg",
            duration: "3 days",
            frequency: "2 times daily",
          }),
        ],
        draft_snapshot: {
          rx_items: [
            {
              name: "Paracetamol",
              dose: "500mg",
              duration: "3 days",
              frequency: "3 times daily",
            },
          ],
        },
      }),
    );
    render(<CaseWorkspacePage />);

    await waitFor(() => screen.getByTestId("edited-tracker"));
    expect(screen.getByTestId("edited-tracker")).toHaveTextContent(
      t.editedTracker(1),
    );
  });

  it("counts a snapshot item the doctor deleted as edited", async () => {
    getCase.mockResolvedValue(caseItem(11, { stage: "prescription_pending" }));
    getWorkingRx.mockResolvedValue(
      prescription({
        items: [
          rxItem(31, {
            name: "Paracetamol",
            dose: "500mg",
            duration: "3 days",
            frequency: "3 times daily",
          }),
        ],
        draft_snapshot: {
          rx_items: [
            {
              name: "Paracetamol",
              dose: "500mg",
              duration: "3 days",
              frequency: "3 times daily",
            },
            {
              name: "Azithromycin",
              dose: "500mg",
              duration: "5 days",
              frequency: "1 time daily",
            },
          ],
        },
      }),
    );
    render(<CaseWorkspacePage />);

    await waitFor(() => screen.getByTestId("edited-tracker"));
    expect(screen.getByTestId("edited-tracker")).toHaveTextContent(
      t.editedTracker(1),
    );
  });

  it("reads a manual prescription (empty snapshot) as all items edited", async () => {
    getCase.mockResolvedValue(caseItem(11, { stage: "prescription_pending" }));
    getWorkingRx.mockResolvedValue(
      prescription({
        draft_snapshot: { rx_items: [] },
        items: [
          rxItem(31, {
            name: "Paracetamol",
            dose: "500mg",
            duration: "3 days",
            frequency: "3 times daily",
          }),
          rxItem(32, {
            sequence: 2,
            name: "Azithromycin",
            dose: "500mg",
            duration: "5 days",
            frequency: "1 time daily",
          }),
          rxItem(33, {
            sequence: 3,
            name: "ORS sachet",
            dose: null,
            duration: "Until resolved",
            frequency: null,
          }),
        ],
      }),
    );
    render(<CaseWorkspacePage />);

    await waitFor(() => screen.getByTestId("edited-tracker"));
    expect(screen.getByTestId("edited-tracker")).toHaveTextContent(
      t.editedTracker(3),
    );
  });
});

describe("CaseWorkspacePage failure paths", () => {
  it("shows a retryable error banner when the case fails to load", async () => {
    getCase.mockRejectedValue(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "trace-case001",
        details: {},
      }),
    );
    render(<CaseWorkspacePage />);
    await waitFor(() => screen.getByTestId("error-banner"));

    expect(screen.getByText(t.loadFailed)).toBeTruthy();
  });

  it("retries the case load from the error state", async () => {
    getCase.mockRejectedValueOnce(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "t",
        details: {},
      }),
    );
    render(<CaseWorkspacePage />);
    await waitFor(() => screen.getByTestId("error-banner"));

    fireEvent.click(screen.getByTestId("error-banner-retry"));
    await waitFor(() => screen.getByTestId("case-content"));
    expect(getCase).toHaveBeenCalledTimes(2);
  });
});

describe("CaseWorkspacePage bilingual parity (REQ-006)", () => {
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
        <CaseWorkspacePage />
      </>
    );
  }

  it("renders the workspace copy in Hindi when the locale flips", async () => {
    render(<LangFlipHost />);
    await waitFor(() => screen.getByTestId("case-content"));

    fireEvent.click(screen.getByText("flip-lang"));
    await waitFor(() =>
      expect(screen.getByTestId("stage-label")).toHaveTextContent(
        hiT.stageLabel,
      ),
    );

    expect(screen.getByText(hiT.title)).toBeInTheDocument();
    expect(screen.getByTestId("case-history")).toHaveTextContent(
      hiT.historyHeading,
    );
    // PHASE-8.1 #484: the inner tabs + transcript surface flip langs too.
    expect(screen.getByRole("tab", { name: hiT.tabPreSummary })).toBeTruthy();
    expect(screen.getByTestId("intake-transcript")).toHaveTextContent(
      hiT.transcriptHeading,
    );
  });

  it("renders the prescription drafting copy in Hindi", async () => {
    getCase.mockResolvedValue(caseItem(11, { stage: "prescription_pending" }));
    getWorkingRx.mockResolvedValue(prescription());
    render(<LangFlipHost />);

    await waitFor(() => screen.getByTestId("prescription-editor"));
    fireEvent.click(screen.getByText("flip-lang"));
    await waitFor(() =>
      expect(screen.getByTestId("case-prescription")).toHaveTextContent(
        hiT.prescriptionHeading,
      ),
    );

    expect(screen.getByTestId("case-prescription")).toHaveTextContent(
      hiT.prescriptionHelp,
    );
    expect(screen.getByTestId("rx-source")).toHaveTextContent(
      hiT.sourceAiDraft,
    );
    expect(screen.getByTestId("save-revision-action")).toHaveTextContent(
      hiT.saveRevisionAction,
    );
  });

  it("renders the doctor-input capture copy in Hindi", async () => {
    getCase.mockResolvedValue(caseItem(11, { stage: "prescription_pending" }));
    getWorkingRx.mockRejectedValue(noDraftError());
    render(<LangFlipHost />);

    await waitFor(() => screen.getByTestId("prescription-empty"));
    fireEvent.click(screen.getByText("flip-lang"));
    await waitFor(() =>
      expect(screen.getByTestId("rx-input-capture")).toHaveTextContent(
        hiT.doctorInputHelp,
      ),
    );

    expect(screen.getByTestId("request-draft-blocked-help")).toHaveTextContent(
      hiT.requestDraftBlocked,
    );
    expect(screen.getByTestId("manual-authoring-action")).toHaveTextContent(
      hiT.manualAuthoringAction,
    );
    expect(screen.getByTestId("rx-input-addendum-submit")).toHaveTextContent(
      hiT.addendumSubmit,
    );
  });

  it("renders the approval/rejection/close copy in Hindi", async () => {
    getCase.mockResolvedValue(caseItem(11, { stage: "prescription_pending" }));
    getWorkingRx.mockResolvedValue(prescription());
    render(<LangFlipHost />);

    await waitFor(() => screen.getByTestId("review-decision"));
    fireEvent.click(screen.getByText("flip-lang"));
    await waitFor(() =>
      expect(screen.getByTestId("review-decision")).toHaveTextContent(
        hiT.decisionHeading,
      ),
    );

    expect(screen.getByTestId("review-decision")).toHaveTextContent(
      hiT.verificationDeclaration,
    );
    expect(screen.getByTestId("approve-issue-action")).toHaveTextContent(
      hiT.approveIssueAction,
    );
    expect(screen.getByTestId("case-close")).toHaveTextContent(
      hiT.closeWithoutRxHeading,
    );
  });

  it("renders the issuing doctor's name with Hindi parity", async () => {
    getCase.mockResolvedValue(caseItem(11, { stage: "prescription_pending" }));
    getWorkingRx.mockResolvedValue(prescription());
    doApprove.mockResolvedValue({
      ...prescription(),
      status: "issued",
      issued_at: "2026-09-14T09:30:00Z",
      attributed_doctor_name: "Dr. Priya Verma",
    });
    render(<LangFlipHost />);

    await waitFor(() => screen.getByTestId("approve-issue-action"));
    fireEvent.click(screen.getByText("flip-lang"));
    fireEvent.click(screen.getByTestId("verification-declaration"));
    fireEvent.click(screen.getByTestId("approve-issue-action"));

    await waitFor(() => screen.getByTestId("issued-rx"));
    expect(screen.getByText(hiT.issuedHeading)).toBeTruthy();
    const attribution = screen.getByTestId("issued-attribution");
    expect(attribution).toHaveTextContent("Dr. Priya Verma");
    expect(attribution).not.toHaveTextContent(hiT.issuedAttributedTo);
  });

  it("renders the Hindi fallback attribution when the doctor name is missing", async () => {
    getCase.mockResolvedValue(caseItem(11, { stage: "prescription_pending" }));
    getWorkingRx.mockResolvedValue(prescription());
    doApprove.mockResolvedValue({
      ...prescription(),
      status: "issued",
      issued_at: "2026-09-14T09:30:00Z",
      attributed_doctor_name: null,
    });
    render(<LangFlipHost />);

    await waitFor(() => screen.getByTestId("approve-issue-action"));
    fireEvent.click(screen.getByText("flip-lang"));
    fireEvent.click(screen.getByTestId("verification-declaration"));
    fireEvent.click(screen.getByTestId("approve-issue-action"));

    await waitFor(() => screen.getByTestId("issued-rx"));
    expect(screen.getByTestId("issued-attribution")).toHaveTextContent(
      hiT.issuedAttributedTo,
    );
  });

  it("renders the edited-items tracker copy in Hindi", async () => {
    getCase.mockResolvedValue(caseItem(11, { stage: "prescription_pending" }));
    getWorkingRx.mockResolvedValue(
      prescription({
        items: [
          rxItem(31, {
            name: "Paracetamol",
            dose: "650mg",
            duration: "3 days",
            frequency: "3 times daily",
          }),
        ],
        draft_snapshot: {
          rx_items: [
            {
              name: "Paracetamol",
              dose: "500mg",
              duration: "3 days",
              frequency: "3 times daily",
            },
          ],
        },
      }),
    );
    render(<LangFlipHost />);

    await waitFor(() => screen.getByTestId("edited-tracker"));
    fireEvent.click(screen.getByText("flip-lang"));
    await waitFor(() =>
      expect(screen.getByTestId("edited-tracker")).toHaveTextContent(
        hiT.editedTracker(1),
      ),
    );
  });
});
