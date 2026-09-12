// PHASE-7 T16 (#360): voice intake recorder page suite - the prototype state
// machine (idle -> recording -> preview -> pending -> poor/done), the 180s
// duration cap with live counter, the 3-second usability floor that never
// silent-proceeds, the re-record-or-type prompt wired to the server
// unusable-audio signal, the 3-attempt cap, the upload retry ladder (x3 with
// backoff, no lost input), the in-button Structuring pending state, and
// bilingual EN/HI parity. The recorder and intake API are mocked at the seam
// (jsdom has no getUserMedia/MediaRecorder); the upload retry ladder is the
// real one from lib/intake/voice driven by fake timers.

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import VoiceIntakePage from "./page";
import PatientGroupLayout from "@/app/(patient)/layout";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { __resetLangForTests, useLang } from "@/lib/i18n/LangContext";
import {
  fetchIntake,
  reRecordIntake,
  submitIntake,
  uploadIntakeMedia,
} from "@/lib/intake/api";
import { openMicrophoneRecorder } from "@/lib/intake/recorder";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/patient/intake/voice",
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

const en = STRINGS.en.intake;
const voice = en.voice;
const openMic = vi.mocked(openMicrophoneRecorder);
const upload = vi.mocked(uploadIntakeMedia);
const submit = vi.mocked(submitIntake);
const rerecord = vi.mocked(reRecordIntake);
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
    mode: "voice" as const,
    language: "hi" as const,
    status: "structuring" as const,
    record_attempts: 1,
    text: null,
    transcript: "mock",
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

// jsdom cannot execute playback, so the page's `Audio` constructor is faked:
// it records `play`/`pause` calls and lets tests dispatch synthetic end
// events (testing decision: fake audio element/Audio constructor).
class FakeAudio {
  static instances: FakeAudio[] = [];
  src = "";
  currentTime = 0;
  paused = true;
  private listeners = new Map<string, Set<() => void>>();

  constructor() {
    FakeAudio.instances.push(this);
  }

  play = vi.fn(() => {
    this.paused = false;
    this.emit("play");
    return Promise.resolve();
  });

  pause = vi.fn(() => {
    this.paused = true;
    this.emit("pause");
  });

  addEventListener = vi.fn((type: string, cb: () => void) => {
    const set = this.listeners.get(type) ?? new Set<() => void>();
    set.add(cb);
    this.listeners.set(type, set);
  });

  removeEventListener = vi.fn((type: string, cb: () => void) => {
    const set = this.listeners.get(type);
    if (set === undefined) return;
    set.delete(cb);
    if (set.size === 0) this.listeners.delete(type);
  });

  emit(type: string) {
    this.listeners.get(type)?.forEach((cb) => cb());
  }
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
      <VoiceIntakePage />
    </>
  );
}

beforeEach(() => {
  __resetLangForTests();
  vi.useFakeTimers();
  openMic.mockReset();
  upload.mockReset();
  submit.mockReset();
  rerecord.mockReset();
  pollIntake.mockReset();
  FakeAudio.instances = [];
  URL.createObjectURL = vi.fn(
    () => "blob:mock-audio",
  ) as typeof URL.createObjectURL;
  URL.revokeObjectURL = vi.fn() as unknown as typeof URL.revokeObjectURL;
  vi.stubGlobal("Audio", FakeAudio as unknown as typeof Audio);
});

afterEach(() => {
  vi.useRealTimers();
  cleanup();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
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

/** Render the page, record a take (mic -> stop) ending in the preview stage. */
async function recordTake(seconds: number) {
  render(<VoiceIntakePage />);
  const recorder = fakeRecorder();
  openMic.mockResolvedValue(recorder);
  fireEvent.click(screen.getByTestId("mic-button"));
  await flush();
  await advance(seconds * 1000);
  fireEvent.click(screen.getByTestId("btn-stop"));
  await flush();
  return recorder;
}

function expectVisible(testId: string) {
  expect(screen.getByTestId(testId)).not.toHaveAttribute("hidden");
}

describe("VoiceIntakePage (inside the patient shell)", () => {
  it("mounts within the patient AppShell", () => {
    render(
      <PatientGroupLayout>
        <VoiceIntakePage />
      </PatientGroupLayout>,
    );
    expect(screen.getByTestId("app-shell")).toBeInTheDocument();
  });

  it("renders the idle state: mic target, 00:00 duration, idle copy", () => {
    render(<VoiceIntakePage />);
    expect(screen.getByTestId("mic-button")).toBeInTheDocument();
    expect(screen.getByTestId("mic-button")).not.toBeDisabled();
    expect(screen.getByTestId("duration")).toHaveTextContent("00:00");
    expect(screen.getByTestId("status-line")).toHaveTextContent(
      voice.statusIdle,
    );
  });
});

describe("VoiceIntakePage recording / playback / cap", () => {
  it("starts recording on mic tap and ticks the live duration", async () => {
    const recorder = fakeRecorder();
    openMic.mockResolvedValue(recorder);

    render(<VoiceIntakePage />);
    fireEvent.click(screen.getByTestId("mic-button"));
    await flush();

    expect(recorder.start).toHaveBeenCalled();
    expect(screen.getByTestId("status-line")).toHaveTextContent(
      voice.statusRecording,
    );
    expectVisible("ctrl-record");

    await advance(3500);
    expect(screen.getByTestId("duration")).toHaveTextContent("00:03");
  });

  it("auto-stops at the 180s cap into preview with 03:00 shown", async () => {
    const recorder = fakeRecorder();
    openMic.mockResolvedValue(recorder);

    render(<VoiceIntakePage />);
    fireEvent.click(screen.getByTestId("mic-button"));
    await flush();
    await flush();

    await advance(180_000);
    await flush();

    expect(recorder.stop).toHaveBeenCalled();
    expectVisible("ctrl-preview");
    expect(screen.getByTestId("duration")).toHaveTextContent("03:00");
  });

  it("pauses and resumes the counter", async () => {
    openMic.mockResolvedValue(fakeRecorder());
    render(<VoiceIntakePage />);
    fireEvent.click(screen.getByTestId("mic-button"));
    await flush();

    await advance(2000);
    fireEvent.click(screen.getByTestId("btn-pause"));
    await flush();
    expect(screen.getByTestId("status-line")).toHaveTextContent(
      voice.statusPaused,
    );

    await advance(2000);
    expect(screen.getByTestId("duration")).toHaveTextContent("00:02");

    fireEvent.click(screen.getByTestId("btn-pause"));
    await flush();
    expect(screen.getByTestId("status-line")).toHaveTextContent(
      voice.statusRecording,
    );
    await advance(1000);
    expect(screen.getByTestId("duration")).toHaveTextContent("00:03");
  });

  it("preview stage offers playback, record again, and submit", async () => {
    await recordTake(4);
    expect(screen.getByTestId("btn-play")).toBeInTheDocument();
    expect(screen.getByTestId("btn-again")).toBeInTheDocument();
    expect(screen.getByTestId("btn-submit")).toBeInTheDocument();
  });
});

describe("VoiceIntakePage playback state toggle (#395)", () => {
  it("starts playback and swaps the button to the active Playing state", async () => {
    await recordTake(4);
    fireEvent.click(screen.getByTestId("btn-play"));
    await flush();

    const audio = FakeAudio.instances[0];
    expect(audio.play).toHaveBeenCalled();
    const btn = screen.getByTestId("btn-play");
    expect(btn).toHaveTextContent(voice.playing);
    expect(btn).toHaveAttribute("aria-busy", "true");
    expect(btn).toHaveAttribute("aria-label", voice.playing);
    expect(btn).not.toBeDisabled();
    expect(screen.getByTestId("button-spinner")).toBeInTheDocument();
  });

  it("second click stops playback and reverts to Play preview", async () => {
    await recordTake(4);
    fireEvent.click(screen.getByTestId("btn-play"));
    await flush();
    const audio = FakeAudio.instances[0];

    fireEvent.click(screen.getByTestId("btn-play"));
    await flush();

    expect(audio.pause).toHaveBeenCalled();
    expect(audio.currentTime).toBe(0);
    const btn = screen.getByTestId("btn-play");
    expect(btn).toHaveTextContent(voice.play);
    expect(btn).not.toHaveAttribute("aria-busy");
    expect(btn).toHaveAttribute("aria-label", voice.play);
    expect(screen.queryByTestId("button-spinner")).not.toBeInTheDocument();
  });

  it("reverts automatically when the clip ends on its own", async () => {
    await recordTake(4);
    fireEvent.click(screen.getByTestId("btn-play"));
    await flush();
    const audio = FakeAudio.instances[0];
    expect(screen.getByTestId("btn-play")).toHaveTextContent(voice.playing);

    act(() => audio.emit("ended"));
    await flush();

    const btn = screen.getByTestId("btn-play");
    expect(btn).toHaveTextContent(voice.play);
    expect(btn).not.toHaveAttribute("aria-busy");
    expect(screen.queryByTestId("button-spinner")).not.toBeInTheDocument();

    // A repeated play after completion restarts from the beginning.
    fireEvent.click(btn);
    await flush();
    expect(screen.getByTestId("btn-play")).toHaveTextContent(voice.playing);
    const restarted = FakeAudio.instances[FakeAudio.instances.length - 1];
    expect(restarted.play).toHaveBeenCalled();
  });

  it("clears the active state on Record again even mid-playback", async () => {
    await recordTake(4);
    fireEvent.click(screen.getByTestId("btn-play"));
    await flush();
    const audio = FakeAudio.instances[0];

    fireEvent.click(screen.getByTestId("btn-again"));
    await flush();

    expect(audio.pause).toHaveBeenCalled();
    expect(URL.revokeObjectURL).toHaveBeenCalled();
    expect(screen.getByTestId("status-line")).toHaveTextContent(
      voice.statusRecording,
    );
    expect(screen.queryByTestId("btn-play")).not.toBeInTheDocument();
  });

  it("clears the active state on submit even mid-playback", async () => {
    await recordTake(4);
    fireEvent.click(screen.getByTestId("btn-play"));
    await flush();
    const audio = FakeAudio.instances[0];

    upload.mockResolvedValue(mediaTicket());
    submit.mockResolvedValue({ intake_id: 42, status: "captured" });
    pollIntake.mockResolvedValue(intakeDetail({ status: "ready_for_review" }));

    fireEvent.click(screen.getByTestId("btn-submit"));
    await flush();

    expect(audio.pause).toHaveBeenCalled();
    expect(URL.revokeObjectURL).toHaveBeenCalled();
    expectVisible("ctrl-pending");
    expect(screen.queryByTestId("btn-play")).not.toBeInTheDocument();
  });

  it("unmounts mid-playback without error and detaches audio", async () => {
    render(<VoiceIntakePage />);
    const recorder = fakeRecorder();
    openMic.mockResolvedValue(recorder);
    fireEvent.click(screen.getByTestId("mic-button"));
    await flush();
    await advance(4000);
    fireEvent.click(screen.getByTestId("btn-stop"));
    await flush();
    fireEvent.click(screen.getByTestId("btn-play"));
    await flush();
    const audio = FakeAudio.instances[0];

    expect(() => cleanup()).not.toThrow();
    expect(audio.pause).toHaveBeenCalled();
    expect(audio.removeEventListener).toHaveBeenCalled();
    expect(URL.revokeObjectURL).toHaveBeenCalled();
  });

  it("shows the Hindi Playing label while playing", async () => {
    render(<LangFlipHost />);
    fireEvent.click(screen.getByText("flip-lang"));
    await flush();

    openMic.mockResolvedValue(fakeRecorder());
    fireEvent.click(screen.getByTestId("mic-button"));
    await flush();
    await advance(4000);
    fireEvent.click(screen.getByTestId("btn-stop"));
    await flush();
    fireEvent.click(screen.getByTestId("btn-play"));
    await flush();

    const btn = screen.getByTestId("btn-play");
    expect(btn).toHaveTextContent(STRINGS.hi.intake.voice.playing);
    expect(screen.getByTestId("button-spinner")).toBeInTheDocument();
    expect(btn).toHaveAttribute("aria-busy", "true");
  });
});

describe("VoiceIntakePage 3-second floor (FEAT-006 no silent proceed)", () => {
  it("blocks a take under 3s into the poor prompt without calling the API", async () => {
    await recordTake(2);
    upload.mockClear();
    submit.mockClear();

    fireEvent.click(screen.getByTestId("btn-submit"));
    await flush();

    const warnZone = screen.getByTestId("warn-zone");
    expect(warnZone).toHaveTextContent(voice.poorTitle);
    expect(upload).not.toHaveBeenCalled();
    expect(submit).not.toHaveBeenCalled();
    expect(screen.getByTestId("btn-retry")).toBeInTheDocument();
    expect(screen.getByTestId("btn-type")).toHaveAttribute(
      "href",
      "/patient/intake/text",
    );
  });
});

describe("VoiceIntakePage server unusable-audio signal", () => {
  it("shows the re-record-or-type prompt when the server reports re_record", async () => {
    await recordTake(4);
    upload.mockResolvedValue(mediaTicket());
    submit.mockResolvedValue({ intake_id: 42, status: "captured" });
    pollIntake.mockResolvedValue(
      intakeDetail({ status: "re_record", record_attempts: 2 }),
    );

    fireEvent.click(screen.getByTestId("btn-submit"));
    await flush();
    expectVisible("ctrl-pending");

    await advance(2000); // INTAKE_POLL_INTERVAL_MS - server says unusable
    await flush();

    const warnZone = screen.getByTestId("warn-zone");
    expect(pollIntake).toHaveBeenCalledWith(42);
    expect(warnZone).toHaveTextContent(voice.poorTitle);
    // Attempt 2 of 3: both re-record and type are still on the table.
    expect(screen.getByTestId("btn-retry")).toBeInTheDocument();
    expect(screen.getByTestId("btn-type")).toBeInTheDocument();
  });

  it("shows the same prompt when the server flags transcript unusable", async () => {
    await recordTake(4);
    upload.mockResolvedValue(mediaTicket());
    submit.mockResolvedValue({ intake_id: 42, status: "captured" });
    pollIntake.mockResolvedValue(
      intakeDetail({ transcript_usability: "unusable" }),
    );

    fireEvent.click(screen.getByTestId("btn-submit"));
    await flush();
    await advance(2000);
    await flush();

    expect(screen.getByTestId("warn-zone")).toHaveTextContent(voice.poorTitle);
  });

  it("at the 3rd attempt the prompt asks the patient to type instead", async () => {
    await recordTake(4);
    upload.mockResolvedValue(mediaTicket());
    submit.mockResolvedValue({ intake_id: 42, status: "captured" });
    pollIntake.mockResolvedValue(
      intakeDetail({ status: "re_record", record_attempts: 3 }),
    );

    fireEvent.click(screen.getByTestId("btn-submit"));
    await flush();
    await advance(2000);
    await flush();

    const warnZone = screen.getByTestId("warn-zone");
    expect(warnZone).toHaveTextContent(voice.attemptsExhausted);
    expect(screen.queryByTestId("btn-retry")).not.toBeInTheDocument();
    expect(screen.getByTestId("btn-type")).toBeInTheDocument();
  });

  it("forced-text from the re-record route caps the ladder client-side too", async () => {
    await recordTake(4);

    // First take: published and polled back as re_record (attempt 1).
    upload.mockResolvedValue(mediaTicket());
    submit.mockResolvedValue({ intake_id: 42, status: "captured" });
    pollIntake.mockResolvedValue(
      intakeDetail({ status: "re_record", record_attempts: 1 }),
    );
    fireEvent.click(screen.getByTestId("btn-submit"));
    await flush();
    await advance(2000);
    await flush();
    expect(screen.getByTestId("warn-zone")).toBeInTheDocument();

    // Second take: re-record route answers forced_text (attempt cap reached).
    fireEvent.click(screen.getByTestId("btn-retry"));
    await flush();
    expect(screen.getByTestId("status-line")).toHaveTextContent(
      voice.statusRecording,
    );
    await advance(4000);
    fireEvent.click(screen.getByTestId("btn-stop"));
    await flush();
    expectVisible("ctrl-preview");

    rerecord;

    rerecord.mockResolvedValue({
      intake_id: 42,
      accepted: false,
      status: "ready_for_review",
      record_attempts: 3,
      forced_text: true,
      media_ref_id: null,
    });
    fireEvent.click(screen.getByTestId("btn-submit"));
    await flush();

    expect(rerecord).toHaveBeenCalledWith(
      42,
      expect.objectContaining({ object_key: "intake/abc" }),
    );
    const warnZone = screen.getByTestId("warn-zone");
    expect(warnZone).toHaveTextContent(voice.attemptsExhausted);
    expect(screen.queryByTestId("btn-retry")).not.toBeInTheDocument();
  });
});

describe("VoiceIntakePage submit -> Structuring pending -> pre-summary link", () => {
  it("routes a clean take through in-button pending to the pre-summary review", async () => {
    await recordTake(4);
    upload.mockResolvedValue(mediaTicket());
    submit.mockResolvedValue({ intake_id: 42, status: "captured" });
    pollIntake.mockResolvedValue(intakeDetail({ status: "ready_for_review" }));

    fireEvent.click(screen.getByTestId("btn-submit"));
    await flush();

    // In-button Structuring state: the submit button itself spins, no page spinner.
    const pendingBtn = screen
      .getByTestId("ctrl-pending")
      .querySelector("button");
    expect(pendingBtn).toBeDisabled();
    expect(pendingBtn).toHaveAttribute("aria-busy", "true");
    expect(screen.getByTestId("status-line")).toHaveTextContent(
      voice.statusPending,
    );
    expect(screen.queryByTestId("warn-zone")).not.toBeInTheDocument();

    await advance(2000);
    await flush();

    expect(screen.getByTestId("done-zone")).toBeInTheDocument();
    expect(submit).toHaveBeenCalledWith(
      expect.objectContaining({ mode: "voice", language: "en" }),
    );
    expect(upload).toHaveBeenCalledWith(
      expect.any(Blob),
      expect.objectContaining({ audioDurationMs: 4000 }),
    );
    expect(screen.getByTestId("done-zone")).toHaveTextContent(voice.doneBody);
    expect(screen.getByTestId("btn-next")).toHaveAttribute(
      "href",
      "/patient/intake/42/pre-summary",
    );
    // A captured intake stays re-recordable (prototype btn-again2) while the
    // 3-attempt cap has not been hit.
    expect(screen.getByTestId("btn-again2")).toBeInTheDocument();
  });

  it("hides the done-state record-again once the 3-attempt cap is reached", async () => {
    await recordTake(4);
    upload.mockResolvedValue(mediaTicket());
    submit.mockResolvedValue({ intake_id: 42, status: "captured" });
    pollIntake.mockResolvedValue(
      intakeDetail({ status: "ready_for_review", record_attempts: 3 }),
    );

    fireEvent.click(screen.getByTestId("btn-submit"));
    await flush();
    await advance(2000);
    await flush();

    expect(screen.getByTestId("done-zone")).toBeInTheDocument();
    expect(screen.queryByTestId("btn-again2")).not.toBeInTheDocument();
    expect(screen.getByTestId("btn-next")).toBeInTheDocument();
  });

  it("keeps the patient on the done state if the pipeline is slow but ready", async () => {
    await recordTake(4);
    upload.mockResolvedValue(mediaTicket());
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
});

describe("VoiceIntakePage upload retry ladder", () => {
  it("retries the upload up to 3 times with backoff before giving up", async () => {
    await recordTake(4);
    upload
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(mediaTicket());
    submit.mockResolvedValue({ intake_id: 42, status: "captured" });
    pollIntake.mockResolvedValue(intakeDetail({ status: "ready_for_review" }));

    fireEvent.click(screen.getByTestId("btn-submit"));
    await flush();
    expect(upload).toHaveBeenCalledTimes(1);

    // Attempt 1 fails; backoff 500ms then attempt 2.
    await advance(500);
    expect(upload).toHaveBeenCalledTimes(2);

    // Backoff 1000ms then attempt 3, which succeeds.
    await advance(1000);
    expect(upload).toHaveBeenCalledTimes(3);

    await advance(2000);
    await flush();
    expect(screen.getByTestId("done-zone")).toBeInTheDocument();
    expect(submit).toHaveBeenCalledTimes(1);
  });

  it("preserves the capture and returns to preview when every upload attempt fails", async () => {
    await recordTake(4);
    upload.mockRejectedValue(new TypeError("Failed to fetch"));

    fireEvent.click(screen.getByTestId("btn-submit"));
    // t0 attempt 1 fails, backoff 500ms, attempt 2, backoff 1000ms, attempt 3
    // fails -> error banner and back to preview, capture preserved.
    await advance(1600);
    await flush();

    expect(upload).toHaveBeenCalledTimes(3);
    expect(submit).not.toHaveBeenCalled();
    expect(screen.getByTestId("error-banner")).toHaveTextContent(
      voice.uploadErrorTitle,
    );
    expectVisible("ctrl-preview");

    // Retry from the banner re-runs the same submit without losing the blob.
    upload.mockResolvedValueOnce(mediaTicket());
    submit.mockResolvedValue({ intake_id: 42, status: "captured" });
    pollIntake.mockResolvedValue(intakeDetail({ status: "ready_for_review" }));
    fireEvent.click(screen.getByTestId("error-banner-retry"));
    await flush();
    await advance(2000);
    await flush();

    expect(screen.getByTestId("done-zone")).toBeInTheDocument();
  });
});

describe("VoiceIntakePage bilingual EN/HI (REQ-006)", () => {
  it("switches all visible copy to Hindi when the locale flips", async () => {
    render(<LangFlipHost />);
    fireEvent.click(screen.getByText("flip-lang"));
    await flush();

    const hi = STRINGS.hi.intake.voice;
    expect(
      screen.getByRole("heading", { name: STRINGS.hi.intake.voice.title }),
    ).toBeInTheDocument();
    expect(screen.getByText(hi.reassure)).toBeInTheDocument();
    expect(screen.getByTestId("status-line")).toHaveTextContent(hi.statusIdle);
    expect(screen.getByTestId("breadcrumb-back")).toHaveTextContent(
      STRINGS.hi.intake.breadcrumb,
    );
    expect(screen.getByTestId("breadcrumb-current")).toHaveTextContent(
      hi.breadcrumb,
    );
  });

  it("starts in English with the correct EN strings", () => {
    render(<VoiceIntakePage />);
    expect(
      screen.getByRole("heading", { name: voice.title }),
    ).toBeInTheDocument();
    expect(screen.getByText(voice.reassure)).toBeInTheDocument();
    expect(screen.getByTestId("status-line")).toHaveTextContent(
      voice.statusIdle,
    );
  });
});
