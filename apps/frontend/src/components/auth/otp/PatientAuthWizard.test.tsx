// PHASE-2 T9 (ticket #60): frontend unit coverage for the patient auth wizard.
// Test names follow the ticket's acceptance criteria - register validation,
// verify states (wrong/expired/used), resend cooldown + latest-wins, lockout
// blocking, the duplicate-number notice, session storage landing on the
// authenticated view, and the hi/en toggle throughout.
// Updated for T6 (#152): AuthenticatedHome removed, redirect to /patient.
//
// #563: why the done-screen countdown tests flush instead of waiting. The
// countdown clock fakes ONLY the interval (see `fakeCountdownClock`), and that
// partial fake silently disarms `@testing-library/dom`'s `waitFor`. `waitFor`
// decides how to poll by asking `jestFakeTimersAreEnabled()`, which probes
// `setTimeout` alone and, with no `jest` global under Vitest, always answers
// `false`. So a `waitFor` opened under the fake clock takes its "real timers"
// path: it registers a MutationObserver and arms its 50ms re-poll on
// `setInterval` - the one function the fake owns. That poll can then only fire
// from `tick`, and a re-render to identical output (the done screen's
// `setDeparted(true)`) trips no observer either, so any wait whose assertion
// needs a re-check after an async flush never gets one. Its 1000ms timeout
// stays real, so such a wait runs out and reports that stale first check.
//
// THE RULE: under `fakeCountdownClock`, a wait is only trustworthy if a DOM
// mutation satisfies it - which is why the flow helpers' `findBy*` are fine
// (each either finds its element on the synchronous first check, or is woken
// by the React commit that resolves its promise), and why a bare `getByText`
// for the released countdown, or a `waitFor` on the CTA's navigation, is not.
// Vitest's own `vi.waitFor` is the one exception: it polls on `setTimeout`,
// which this fake leaves alone. For anything the resume seam or the navigate
// routine produces, flush first with `tick(0)` and then assert. Both #563
// failures were that exact mistake.

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  fetchDemoOtp,
  issueSession,
  registerPhone,
  resendOtp,
  type RegisterResult,
  type SessionResult,
  verifyOtp,
  type VerifyResult,
} from "@/lib/auth/api";
import { PatientAuthWizard } from "./PatientAuthWizard";
import { DONE_SCREEN_COUNTDOWN_SECONDS } from "../DoneScreen";

vi.mock("@/lib/auth/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/auth/api")>();
  return {
    ...mod,
    registerPhone: vi.fn(),
    verifyOtp: vi.fn(),
    resendOtp: vi.fn(),
    issueSession: vi.fn(),
    fetchDemoOtp: vi.fn(),
  };
});

// #496: the wizard invokes the session-resume seam right after persisting a
// new session, so identity resolves in-flow without a reload.
const state = vi.hoisted(() => ({
  resumeSession: vi.fn(),
}));

vi.mock("@/lib/auth/AuthContext", () => ({
  useAuth: () => ({
    user: null,
    selectedRole: null,
    switchRole: vi.fn(),
    logout: vi.fn(),
    isAuthenticated: false,
    isLoading: false,
    resumeSession: state.resumeSession,
  }),
}));

const mockReplace = vi.fn();
const stableRouter = { replace: mockReplace };

vi.mock("next/navigation", () => ({
  useRouter: () => stableRouter,
}));

const PHONE = "+919876543210";
const REGISTER_OK: RegisterResult = {
  outcome: "sent",
  phone_e164: PHONE,
  identity_id: 1,
  challenge_id: 11,
  is_existing: false,
  flow: "register",
  expires_in_seconds: 300,
  cooldown_remaining_seconds: 60,
  attempts_left: 5,
  lockout_remaining_seconds: null,
};

const REGISTER_DUPLICATE: RegisterResult = {
  ...REGISTER_OK,
  is_existing: true,
  flow: "login",
};

const SESSION: SessionResult = {
  jwt: "header.payload.signature",
  jti: "jti-1",
  scope: "patient",
  identity_id: 1,
  expires_in_seconds: 900,
  refresh_token: "opaque-refresh-token",
};

function verifiedResult(): VerifyResult {
  return {
    outcome: "verified",
    phone_e164: PHONE,
    identity_id: 1,
    attempts_left: null,
    lockout_remaining_seconds: null,
  };
}

async function enterPhone(digits = "9876543210") {
  fireEvent.change(
    await screen.findByPlaceholderText("10-digit mobile number"),
    { target: { value: digits } },
  );
}

async function startOtpFlow(
  registerResult: RegisterResult = REGISTER_OK,
): Promise<void> {
  vi.mocked(registerPhone).mockResolvedValue(registerResult);
  render(<PatientAuthWizard />);
  await enterPhone();
  fireEvent.click(
    screen.getByRole("button", { name: "Get verification code" }),
  );
  await screen.findByText(/6-digit code sent by SMS to/);
}

function typeOtp(digits = "123456") {
  fireEvent.change(screen.getByLabelText("Verification code"), {
    target: { value: digits },
  });
}

function verifyButton() {
  return screen.getByRole("button", { name: "Verify & continue" });
}

// #551: the done-screen countdown is driven by faking ONLY the interval, so
// the async flow helpers above (findBy*) keep their real timers while the
// 5-second tick becomes drivable. #563: what that partial fake costs, and the
// rule it forces on every test that installs it, is in the file header.
function fakeCountdownClock() {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
}

/**
 * Run the faked countdown forward by `ms`, flushing interval callbacks.
 *
 * #563: `tick(0)` is the flush - it drains the microtask queue inside `act`
 * without moving the countdown, which is what settles the session-resume seam
 * and commits the state it releases, and what lets the post-resume navigation
 * run. See the file header for why a wait cannot be relied on here instead.
 */
async function tick(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
  // #563: this suite declared mocks and cleared no call counts at all. Not the
  // cause of the two countdown failures (beforeEach already resets every mock),
  // but a leak of the same class as #562's, so it is closed here.
  vi.clearAllMocks();
});

beforeEach(() => {
  localStorage.clear();
  vi.mocked(registerPhone).mockReset();
  vi.mocked(verifyOtp).mockReset();
  vi.mocked(resendOtp).mockReset();
  vi.mocked(issueSession).mockReset();
  vi.mocked(fetchDemoOtp).mockReset();
  mockReplace.mockReset();
  state.resumeSession.mockReset();
  // Default: the seam settles immediately (the app awaits it before routing).
  state.resumeSession.mockResolvedValue(undefined);
});

describe("PatientAuthWizard - phone step", () => {
  it("renders the phone step once hydrated and does not call the API", async () => {
    render(<PatientAuthWizard />);

    expect(
      await screen.findByPlaceholderText("10-digit mobile number"),
    ).toBeInTheDocument();
    expect(registerPhone).not.toHaveBeenCalled();
  });

  it("shows the validation error for an invalid number and never calls the API", async () => {
    render(<PatientAuthWizard />);
    await enterPhone("123");

    fireEvent.click(
      screen.getByRole("button", { name: "Get verification code" }),
    );

    expect(
      await screen.findByText("Enter a valid 10-digit Indian mobile number."),
    ).toBeInTheDocument();
    expect(registerPhone).not.toHaveBeenCalled();
  });

  it("normalizes a valid number and moves to the verify step", async () => {
    await startOtpFlow();

    expect(registerPhone).toHaveBeenCalledWith(PHONE);
    expect(screen.getByText(PHONE)).toBeInTheDocument();
    expect(verifyButton()).toBeInTheDocument();
  });

  it("shows the already-registered login notice for a duplicate number", async () => {
    vi.mocked(registerPhone).mockResolvedValue(REGISTER_DUPLICATE);
    render(<PatientAuthWizard />);
    await enterPhone();
    fireEvent.click(
      screen.getByRole("button", { name: "Get verification code" }),
    );

    expect(
      await screen.findByText(
        "This number is already registered - verifying logs you in.",
      ),
    ).toBeInTheDocument();
  });
});

describe("PatientAuthWizard - register refusal states", () => {
  it("cooldown outcome stays on the phone step with the live countdown", async () => {
    vi.mocked(registerPhone).mockResolvedValue({
      outcome: "cooldown",
      phone_e164: PHONE,
      identity_id: 1,
      challenge_id: null,
      is_existing: true,
      flow: "login",
      expires_in_seconds: null,
      cooldown_remaining_seconds: 45,
      attempts_left: null,
      lockout_remaining_seconds: null,
    });
    render(<PatientAuthWizard />);
    await enterPhone();
    fireEvent.click(
      screen.getByRole("button", { name: "Get verification code" }),
    );

    expect(await screen.findByText(/Resend in \d+s/)).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText("10-digit mobile number"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("group", { name: "OTP" }),
    ).not.toBeInTheDocument();
  });

  it("locked outcome shows the lockout message and blocks the phone step", async () => {
    vi.mocked(registerPhone).mockResolvedValue({
      outcome: "locked",
      phone_e164: PHONE,
      identity_id: 1,
      challenge_id: null,
      is_existing: true,
      flow: "login",
      expires_in_seconds: null,
      cooldown_remaining_seconds: null,
      attempts_left: null,
      lockout_remaining_seconds: 900,
    });
    render(<PatientAuthWizard />);
    await enterPhone();
    fireEvent.click(
      screen.getByRole("button", { name: "Get verification code" }),
    );

    expect(
      await screen.findByText(
        "Too many failed attempts. Verification locked for 15 min.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Get verification code" }),
    ).toBeDisabled();
    expect(
      screen.queryByRole("group", { name: "OTP" }),
    ).not.toBeInTheDocument();
  });

  it("suspended outcome shows the suspended notice on the phone step", async () => {
    vi.mocked(registerPhone).mockResolvedValue({
      outcome: "suspended",
      phone_e164: PHONE,
      identity_id: 1,
      challenge_id: null,
      is_existing: true,
      flow: "login",
      expires_in_seconds: null,
      cooldown_remaining_seconds: null,
      attempts_left: null,
      lockout_remaining_seconds: null,
    });
    render(<PatientAuthWizard />);
    await enterPhone();
    fireEvent.click(
      screen.getByRole("button", { name: "Get verification code" }),
    );

    expect(
      await screen.findByText(
        "This number is suspended. Contact support for assistance.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("group", { name: "OTP" }),
    ).not.toBeInTheDocument();
  });
});

describe("PatientAuthWizard - verify step", () => {
  it("wrong code shows the attempts-left error", async () => {
    await startOtpFlow();
    vi.mocked(verifyOtp).mockResolvedValue({
      outcome: "wrong_code",
      phone_e164: PHONE,
      identity_id: null,
      attempts_left: 4,
      lockout_remaining_seconds: null,
    });

    typeOtp("111111");
    fireEvent.click(verifyButton());

    expect(
      await screen.findByText("Wrong code. 4 attempts left."),
    ).toBeInTheDocument();
  });

  it("expired code shows the request-new-code message", async () => {
    await startOtpFlow();
    vi.mocked(verifyOtp).mockResolvedValue({
      outcome: "expired",
      phone_e164: PHONE,
      identity_id: null,
      attempts_left: null,
      lockout_remaining_seconds: null,
    });

    typeOtp("123456");
    fireEvent.click(verifyButton());

    expect(
      await screen.findByText(
        "This code has expired or was already used. Request a new one.",
      ),
    ).toBeInTheDocument();
  });

  it("used code shows the request-new-code message", async () => {
    await startOtpFlow();
    vi.mocked(verifyOtp).mockResolvedValue({
      outcome: "spent",
      phone_e164: PHONE,
      identity_id: null,
      attempts_left: null,
      lockout_remaining_seconds: null,
    });

    typeOtp("123456");
    fireEvent.click(verifyButton());

    expect(
      await screen.findByText(
        "This code has expired or was already used. Request a new one.",
      ),
    ).toBeInTheDocument();
  });

  it("zero attempts left renders the request-a-new-code hint", async () => {
    await startOtpFlow();
    vi.mocked(verifyOtp).mockResolvedValue({
      outcome: "wrong_code",
      phone_e164: PHONE,
      identity_id: null,
      attempts_left: 0,
      lockout_remaining_seconds: null,
    });

    typeOtp("111111");
    fireEvent.click(verifyButton());

    expect(
      await screen.findByText("No attempts left. Request a new code."),
    ).toBeInTheDocument();
  });

  it("lockout state renders the lockout message and blocks input", async () => {
    await startOtpFlow();
    vi.mocked(verifyOtp).mockResolvedValue({
      outcome: "locked",
      phone_e164: PHONE,
      identity_id: null,
      attempts_left: null,
      lockout_remaining_seconds: 900,
    });

    typeOtp("123456");
    fireEvent.click(verifyButton());

    expect(
      await screen.findByText(
        "Too many failed attempts. Verification locked for 15 min.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Verification code")).toBeDisabled();
  });

  it("disables resend while the cooldown is active", async () => {
    await startOtpFlow();

    const resend = screen.getByRole("button", { name: "Resend code" });
    expect(resend).toBeDisabled();
    fireEvent.click(resend);
    expect(resendOtp).not.toHaveBeenCalled();
  });

  it("resend past the cooldown shows the latest-wins notice", async () => {
    await startOtpFlow({
      ...REGISTER_OK,
      cooldown_remaining_seconds: 0,
    });
    vi.mocked(resendOtp).mockResolvedValue({
      outcome: "sent",
      phone_e164: PHONE,
      challenge_id: 12,
      expires_in_seconds: 300,
      cooldown_remaining_seconds: 60,
      lockout_remaining_seconds: null,
      attempts_left: 5,
    });

    const resend = screen.getByRole("button", { name: "Resend code" });
    expect(resend).toBeEnabled();
    fireEvent.click(resend);

    expect(
      await screen.findByText(
        "A new code was sent. The previous code is no longer valid.",
      ),
    ).toBeInTheDocument();
  });
});

describe("PatientAuthWizard - resend refuse states", () => {
  it("cooldown outcome shows the cooldown countdown", async () => {
    await startOtpFlow({ ...REGISTER_OK, cooldown_remaining_seconds: 0 });
    vi.mocked(resendOtp).mockResolvedValue({
      outcome: "cooldown",
      phone_e164: PHONE,
      challenge_id: null,
      expires_in_seconds: null,
      cooldown_remaining_seconds: 60,
      lockout_remaining_seconds: null,
      attempts_left: null,
    });

    fireEvent.click(screen.getByRole("button", { name: "Resend code" }));

    expect(
      await screen.findByText("Cooldown active. Resend in 60s."),
    ).toBeInTheDocument();
  });

  it("locked outcome renders the lockout and blocks input", async () => {
    await startOtpFlow({ ...REGISTER_OK, cooldown_remaining_seconds: 0 });
    vi.mocked(resendOtp).mockResolvedValue({
      outcome: "locked",
      phone_e164: PHONE,
      challenge_id: null,
      expires_in_seconds: null,
      cooldown_remaining_seconds: null,
      lockout_remaining_seconds: 900,
      attempts_left: null,
    });

    fireEvent.click(screen.getByRole("button", { name: "Resend code" }));

    expect(
      await screen.findByText(
        "Too many failed attempts. Verification locked for 15 min.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Verification code")).toBeDisabled();
  });

  it("suspended outcome shows the suspended notice", async () => {
    await startOtpFlow({ ...REGISTER_OK, cooldown_remaining_seconds: 0 });
    vi.mocked(resendOtp).mockResolvedValue({
      outcome: "suspended",
      phone_e164: PHONE,
      challenge_id: null,
      expires_in_seconds: null,
      cooldown_remaining_seconds: null,
      lockout_remaining_seconds: null,
      attempts_left: null,
    });

    fireEvent.click(screen.getByRole("button", { name: "Resend code" }));

    expect(
      await screen.findByText(
        "This number is suspended. Contact support for assistance.",
      ),
    ).toBeInTheDocument();
  });

  it("no-identity outcome returns to the phone step with the notice", async () => {
    await startOtpFlow({ ...REGISTER_OK, cooldown_remaining_seconds: 0 });
    vi.mocked(resendOtp).mockResolvedValue({
      outcome: "no_identity",
      phone_e164: PHONE,
      challenge_id: null,
      expires_in_seconds: null,
      cooldown_remaining_seconds: null,
      lockout_remaining_seconds: null,
      attempts_left: null,
    });

    fireEvent.click(screen.getByRole("button", { name: "Resend code" }));

    expect(
      await screen.findByText(
        "This number was never registered. Go back and get a code first.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText("10-digit mobile number"),
    ).toBeInTheDocument();
  });
});

describe("PatientAuthWizard - success and session", () => {
  it("stores the session, shows the Done step, and redirects to /patient", async () => {
    await startOtpFlow();
    vi.mocked(verifyOtp).mockResolvedValue(verifiedResult());
    vi.mocked(issueSession).mockResolvedValue(SESSION);

    typeOtp();
    fireEvent.click(verifyButton());

    expect(await screen.findByText("Identity verified")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Go to Dashboard" }));

    expect(issueSession).toHaveBeenCalledWith(PHONE);
    // #551: the CTA now shares the auto path's resume-then-navigate ordering,
    // so the route lands one microtask later - never identity-less.
    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith("/patient"));

    const stored = JSON.parse(localStorage.getItem("caresetu.session") ?? "{}");
    expect(stored.jwt).toBe("header.payload.signature");
    expect(stored.refresh_token).toBe("opaque-refresh-token");
  });

  it("shows the shared done screen, counts down, and redirects at zero (#551)", async () => {
    fakeCountdownClock();
    try {
      await startOtpFlow();
      vi.mocked(verifyOtp).mockResolvedValue(verifiedResult());
      vi.mocked(issueSession).mockResolvedValue(SESSION);
      mockReplace.mockClear();

      typeOtp();
      fireEvent.click(verifyButton());

      // The resume seam settles, so the countdown is released with its full
      // duration and the verified state stands on its own - the blank-flash
      // regression guard.
      expect(await screen.findByText("Identity verified")).toBeInTheDocument();
      // #563: the released countdown only exists once the resume seam's
      // microtask has committed, so flush it before reading the DOM.
      await tick(0);
      expect(
        screen.getByText("Your number is verified and your session is ready."),
      ).toBeInTheDocument();
      expect(
        screen.getByText(
          `Opening your dashboard in ${DONE_SCREEN_COUNTDOWN_SECONDS}`,
        ),
      ).toBeInTheDocument();
      expect(screen.getByRole("progressbar")).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: "Go to Dashboard" }),
      ).toBeInTheDocument();

      // Mid-countdown: still counting, and the CTA stays available.
      await tick(2000);
      expect(mockReplace).not.toHaveBeenCalled();
      expect(screen.getByRole("status")).toHaveTextContent(
        "Opening your dashboard in 3",
      );

      // At zero the auto-redirect fires.
      await tick(DONE_SCREEN_COUNTDOWN_SECONDS * 1000);
      expect(mockReplace).toHaveBeenCalledWith("/patient");
    } finally {
      vi.useRealTimers();
    }
  });

  it("holds the countdown back until the resume seam settles (#551)", async () => {
    fakeCountdownClock();
    try {
      await startOtpFlow();
      vi.mocked(verifyOtp).mockResolvedValue(verifiedResult());
      vi.mocked(issueSession).mockResolvedValue(SESSION);

      let release: () => void;
      const gate = new Promise<void>((resolve) => {
        release = resolve;
      });
      state.resumeSession.mockReturnValue(gate);
      mockReplace.mockClear();

      typeOtp();
      fireEvent.click(verifyButton());

      expect(await screen.findByText("Identity verified")).toBeInTheDocument();
      await vi.waitFor(() => expect(state.resumeSession).toHaveBeenCalled());

      // The resume call has not resolved: no digits, and the clock never runs
      // behind it, however long the seam takes.
      expect(screen.getByRole("status")).toHaveTextContent(
        "Opening your dashboard",
      );
      expect(
        screen.queryByText(/Opening your dashboard in/),
      ).not.toBeInTheDocument();
      await tick(DONE_SCREEN_COUNTDOWN_SECONDS * 1000 * 2);
      expect(
        screen.queryByText(/Opening your dashboard in/),
      ).not.toBeInTheDocument();
      expect(mockReplace).not.toHaveBeenCalled();

      // Once it settles the countdown starts from the top and owns the
      // auto-redirect.
      release!();
      await tick(0);
      expect(screen.getByRole("status")).toHaveTextContent(
        `Opening your dashboard in ${DONE_SCREEN_COUNTDOWN_SECONDS}`,
      );
      await tick(DONE_SCREEN_COUNTDOWN_SECONDS * 1000);
      expect(mockReplace).toHaveBeenCalledWith("/patient");
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not double-navigate when the CTA is pressed mid-countdown (#551)", async () => {
    fakeCountdownClock();
    try {
      await startOtpFlow();
      vi.mocked(verifyOtp).mockResolvedValue(verifiedResult());
      vi.mocked(issueSession).mockResolvedValue(SESSION);
      mockReplace.mockClear();

      typeOtp();
      fireEvent.click(verifyButton());
      expect(await screen.findByText("Identity verified")).toBeInTheDocument();

      // Wait for the resume seam to settle and the countdown to start.
      // #563: flushed, not waited on - see the file header.
      await tick(0);
      expect(screen.getByRole("status")).toHaveTextContent(
        `Opening your dashboard in ${DONE_SCREEN_COUNTDOWN_SECONDS}`,
      );

      await tick(2000);
      fireEvent.click(screen.getByRole("button", { name: "Go to Dashboard" }));
      // #563: `landOnReturnTarget` routes inside `resumeOnce().then(...)`, one
      // microtask after the click, and the click's re-render is identical so
      // nothing would re-check it. Flush, then assert.
      await tick(0);
      expect(mockReplace).toHaveBeenCalledWith("/patient");

      // The countdown reaching zero must not navigate a second time.
      await tick(DONE_SCREEN_COUNTDOWN_SECONDS * 1000);
      expect(mockReplace).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("awaits the session-resume seam before routing to the return target (#496)", async () => {
    await startOtpFlow();
    vi.mocked(verifyOtp).mockResolvedValue(verifiedResult());
    vi.mocked(issueSession).mockResolvedValue(SESSION);

    // The seam must settle BEFORE the post-login route mounts, so the patient
    // surface never renders identity-less (and never remounts mid-flow).
    let release: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    state.resumeSession.mockReturnValue(gate);
    mockReplace.mockClear();

    typeOtp();
    fireEvent.click(verifyButton());

    await vi.waitFor(() => expect(state.resumeSession).toHaveBeenCalled());
    expect(
      mockReplace,
      "must not route before the seam settles",
    ).not.toHaveBeenCalled();

    fakeCountdownClock();
    try {
      release!();
      await tick(0);
      // Settled: the countdown now owns the auto-redirect (#551), so the route
      // still has not fired.
      expect(
        mockReplace,
        "must not route before the countdown completes",
      ).not.toHaveBeenCalled();
      await tick(DONE_SCREEN_COUNTDOWN_SECONDS * 1000);
      expect(mockReplace).toHaveBeenCalledWith("/patient");
    } finally {
      vi.useRealTimers();
    }
  });

  it("a stored session triggers a redirect to /patient without showing the form", async () => {
    localStorage.setItem(
      "caresetu.session",
      JSON.stringify({
        jwt: "header.payload.signature",
        refresh_token: "opaque-refresh-token",
        jti: "jti-1",
        scope: "patient",
        identity_id: 1,
        phone: PHONE,
      }),
    );

    render(<PatientAuthWizard />);

    // Wait for hydration and redirect
    await vi.waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/patient");
    });
    expect(registerPhone).not.toHaveBeenCalled();
  });

  // PHASE-2.6 T07 (#198): the proxy's return-url must survive the whole OTP
  // wizard - a deep link bounced to /login?return=... lands back on the
  // original destination after sign-in, never dead-ending on /patient.
  describe("return-url redirect target", () => {
    async function completeFlowWithReturnTo(returnTo: string) {
      vi.mocked(registerPhone).mockResolvedValue(REGISTER_OK);
      render(<PatientAuthWizard returnTo={returnTo} />);
      await enterPhone();
      fireEvent.click(
        screen.getByRole("button", { name: "Get verification code" }),
      );
      await screen.findByText(/6-digit code sent by SMS to/);
      vi.mocked(verifyOtp).mockResolvedValue(verifiedResult());
      vi.mocked(issueSession).mockResolvedValue(SESSION);
      typeOtp();
      fireEvent.click(verifyButton());
      expect(await screen.findByText("Identity verified")).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "Go to Dashboard" }));
      // #551: the CTA resumes the session first, so the route lands one
      // microtask after the click.
      await waitFor(() => expect(mockReplace).toHaveBeenCalledWith(returnTo));
    }

    it("redirects to the returnTo prop after the Done step", async () => {
      await completeFlowWithReturnTo("/patient/record");
    });

    it("falls back to /patient when no returnTo is given", async () => {
      await completeFlowWithReturnTo("/patient");
    });

    it("routes an already-stored session to the returnTo prop", async () => {
      localStorage.setItem(
        "caresetu.session",
        JSON.stringify({
          jwt: "header.payload.signature",
          refresh_token: "opaque-refresh-token",
          jti: "jti-1",
          scope: "patient",
          identity_id: 1,
          phone: PHONE,
        }),
      );

      render(<PatientAuthWizard returnTo="/patient/bookings" />);

      await vi.waitFor(() => {
        expect(mockReplace).toHaveBeenCalledWith("/patient/bookings");
      });
    });
  });

  it("clears the session on sign out and returns to the phone step", async () => {
    await startOtpFlow();
    vi.mocked(verifyOtp).mockResolvedValue(verifiedResult());
    vi.mocked(issueSession).mockResolvedValue(SESSION);
    typeOtp();
    fireEvent.click(verifyButton());
    await screen.findByText("Identity verified");

    // After successful verify, the component redirects. Verify session was stored.
    expect(localStorage.getItem("caresetu.session")).not.toBeNull();

    // Sign out clears the session
    const { clearSession } = await import("@/lib/auth/session");
    clearSession();
    expect(localStorage.getItem("caresetu.session")).toBeNull();
  });
});

describe("PatientAuthWizard - demo OTP banner", () => {
  it("shows the banner with the fetched code after a successful register", async () => {
    vi.stubEnv("NEXT_PUBLIC_DEMO_MODE", "true");
    vi.mocked(fetchDemoOtp).mockResolvedValue("424242");

    await startOtpFlow();

    expect(await screen.findByText("Demo OTP: 424242")).toBeInTheDocument();
    expect(fetchDemoOtp).toHaveBeenCalledWith(PHONE);
  });

  it("re-fetches and shows the new code after a successful resend", async () => {
    vi.stubEnv("NEXT_PUBLIC_DEMO_MODE", "true");
    vi.mocked(fetchDemoOtp).mockResolvedValue("424242");
    await startOtpFlow({ ...REGISTER_OK, cooldown_remaining_seconds: 0 });
    expect(await screen.findByText("Demo OTP: 424242")).toBeInTheDocument();

    vi.mocked(fetchDemoOtp).mockResolvedValue("999999");
    vi.mocked(resendOtp).mockResolvedValue({
      outcome: "sent",
      phone_e164: PHONE,
      challenge_id: 12,
      expires_in_seconds: 300,
      cooldown_remaining_seconds: 60,
      lockout_remaining_seconds: null,
      attempts_left: 5,
    });
    fireEvent.click(screen.getByRole("button", { name: "Resend code" }));

    expect(await screen.findByText("Demo OTP: 999999")).toBeInTheDocument();
    expect(fetchDemoOtp).toHaveBeenCalledTimes(2);
  });

  it("shows no banner when the read-back is unavailable", async () => {
    vi.stubEnv("NEXT_PUBLIC_DEMO_MODE", "true");
    vi.mocked(fetchDemoOtp).mockResolvedValue(null);

    await startOtpFlow();

    await waitFor(() => {
      expect(fetchDemoOtp).toHaveBeenCalledWith(PHONE);
    });
    expect(screen.queryByText(/Demo OTP:/)).not.toBeInTheDocument();
  });

  it("without the flag there is no banner and no read-back call", async () => {
    await startOtpFlow();

    expect(fetchDemoOtp).not.toHaveBeenCalled();
    expect(screen.queryByText(/Demo OTP:/)).not.toBeInTheDocument();
  });
});

describe("PatientAuthWizard - language toggle", () => {
  it("switches to Hindi and back to English across steps", async () => {
    render(<PatientAuthWizard />);
    await screen.findByPlaceholderText("10-digit mobile number");

    fireEvent.click(screen.getByRole("button", { name: "हिंदी" }));
    expect(
      await screen.findByPlaceholderText("10 अंकों का मोबाइल नंबर"),
    ).toBeInTheDocument();

    vi.mocked(registerPhone).mockResolvedValue(REGISTER_OK);
    fireEvent.change(screen.getByPlaceholderText("10 अंकों का मोबाइल नंबर"), {
      target: { value: "9876543210" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "वेरिफिकेशन कोड पाएँ" }),
    );
    await screen.findByText(/SMS से भेजा गया 6 अंकों का कोड/);

    fireEvent.click(screen.getByRole("button", { name: "EN" }));
    expect(
      screen.getByRole("button", { name: "Resend code" }),
    ).toBeInTheDocument();
  });
});
