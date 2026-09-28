// PHASE-2.6 T10 (#201): the /staff/login surface - composition distinct from
// the patient wizard, registration CTAs, and the authenticated-visitor
// routing through the §4.5 matrix (single role -> home; multi-role ->
// scoped picker; no staff role -> stays on the form).

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import StaffLoginPage from "./page";
import { useAuth } from "@/lib/auth/AuthContext";
import { STRINGS } from "@/lib/i18n/dictionaries";

const mockReplace = vi.fn();
let searchParamsValue = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace }),
  useSearchParams: () => searchParamsValue,
}));

vi.mock("@/lib/auth/AuthContext", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/auth/AuthContext")>();
  return { ...mod, useAuth: vi.fn() };
});

const mockFetchPartnerMe = vi.fn();
vi.mock("@/lib/partner/api", () => ({
  fetchPartnerMe: (...args: unknown[]) => mockFetchPartnerMe(...args),
}));

// #573: the code step and the handoff each bring a top-level heading of their
// own, and "exactly one per stage" can only be asserted on stages the page can
// actually be driven to. That means the partner flow's auth seam, which until
// now this suite left real because no test here needed to submit anything.
// Spread and override rather than replace, so `postLoginTarget` and the page's
// own routing keep the real implementation they resolve destinations through.
const mockFetchMe = vi.fn();
const mockFetchDemoOtp = vi.fn();
const mockIssuePartnerSession = vi.fn();
const mockPartnerLogin = vi.fn();
const mockPartnerVerify = vi.fn();
vi.mock("@/lib/auth/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/auth/api")>();
  return {
    ...mod,
    fetchMe: (...args: unknown[]) => mockFetchMe(...args),
    fetchDemoOtp: (...args: unknown[]) => mockFetchDemoOtp(...args),
    issuePartnerSession: (...args: unknown[]) =>
      mockIssuePartnerSession(...args),
    partnerLogin: (...args: unknown[]) => mockPartnerLogin(...args),
    partnerVerify: (...args: unknown[]) => mockPartnerVerify(...args),
  };
});

const en = STRINGS.en.staffAuth.login;
const PHONE_E164 = "+919876543210";

// #573: the same mock for every session this file stages. Its implementation is
// installed in the `beforeEach` below rather than here, because a reset cannot
// leave an implementation behind - see #562.
const mockResumeSession = vi.fn();

function mockSession(roles: string[] | null) {
  vi.mocked(useAuth).mockReturnValue({
    user: roles === null ? null : { id: 1, phone: "+911234567890", roles },
    selectedRole: null,
    switchRole: vi.fn(),
    logout: vi.fn(),
    isAuthenticated: roles !== null,
    isLoading: false,
    resumeSession: mockResumeSession,
  });
}

// #573: `useAuth` is mocked here as a `vi.fn` with a return value rather than a
// factory, so `resetAllMocks` below wipes it along with everything else - which
// is the point. The defaults are re-installed per test instead, so no mock
// implementation can be quietly omitted by a test that assumed the previous
// one's leaked (the #562 rule, and why the sibling form suite resets).
beforeEach(() => {
  // Every test starts on a signed-out visitor - the phone stage. A test that
  // needs a session says so.
  mockSession(null);
  // The handoff awaits the session before it will route, so this has to return a
  // promise even where nothing routes. A bare `vi.fn()` returning undefined
  // crashes the form's resume effect, and React unmounts the tree with it -
  // which would empty the container every heading count here is read off.
  mockResumeSession.mockResolvedValue(undefined);
  // Default an already-active partner so non-state tests route by role alone.
  mockFetchPartnerMe.mockResolvedValue({
    partner_id: 1,
    partner_type: "doctor",
    round: 1,
    status: "Active",
  });
});

afterEach(() => {
  cleanup();
  searchParamsValue = new URLSearchParams();
  vi.resetAllMocks();
  vi.unstubAllGlobals();
});

describe("StaffLoginPage", () => {
  it("renders the staff sign-in card for a signed-out visitor", () => {
    render(<StaffLoginPage />);
    expect(screen.getByTestId("staff-login-form")).toBeInTheDocument();
    expect(screen.getByText(/Staff sign-in/)).toBeInTheDocument();
    expect(mockReplace).not.toHaveBeenCalled();
  });

  it("renders the partner phone-OTP form by default - no email, password, or operator fields", () => {
    render(<StaffLoginPage />);
    expect(screen.getByTestId("partner-phone")).toBeInTheDocument();
    expect(screen.queryByTestId("staff-email")).not.toBeInTheDocument();
    expect(screen.queryByTestId("staff-password")).not.toBeInTheDocument();
    expect(screen.queryByTestId("staff-phone")).not.toBeInTheDocument();
    expect(screen.queryByTestId("staff-totp")).not.toBeInTheDocument();
  });

  it("renders the operator form when role=operator is passed", () => {
    searchParamsValue = new URLSearchParams({ role: "operator" });
    render(<StaffLoginPage />);
    expect(screen.getByTestId("staff-phone")).toBeInTheDocument();
    expect(screen.getByTestId("staff-totp")).toBeInTheDocument();
    expect(screen.queryByTestId("staff-email")).not.toBeInTheDocument();
    expect(screen.queryByTestId("staff-password")).not.toBeInTheDocument();
  });

  it("falls back to partner mode for an unknown role param", () => {
    searchParamsValue = new URLSearchParams({ role: "doctor" });
    render(<StaffLoginPage />);
    expect(screen.getByTestId("partner-phone")).toBeInTheDocument();
    expect(screen.queryByTestId("staff-email")).not.toBeInTheDocument();
    expect(screen.queryByTestId("staff-phone")).not.toBeInTheDocument();
  });

  it("links the type-preset registration CTAs to the wizard route", () => {
    render(<StaffLoginPage />);
    expect(screen.getByTestId("register-doctor")).toHaveAttribute(
      "href",
      "/staff/register?type=doctor",
    );
    expect(screen.getByTestId("register-lab")).toHaveAttribute(
      "href",
      "/staff/register?type=lab",
    );
    expect(screen.getByTestId("register-chemist")).toHaveAttribute(
      "href",
      "/staff/register?type=chemist",
    );
  });

  it("keeps the interim choose-role entry reachable", () => {
    render(<StaffLoginPage />);
    expect(screen.getByTestId("choose-role-link")).toHaveAttribute(
      "href",
      "/choose-role",
    );
  });

  it("routes an already-signed-in single-staff-role session to its home", async () => {
    mockSession(["operator"]);
    render(<StaffLoginPage />);
    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith("/operator"));
  });

  it("routes a multi-staff-role session to the scoped picker", async () => {
    mockSession(["doctor", "partner"]);
    searchParamsValue = new URLSearchParams({ return: "/staff/roles" });
    render(<StaffLoginPage />);
    await waitFor(() =>
      expect(mockReplace).toHaveBeenCalledWith("/staff/roles"),
    );
  });

  it("does not bounce a patient-only session off the form", () => {
    mockSession(["patient"]);
    render(<StaffLoginPage />);
    expect(mockReplace).not.toHaveBeenCalled();
    expect(screen.getByTestId("staff-login-form")).toBeInTheDocument();
  });

  it("honors a return deep link into the owned territory", async () => {
    mockSession(["doctor"]);
    searchParamsValue = new URLSearchParams({ return: "/doctor/cases/9" });
    render(<StaffLoginPage />);
    await waitFor(() =>
      expect(mockReplace).toHaveBeenCalledWith("/doctor/cases/9"),
    );
  });

  it.each([
    ["Registered", "/partner/status/pending"],
    ["Under Verification", "/partner/status/pending"],
    ["Rejected", "/partner/status/rejected"],
  ] as const)(
    "routes an already-signed-in %s partner to its status screen",
    async (status, expected) => {
      mockFetchPartnerMe.mockResolvedValue({
        partner_id: 1,
        partner_type: "doctor",
        round: 1,
        status,
      });
      mockSession(["partner"]);
      render(<StaffLoginPage />);
      await waitFor(() => expect(mockReplace).toHaveBeenCalledWith(expected));
      expect(mockFetchPartnerMe).toHaveBeenCalled();
    },
  );

  it.each([
    ["doctor", "/doctor"],
    ["lab", "/partner"],
    ["chemist", "/partner"],
  ] as const)(
    "routes an already-signed-in active %s partner to %s",
    async (partnerType, expected) => {
      mockFetchPartnerMe.mockResolvedValue({
        partner_id: 1,
        partner_type: partnerType,
        round: 1,
        status: "Active",
      });
      mockSession(["partner"]);
      render(<StaffLoginPage />);
      await waitFor(() => expect(mockReplace).toHaveBeenCalledWith(expected));
    },
  );

  it("routes an already-signed-in active doctor partner into a doctor deep link", async () => {
    mockFetchPartnerMe.mockResolvedValue({
      partner_id: 1,
      partner_type: "doctor",
      round: 1,
      status: "Active",
    });
    mockSession(["partner"]);
    searchParamsValue = new URLSearchParams({ return: "/doctor/cases/42" });
    render(<StaffLoginPage />);
    await waitFor(() =>
      expect(mockReplace).toHaveBeenCalledWith("/doctor/cases/42"),
    );
  });

  it("routes an already-signed-in active partner to the return deep link (F014-T09b)", async () => {
    mockFetchPartnerMe.mockResolvedValue({
      partner_id: 1,
      partner_type: "doctor",
      round: 1,
      status: "Active",
    });
    mockSession(["partner"]);
    searchParamsValue = new URLSearchParams({ return: "/partner/orders/42" });
    render(<StaffLoginPage />);
    await waitFor(() =>
      expect(mockReplace).toHaveBeenCalledWith("/partner/orders/42"),
    );
  });

  it("lets a partner-state override win over a stale return target", async () => {
    mockFetchPartnerMe.mockResolvedValue({
      partner_id: 1,
      partner_type: "doctor",
      round: 1,
      status: "Rejected",
    });
    mockSession(["partner", "operator"]);
    searchParamsValue = new URLSearchParams({ return: "/operator" });
    render(<StaffLoginPage />);
    await waitFor(() =>
      expect(mockReplace).toHaveBeenCalledWith("/partner/status/rejected"),
    );
  });

  it("falls back to role-based routing when the partner status read fails", async () => {
    mockFetchPartnerMe.mockRejectedValue(new TypeError("Failed to fetch"));
    mockSession(["partner"]);
    render(<StaffLoginPage />);
    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith("/partner"));
  });

  it("does not read partner status for a non-partner staff session", async () => {
    mockSession(["doctor"]);
    render(<StaffLoginPage />);
    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith("/doctor"));
    expect(mockFetchPartnerMe).not.toHaveBeenCalled();
  });
});

// #573: the document structure of the sign-in card. The page owns the "Sign in"
// heading, and two of the three stages inside it own one of their own - the code
// step and the handoff - so the page's has to stand down for those. The
// criterion is the COUNT on every stage, not the absence of a name: "the page
// heading is gone" is equally satisfied by deleting the phone step's heading
// outright, which is the mistake this is written to catch.
//
// The step's own heading and its axe scan live in `StaffLoginForm.test.tsx`,
// which renders the form bare and therefore cannot see this page's chrome.
// The split is deliberate, not halves of one assertion.
describe("StaffLoginPage - one top-level heading per stage (#573)", () => {
  // The two stages the page has to be driven to, since neither is reachable
  // from a signed-out first render. Each mounts the page itself and hands back
  // its container, so no test ends up with two pages mounted and a count to
  // misread.
  async function reachOtpStage() {
    mockPartnerLogin.mockResolvedValue({
      outcome: "sent",
      phone_e164: PHONE_E164,
      challenge_id: 21,
      expires_in_seconds: 300,
      cooldown_remaining_seconds: 0,
      attempts_left: 5,
      lockout_remaining_seconds: null,
    });
    const { container } = render(<StaffLoginPage />);
    fireEvent.change(screen.getByTestId("partner-phone"), {
      target: { value: "9876543210" },
    });
    fireEvent.click(screen.getByTestId("staff-submit"));
    await screen.findByTestId("partner-otp");
    return container;
  }

  async function reachDoneStage() {
    // The practice-facts read the handoff makes is deliberately unmocked, and
    // left alone it reaches a real socket. The handoff mounts on the STAGE, so
    // the heading under test is up long before the destination resolves; failing
    // the read fast is the whole of what the stub is for.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("no network in unit tests")),
    );
    const container = await reachOtpStage();
    mockPartnerVerify.mockResolvedValue({
      outcome: "verified",
      phone_e164: PHONE_E164,
      identity_id: 7,
      attempts_left: null,
      lockout_remaining_seconds: null,
    });
    mockIssuePartnerSession.mockResolvedValue({
      jwt: "header.payload.signature",
      jti: "jti-1",
      scope: "partner",
      identity_id: 7,
      expires_in_seconds: 900,
      refresh_token: "opaque-refresh-token",
    });
    mockFetchMe.mockResolvedValue({
      subject_id: "7",
      roles: ["partner"],
      phone: PHONE_E164,
    });
    fireEvent.change(screen.getByTestId("partner-otp"), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByTestId("staff-submit"));
    await screen.findByRole("heading", { level: 1, name: en.verifiedTitle });
    return container;
  }

  // Counted off the container rather than off `screen`, so the assertion is
  // about the document this page rendered and not about whatever else a suite
  // has left mounted.
  const h1Count = (container: HTMLElement) =>
    container.querySelectorAll("h1").length;

  it("keeps the page heading as the only top-level heading on the phone stage", () => {
    const { container } = render(<StaffLoginPage />);
    expect(h1Count(container)).toBe(1);
    expect(
      screen.getByRole("heading", { level: 1, name: en.heading }),
    ).toBeInTheDocument();
  });

  it("counts one top-level heading on the code stage, the step's own (#573 AC-1/AC-2)", async () => {
    const container = await reachOtpStage();
    // The suppression is a lifted signal, so the page retires its heading one
    // effect pass after the step renders its own. Flush that pass deliberately
    // and assert the settled document, rather than polling for a count that
    // would also read 1 on a page that had simply deleted its heading.
    await act(async () => {});
    expect(h1Count(container)).toBe(1);
    // The step took over from the page, rather than joining it.
    expect(
      screen.getByRole("heading", { level: 1, name: en.codeStepTitle }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { level: 1, name: en.heading }),
    ).not.toBeInTheDocument();
  });

  it("counts one top-level heading on the done stage, the handoff's own (#573 AC-2)", async () => {
    const container = await reachDoneStage();
    await act(async () => {});
    expect(h1Count(container)).toBe(1);
    expect(
      screen.getByRole("heading", { level: 1, name: en.verifiedTitle }),
    ).toBeInTheDocument();
  });

  it("leaves the operator branch's heading arrangement exactly as it was (#573 AC-5)", () => {
    searchParamsValue = new URLSearchParams({ role: "operator" });
    const { container } = render(<StaffLoginPage />);
    // The operator form never reaches the partner stages, so the page keeps its
    // heading and gains none. The suppression is a partner condition.
    expect(h1Count(container)).toBe(1);
    expect(
      screen.getByRole("heading", { level: 1, name: en.heading }),
    ).toBeInTheDocument();
  });
});
