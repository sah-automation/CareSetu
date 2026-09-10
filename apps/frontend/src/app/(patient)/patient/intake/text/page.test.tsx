// PHASE-7 T17 (#361): text intake page suite - the prominent textarea with
// the 2000-char cap enforced in page (maxLength + live counter + slice), the
// bilingual hint (Hindi and English both accepted, REQ-006), the optional
// voice-note attach that is strictly non-blocking and posts as a doctor-only
// media ref (never text, never structuring input), the submit -> in-button
// Structuring pending -> pre-summary link flow, the upload retry ladder (x3
// without losing input), the failure paths (mic unavailable, upload/submit
// failures, server-declared failed), and bilingual EN/HI parity. The recorder
// and intake API are mocked at the seam (jsdom has no getUserMedia/
// MediaRecorder); the upload retry ladder is the real one from lib/intake/voice
// driven by fake timers.

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import TextIntakePage, { TEXT_INTAKE_CAP } from "./page";
import PatientGroupLayout from "@/app/(patient)/layout";
import { ApiError } from "@/lib/api-errors";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { __resetLangForTests, useLang } from "@/lib/i18n/LangContext";
import { fetchIntake, submitIntake, uploadIntakeMedia } from "@/lib/intake/api";
import { openMicrophoneRecorder } from "@/lib/intake/recorder";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/patient/intake/text",
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
  submitIntake: vi.fn(),
  reRecordIntake: vi.fn(),
  fetchIntake: vi.fn(),
  uploadIntakeMedia: vi.fn(),
  savePatientEdits: vi.fn(),
  fetchPreSummary: vi.fn(),
}));

vi.mock("@/lib/intake/recorder", () => ({
  openMicrophoneRecorder: vi.fn(),
}));

const text = STRINGS.en.intake.text;
const openMic = vi.mocked(openMicrophoneRecorder);
const upload = vi.mocked(uploadIntakeMedia);
const submit = vi.mocked(submitIntake);
const pollIntake = vi.mocked(fetchIntake);

function fakeRecorder() {
  return {
    start: vi.fn(),
    pause: vi.fn(),
    resume: vi.fn(),
    stop: vi.fn(async () => new Blob(["audio"], { type: "audio/webm" })),
    close: vi.fn(),
  };
}

function intakeDetail(overrides: Record<string, unknown> = {}) {
  return {
    intake_id: 42,
    patient_id: 7,
    mode: "text" as const,
    language: "en" as const,
    status: "structuring" as const,
    record_attempts: 1,
    text: "fever since two days",
    transcript: null,
    transcript_usability: null,
    forced_text: false,
    media_refs: [],
    created_at: "2026-09-08T10:00:00Z",
    updated_at: "2026-09-08T10:00:00Z",
    ...overrides,
  };
}

function mediaTicket() {
  return {
    object_key: "intake/abc",
    media_type: "audio/webm",
    audio_duration_ms: 4000,
    file_size_bytes: 1234,
    record_attempt: 1,
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
      <TextIntakePage />
    </>
  );
}

beforeEach(() => {
  __resetLangForTests();
  vi.useFakeTimers();
  openMic.mockReset();
  upload.mockReset();
  submit.mockReset();
  pollIntake.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
  cleanup();
  vi.clearAllMocks();
});

/** Flush pending microtasks (mock resolutions) inside act. */
async function flush() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
}

/** Run timers for ms inside act, flushing async continuations. */
async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

/** Render the page, type symptoms, and return the textarea. */
function typeSymptoms(value: string) {
  fireEvent.change(screen.getByTestId("textarea"), { target: { value } });
}

/** Record a voice note (attach -> stop) ending in the preview stage. */
async function recordNote(seconds: number) {
  render(<TextIntakePage />);
  const recorder = fakeRecorder();
  openMic.mockResolvedValue(recorder);
  fireEvent.click(screen.getByTestId("note-attach"));
  await flush();
  await advance(seconds * 1000);
  fireEvent.click(screen.getByTestId("note-stop"));
  await flush();
  return recorder;
}

/** Type symptoms and render the page already in the text-filled idle state. */
async function setupFilledText(value = "fever since two days") {
  render(<TextIntakePage />);
  typeSymptoms(value);
}

function expectVisible(testId: string) {
  expect(screen.getByTestId(testId)).not.toHaveAttribute("hidden");
}

describe("TextIntakePage (inside the patient shell)", () => {
  it("mounts within the patient AppShell", () => {
    render(
      <PatientGroupLayout>
        <TextIntakePage />
      </PatientGroupLayout>,
    );
    expect(screen.getByTestId("app-shell")).toBeInTheDocument();
  });

  it("renders the idle state: textarea, live counter, bilingual hint, disabled submit", () => {
    render(<TextIntakePage />);
    const input = screen.getByTestId("textarea");
    expect(input).toBeInTheDocument();
    expect(input).not.toBeDisabled();
    expect(screen.getByTestId("char-count")).toHaveTextContent(
      `0 / ${TEXT_INTAKE_CAP}`,
    );
    expect(screen.getByTestId("lang-hint")).toHaveTextContent(text.langHint);
    expectVisible("submit-zone");
    expectVisible("warn-empty");
    expect(screen.getByTestId("btn-submit")).toBeDisabled();
  });
});

describe("TextIntakePage textarea cap and enablement", () => {
  it("enables submit once symptoms are typed and hides the empty hint", async () => {
    render(<TextIntakePage />);
    expect(screen.getByTestId("btn-submit")).toBeDisabled();

    typeSymptoms("fever");
    await flush();

    expect(screen.getByTestId("char-count")).toHaveTextContent(
      `5 / ${TEXT_INTAKE_CAP}`,
    );
    expect(screen.queryByTestId("warn-empty")).not.toBeInTheDocument();
    expect(screen.getByTestId("btn-submit")).not.toBeDisabled();
  });

  it("caps typing at 2000 characters in page and reflects it in the counter", async () => {
    render(<TextIntakePage />);
    const overflow = "f".repeat(TEXT_INTAKE_CAP + 50);
    typeSymptoms(overflow);
    await flush();

    const input = screen.getByTestId("textarea") as HTMLTextAreaElement;
    expect(input.value).toHaveLength(TEXT_INTAKE_CAP);
    expect(input).toHaveAttribute("maxlength", String(TEXT_INTAKE_CAP));
    expect(screen.getByTestId("char-count")).toHaveTextContent(
      `${TEXT_INTAKE_CAP} / ${TEXT_INTAKE_CAP}`,
    );
    expect(screen.getByTestId("btn-submit")).not.toBeDisabled();
  });

  it("ignores a submit attempt with whitespace-only text", async () => {
    render(<TextIntakePage />);
    typeSymptoms("   ");
    await flush();

    expect(screen.getByTestId("btn-submit")).toBeDisabled();
    fireEvent.click(screen.getByTestId("btn-submit"));
    await flush();
    expect(submit).not.toHaveBeenCalled();
  });
});

describe("TextIntakePage optional voice-note attach (doctor-only)", () => {
  it("attach -> recording tips the live duration -> stop -> removable preview", async () => {
    render(<TextIntakePage />);
    const recorder = fakeRecorder();
    openMic.mockResolvedValue(recorder);

    fireEvent.click(screen.getByTestId("note-attach"));
    await flush();

    expect(recorder.start).toHaveBeenCalled();
    expect(screen.getByTestId("note-attach")).toHaveAttribute("hidden");
    expectVisible("note-recording");

    await advance(4000);
    expect(screen.getByTestId("note-rec-dur")).toHaveTextContent("00:04");

    fireEvent.click(screen.getByTestId("note-stop"));
    await flush();

    expect(recorder.stop).toHaveBeenCalled();
    expect(screen.getByTestId("note-recording")).toHaveAttribute("hidden");
    expectVisible("note-preview");
    expect(screen.getByTestId("note-preview")).toHaveTextContent(
      text.voicePreview,
    );

    fireEvent.click(screen.getByTestId("note-remove"));
    await flush();
    expect(screen.getByTestId("note-preview")).toHaveAttribute("hidden");
    expectVisible("note-attach");
  });

  it("auto-stops the note at the 180s cap into preview with 03:00 shown", async () => {
    render(<TextIntakePage />);
    const recorder = fakeRecorder();
    openMic.mockResolvedValue(recorder);
    fireEvent.click(screen.getByTestId("note-attach"));
    await flush();
    await flush();

    await advance(180_000);
    await flush();

    expect(recorder.stop).toHaveBeenCalled();
    expectVisible("note-preview");
    expect(screen.getByTestId("note-rec-dur")).toHaveTextContent("03:00");
  });

  it("does not gate the text submit: submit stays disabled only while recording", async () => {
    render(<TextIntakePage />);
    const recorder = fakeRecorder();
    openMic.mockResolvedValue(recorder);

    fireEvent.click(screen.getByTestId("note-attach"));
    await flush();
    typeSymptoms("fever");
    await flush();
    expect(screen.getByTestId("btn-submit")).toBeDisabled();

    fireEvent.click(screen.getByTestId("note-stop"));
    await flush();
    expect(screen.getByTestId("btn-submit")).not.toBeDisabled();
  });
});

describe("TextIntakePage submit -> Structuring pending -> pre-summary link", () => {
  it("sends text-only intake without any note, then advances on ready_for_review", async () => {
    await setupFilledText();
    submit.mockResolvedValue({ intake_id: 42, status: "captured" });
    pollIntake.mockResolvedValue(intakeDetail({ status: "ready_for_review" }));

    fireEvent.click(screen.getByTestId("btn-submit"));
    await flush();

    expect(submit).toHaveBeenCalledWith(
      expect.objectContaining({
        mode: "text",
        language: "en",
        text: "fever since two days",
      }),
    );
    // One-mode-per-intake: text-only carries no media ref, and no upload
    // happens for a note that was never recorded.
    expect(submit.mock.calls[0][0].media_ref).toBeUndefined();
    expect(upload).not.toHaveBeenCalled();

    // In-button Structuring state: the submit button itself spins, never a
    // page spinner (§9.1).
    const pendingBtn = screen
      .getByTestId("ctrl-pending")
      .querySelector("button");
    expect(pendingBtn).toBeDisabled();
    expect(pendingBtn).toHaveAttribute("aria-busy", "true");
    expect(
      screen.getByTestId("ctrl-pending").querySelector("button"),
    ).toHaveTextContent(text.submitting);

    await advance(2000);
    await flush();

    expect(screen.getByTestId("done-zone")).toBeInTheDocument();
    expect(screen.getByTestId("done-zone")).toHaveTextContent(text.doneBody);
    expect(screen.getByTestId("btn-next")).toHaveAttribute(
      "href",
      "/patient/intake/42/pre-summary",
    );
  });

  it("rides an optional note as a doctor-only media ref, never as text", async () => {
    await recordNote(4);
    typeSymptoms("fever since two days");
    upload.mockResolvedValue(mediaTicket());
    submit.mockResolvedValue({ intake_id: 42, status: "captured" });
    pollIntake.mockResolvedValue(intakeDetail({ status: "ready_for_review" }));

    fireEvent.click(screen.getByTestId("btn-submit"));
    await flush();

    expect(upload).toHaveBeenCalledWith(
      expect.any(Blob),
      expect.objectContaining({
        audioDurationMs: 4000,
        filename: "voice-note.webm",
      }),
    );
    expect(submit).toHaveBeenCalledWith(
      expect.objectContaining({
        mode: "text",
        text: "fever since two days",
        media_ref: expect.objectContaining({ object_key: "intake/abc" }),
      }),
    );

    await advance(2000);
    await flush();
    expect(screen.getByTestId("done-zone")).toBeInTheDocument();
  });

  it("keeps polling while structuring, then releases on ready_for_review", async () => {
    await setupFilledText();
    submit.mockResolvedValue({ intake_id: 42, status: "captured" });
    pollIntake.mockResolvedValueOnce(intakeDetail({ status: "structuring" }));
    pollIntake.mockResolvedValueOnce(
      intakeDetail({ status: "ready_for_review" }),
    );

    fireEvent.click(screen.getByTestId("btn-submit"));
    await flush();
    await advance(2000);
    expectVisible("ctrl-pending");
    await advance(2000);
    await flush();

    expect(screen.getByTestId("done-zone")).toBeInTheDocument();
    expect(pollIntake).toHaveBeenCalledTimes(2);
  });

  it("releases to the pre-summary link when the pipeline stalls past MAX polls", async () => {
    await setupFilledText();
    submit.mockResolvedValue({ intake_id: 42, status: "captured" });
    pollIntake.mockResolvedValue(intakeDetail({ status: "structuring" }));

    fireEvent.click(screen.getByTestId("btn-submit"));
    await flush();
    await advance(15 * 2000 + 100);
    await flush();

    expect(screen.getByTestId("done-zone")).toBeInTheDocument();
  });
});

describe("TextIntakePage failure paths (no silent loss, non-blocking note)", () => {
  it("shows the mic-unavailable banner and lets the patient retry the attach", async () => {
    render(<TextIntakePage />);
    openMic.mockRejectedValue(new TypeError("getUserMedia denied"));

    fireEvent.click(screen.getByTestId("note-attach"));
    await flush();

    const banner = screen.getByTestId("error-banner");
    expect(banner).toHaveTextContent(text.micUnavailableTitle);
    expect(screen.getByTestId("note-attach")).not.toHaveAttribute("hidden");

    // Retry from the banner re-attempts the note attach.
    const recorder = fakeRecorder();
    openMic.mockResolvedValue(recorder);
    fireEvent.click(screen.getByTestId("error-banner-retry"));
    await flush();

    expect(recorder.start).toHaveBeenCalled();
    expectVisible("note-recording");
  });

  it("retries a flaky note upload up to 3 times with backoff, then succeeds", async () => {
    await recordNote(4);
    typeSymptoms("fever");
    upload
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(mediaTicket());
    submit.mockResolvedValue({ intake_id: 42, status: "captured" });
    pollIntake.mockResolvedValue(intakeDetail({ status: "ready_for_review" }));

    fireEvent.click(screen.getByTestId("btn-submit"));
    await flush();
    expect(upload).toHaveBeenCalledTimes(1);

    await advance(500);
    expect(upload).toHaveBeenCalledTimes(2);

    await advance(1000);
    expect(upload).toHaveBeenCalledTimes(3);

    await advance(2000);
    await flush();
    expect(screen.getByTestId("done-zone")).toBeInTheDocument();
    expect(submit).toHaveBeenCalledTimes(1);
  });

  it("preserves text and note and returns to the form when every upload attempt fails", async () => {
    await recordNote(4);
    typeSymptoms("fever");
    upload.mockRejectedValue(new TypeError("Failed to fetch"));

    fireEvent.click(screen.getByTestId("btn-submit"));
    await advance(1600);
    await flush();

    expect(upload).toHaveBeenCalledTimes(3);
    expect(submit).not.toHaveBeenCalled();
    expect(screen.getByTestId("error-banner")).toHaveTextContent(
      text.uploadErrorTitle,
    );
    // Neither the text nor the note is lost: the preview chip and the filled
    // textarea are both intact, and the note never gates a later submit.
    expectVisible("note-preview");
    expect((screen.getByTestId("textarea") as HTMLTextAreaElement).value).toBe(
      "fever",
    );

    upload.mockResolvedValueOnce(mediaTicket());
    submit.mockResolvedValue({ intake_id: 42, status: "captured" });
    pollIntake.mockResolvedValue(intakeDetail({ status: "ready_for_review" }));
    fireEvent.click(screen.getByTestId("error-banner-retry"));
    await flush();
    await advance(2000);
    await flush();

    expect(screen.getByTestId("done-zone")).toBeInTheDocument();
  });

  it("returns to the form with text preserved when a text-only submit fails", async () => {
    await setupFilledText();
    submit.mockRejectedValue(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "trace-abcd1234",
        details: {},
      }),
    );

    fireEvent.click(screen.getByTestId("btn-submit"));
    await flush();

    const banner = screen.getByTestId("error-banner");
    expect(banner).toHaveTextContent(text.uploadErrorTitle);
    expect(screen.getByTestId("error-banner-trace-id")).toHaveTextContent(
      "trace-abcd1234",
    );
    expect((screen.getByTestId("textarea") as HTMLTextAreaElement).value).toBe(
      "fever since two days",
    );

    // The banner's Retry re-runs the same submit.
    submit.mockResolvedValue({ intake_id: 42, status: "captured" });
    pollIntake.mockResolvedValue(intakeDetail({ status: "ready_for_review" }));
    fireEvent.click(screen.getByTestId("error-banner-retry"));
    await flush();
    await advance(2000);
    await flush();
    expect(screen.getByTestId("done-zone")).toBeInTheDocument();
  });

  it("shows the upload banner and restores the form when the server fails the intake", async () => {
    await setupFilledText();
    submit.mockResolvedValue({ intake_id: 42, status: "captured" });
    pollIntake.mockResolvedValue(intakeDetail({ status: "failed" }));

    fireEvent.click(screen.getByTestId("btn-submit"));
    await flush();
    await advance(2000);
    await flush();

    expect(screen.getByTestId("error-banner")).toHaveTextContent(
      text.uploadErrorTitle,
    );
    expectVisible("submit-zone");
    expect((screen.getByTestId("textarea") as HTMLTextAreaElement).value).toBe(
      "fever since two days",
    );
  });

  it("refuses to submit a voice note under the 3s floor and keeps the note for re-record or removal", async () => {
    await recordNote(2);
    typeSymptoms("fever");
    upload.mockResolvedValue(mediaTicket());
    submit.mockResolvedValue({ intake_id: 42, status: "captured" });

    fireEvent.click(screen.getByTestId("btn-submit"));
    await flush();

    // Catch the too-short note client-side before any network call: no
    // upload ticket, no submit (mirrors the voice page MIN_RECORD_MS floor).
    expect(upload).not.toHaveBeenCalled();
    expect(submit).not.toHaveBeenCalled();
    const banner = screen.getByTestId("error-banner");
    expect(banner).toHaveTextContent(text.voiceTooShortTitle);

    // The note stays attached (never silently lost) so the patient can
    // re-record or remove it; the text remains intact and submittable.
    expectVisible("note-preview");
    expect((screen.getByTestId("textarea") as HTMLTextAreaElement).value).toBe(
      "fever",
    );

    // Removing the short note unlocks a clean text-only submit.
    fireEvent.click(screen.getByTestId("note-remove"));
    await flush();
    fireEvent.click(screen.getByTestId("btn-submit"));
    await flush();
    expect(upload).not.toHaveBeenCalled();
    expect(submit).toHaveBeenCalledWith(
      expect.objectContaining({ mode: "text", text: "fever" }),
    );
  });
});

describe("TextIntakePage bilingual EN/HI (REQ-006)", () => {
  it("starts in English with the correct EN strings", () => {
    render(<TextIntakePage />);
    expect(
      screen.getByRole("heading", { name: text.title }),
    ).toBeInTheDocument();
    expect(screen.getByText(text.reassure)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(text.placeholder)).toBeInTheDocument();
    expect(screen.getByTestId("lang-hint")).toHaveTextContent(text.langHint);
  });

  it("switches all visible copy to Hindi when the locale flips", async () => {
    render(<LangFlipHost />);
    fireEvent.click(screen.getByText("flip-lang"));
    await flush();

    const hi = STRINGS.hi.intake.text;
    expect(screen.getByRole("heading", { name: hi.title })).toBeInTheDocument();
    expect(screen.getByText(hi.reassure)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(hi.placeholder)).toBeInTheDocument();
    expect(screen.getByTestId("lang-hint")).toHaveTextContent(hi.langHint);
    expect(screen.getByTestId("breadcrumb-back")).toHaveTextContent(
      STRINGS.hi.intake.breadcrumb,
    );
    expect(screen.getByTestId("breadcrumb-current")).toHaveTextContent(
      hi.breadcrumb,
    );
  });
});
