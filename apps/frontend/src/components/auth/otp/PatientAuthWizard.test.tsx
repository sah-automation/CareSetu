// PHASE-2 T9 (ticket #60): frontend unit coverage for the patient auth wizard.
// Test names follow the ticket's acceptance criteria - register validation,
// verify states (wrong/expired/used), resend cooldown + latest-wins, lockout
// blocking, the duplicate-number notice, session storage landing on the
// authenticated view, and the hi/en toggle throughout.
// Updated for T6 (#152): AuthenticatedHome removed, redirect to /patient.
//
// #563: why the done-screen tests flush instead of waiting. Under the handoff
// clock fake (`fakeHandoffClock`, which since #580 owns `setInterval` AND
// `setTimeout`) every RTL wait in this file hangs. `@testing-library/react`'s
// `asyncWrapper` drains its microtask queue with a real `setTimeout(0)`, and
// that drain is the last step of every `findBy*` and `waitFor` - so with the
// timeout faked it never fires and the wait never settles, even for an element
// that is already on screen. `waitFor` has a second problem: it decides how to
// poll by asking `jestFakeTimersAreEnabled()`, which needs a `jest` global; under
// Vitest there is none, so it always answers `false` and takes its "real timers"
// path - a MutationObserver plus a 50ms re-poll on `setInterval` that only ever
// fires from `tick`, and since #580 a 1000ms timeout that is itself faked and so
// can no longer report a failure, only hang. Vitest's own `vi.waitFor` is worse:
// it re-arms its poll on `setTimeout`, which the fake now owns, so it never
// polls at all.
//
// THE RULE: the flow helpers' `findBy*` run BEFORE the fake is installed, which
// is why the four #580 tests reach the handoff first and fake the clock after.
// The fake goes on only while the resume is still outstanding, so no leave is
// already sitting on the real clock when it does - one armed before the switch
// would outlive the fake and fire against real time. Once it is installed, use
// synchronous queries, `flush()` to settle the session-resume seam, and
// `tick(ms)` to move the clock. Both #563 failures were that exact mistake.

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
import { HANDOFF_MINIMUM_DWELL_MS } from "@/lib/auth/useHandoffNavigation";

// A span long enough to outlast any delay this screen could impose. The
// negative assertions below advance past it to prove a clock decides nothing
// here - ten seconds, twice what the handoff used to hold anyone for. #581
// deleted that duration along with the countdown it drove, so it is stated here
// in milliseconds rather than imported from the component.
const PAST_ANY_HANDOFF_DELAY_MS = 10_000;

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

// #580: the handoff's leave is scheduled with a `setTimeout` (the shared
// navigation hook's minimum dwell), so the fake owns that as well as the
// `setInterval` that drives this file's cooldowns - a `setInterval`-only fake
// would leave the leave unmovable and the tests below would read as "never
// navigates".
//
// Install it ONLY once the flow is on screen and the session resume is still
// outstanding, i.e. before the handoff has armed anything: see the file header
// for why every RTL wait in this file hangs while it is installed. #563: what a
// faked clock costs, and the rule it forces on every test that installs it, is
// in there too.
function fakeHandoffClock() {
  vi.useFakeTimers({
    toFake: ["setInterval", "clearInterval", "setTimeout", "clearTimeout"],
  });
}

/**
 * Drain the microtask queue and commit the state it released, without moving
 * the clock - "the session-resume seam has settled, and nothing has left yet".
 *
 * #580: separate from `tick` because act settles the seam (and so the hook
 * arms its leave timer) only after `advanceTimersByTimeAsync` has already run,
 * so one `tick` cannot both settle the seam and fire what settling armed.
 */
async function flush() {
  await act(async () => {});
}

/**
 * Run the faked clock forward by `ms`, flushing interval and timeout callbacks.
 *
 * #563: `tick(0)` is also a flush - it drains the microtask queue inside `act`
 * without moving the clock, which is what lets the post-resume leave run. See
 * the file header for why a wait cannot be relied on here instead.
 */
async function tick(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

/**
 * Drive the flow to the handoff with the session-resume seam held open, and
 * return the release for it.
 *
 * #580: the handoff's own loading state is only observable if the resume is
 * held, so all four tests below need one, and need it before the verify click -
 * the seam starts on the commit that lands the done stage. Holding it also
 * leaves the handoff with nothing scheduled, which is what makes installing the
 * clock fake afterwards race-free.
 */
async function startOtpFlowWithHeldResume(): Promise<() => void> {
  await startOtpFlow();
  vi.mocked(verifyOtp).mockResolvedValue(verifiedResult());
  vi.mocked(issueSession).mockResolvedValue(SESSION);
  let release: () => void = () => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  state.resumeSession.mockReturnValue(gate);
  mockReplace.mockClear();
  typeOtp();
  fireEvent.click(verifyButton());
  return release;
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

  it("keeps the handoff up while the session resumes, then leaves once (#580)", async () => {
    const release = await startOtpFlowWithHeldResume();
    const hrefBefore = window.location.href;

    // #580: the handoff IS the loading surface, so the resume runs behind it
    // and its progress line carries no countdown digits. Read synchronously -
    // the resume is deliberately still outstanding here. This is the
    // blank-flash regression guard #566 and #563 left in this place.
    expect(await screen.findByText("Identity verified")).toBeInTheDocument();
    expect(
      screen.getByText("Your number is verified and your session is ready."),
    ).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Opening your dashboard",
    );
    // #581: there is no second, digit-bearing line to be absent any more. The
    // progress output carries no digits at all, and the indicator is
    // indeterminate - the whole guarantee in one assertion.
    expect(screen.getByRole("status").textContent).not.toMatch(/\d/);
    expect(screen.getByRole("progressbar")).not.toHaveAttribute(
      "aria-valuenow",
    );
    expect(
      screen.getByRole("button", { name: "Go to Dashboard" }),
    ).toBeInTheDocument();
    // #581 AC-6, this flow's half: the handoff brings its own h1, and it is
    // the only one on the page while it is up. Counted, not just found by name,
    // so a leftover page heading cannot pass unnoticed.
    expect(
      screen.getByRole("heading", { level: 1, name: "Identity verified" }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);

    fakeHandoffClock();
    try {
      // Settled, but not gone: a destination that is ready almost at once still
      // gets the shared hook's readable beat, so the route is NOT pushed at
      // this instant. This is the criterion that keeps the dwell from being
      // optimised away later.
      release();
      await flush();
      expect(
        mockReplace,
        "must not route before the minimum dwell has elapsed",
      ).not.toHaveBeenCalled();

      await tick(HANDOFF_MINIMUM_DWELL_MS);
      expect(mockReplace).toHaveBeenCalledWith("/patient");
      expect(mockReplace).toHaveBeenCalledTimes(1);

      // One leave, ever - and through the framework router, never by replacing
      // the document.
      await tick(PAST_ANY_HANDOFF_DELAY_MS);
      expect(mockReplace).toHaveBeenCalledTimes(1);
      expect(
        window.location.href,
        "must leave with the framework router, not a document navigation",
      ).toBe(hrefBefore);
    } finally {
      vi.useRealTimers();
    }
  });

  it("leaves when the resume settles, never because time passed (#580)", async () => {
    const release = await startOtpFlowWithHeldResume();

    expect(await screen.findByText("Identity verified")).toBeInTheDocument();
    expect(state.resumeSession).toHaveBeenCalled();

    fakeHandoffClock();
    try {
      // Twice the hold this screen used to impose, and the handoff is still
      // there with no digits and no navigation: elapsed time is not what
      // releases it.
      await tick(PAST_ANY_HANDOFF_DELAY_MS);
      expect(screen.getByRole("status")).toHaveTextContent(
        "Opening your dashboard",
      );
      // Still the same line, still digit-free, however long the clock runs.
      expect(screen.getByRole("status").textContent).not.toMatch(/\d/);
      expect(
        mockReplace,
        "must not route while the resume is outstanding",
      ).not.toHaveBeenCalled();

      // The dwell is measured from readiness, not from mount, so a slow resume
      // is not also made to wait out a hold afterwards - the route lands a dwell
      // after the commit that released the readiness, rather than the five
      // seconds after it the old countdown would have cost.
      release();
      await flush();
      expect(
        mockReplace,
        "must not route before the minimum dwell has elapsed",
      ).not.toHaveBeenCalled();
      await tick(HANDOFF_MINIMUM_DWELL_MS);
      expect(mockReplace).toHaveBeenCalledTimes(1);
      expect(mockReplace).toHaveBeenCalledWith("/patient");
    } finally {
      vi.useRealTimers();
    }
  });

  it("honours a mid-load CTA press once the session is ready, exactly once (#580)", async () => {
    const release = await startOtpFlowWithHeldResume();

    expect(await screen.findByText("Identity verified")).toBeInTheDocument();

    // Pressed mid-load, while there is nothing to leave to: the ask has to be
    // remembered rather than obeyed, so it cannot navigate an identity-less
    // surface.
    fireEvent.click(screen.getByRole("button", { name: "Go to Dashboard" }));

    fakeHandoffClock();
    try {
      await flush();
      await tick(HANDOFF_MINIMUM_DWELL_MS * 2);
      expect(
        mockReplace,
        "must not route before the session is resumed",
      ).not.toHaveBeenCalled();

      // The ask is not lost either: readiness is the only thing it was ever
      // waiting on, and once it lands the ask drops the dwell entirely.
      release();
      await flush();
      expect(
        mockReplace,
        "a go-now ask is remembered, not obeyed, on readiness",
      ).not.toHaveBeenCalled();
      await tick(1);
      expect(mockReplace).toHaveBeenCalledTimes(1);
      expect(mockReplace).toHaveBeenCalledWith("/patient");

      // A second press must not leave a second time, and the countdown this
      // screen used to hold is given its full old duration to try.
      fireEvent.click(screen.getByRole("button", { name: "Go to Dashboard" }));
      await flush();
      await tick(PAST_ANY_HANDOFF_DELAY_MS);
      expect(mockReplace).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("awaits the session-resume seam before routing to the return target (#496)", async () => {
    // The seam must settle BEFORE the post-login route mounts, so the patient
    // surface never renders identity-less (and never remounts mid-flow).
    const release = await startOtpFlowWithHeldResume();

    expect(await screen.findByText("Identity verified")).toBeInTheDocument();
    expect(state.resumeSession).toHaveBeenCalled();
    expect(
      mockReplace,
      "must not route before the seam settles",
    ).not.toHaveBeenCalled();

    fakeHandoffClock();
    try {
      release();
      await flush();
      // Settled: the shared hook owns the leave now (#580), and its minimum
      // dwell has not elapsed yet, so the route still has not fired.
      expect(
        mockReplace,
        "must not route before the minimum dwell has elapsed",
      ).not.toHaveBeenCalled();
      await tick(HANDOFF_MINIMUM_DWELL_MS);
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
    // #580: called with no argument the prop is undefined, so the fallback
    // case exercises the wizard's own default rather than restating it.
    async function completeFlowWithReturnTo(returnTo?: string) {
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
      await waitFor(() =>
        expect(mockReplace).toHaveBeenCalledWith(returnTo ?? "/patient"),
      );
    }

    it("redirects to the returnTo prop after the Done step", async () => {
      await completeFlowWithReturnTo("/patient/record");
    });

    it("falls back to /patient when no returnTo is given", async () => {
      await completeFlowWithReturnTo();
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
