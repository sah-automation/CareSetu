// #584 (PHASE-5 T7 / FEAT-014): the partner OTP flow's persistence ORDERING, at
// the module boundary.
//
// The reported defect's first half: the flow published its minted session into
// state and persisted it much later, after a network round trip to the identity
// read. The in-flow identity-resume seam reads the PERSISTED session the moment
// the state is published, so it used to pick up whatever was in storage before -
// the stale patient session of a dual-registered phone, or nothing at all. The
// doctor console is the only partner landing that routes with the client-side
// router rather than a full reload, so the stale identity rode straight into
// the shell. A hard refresh healed it by replaying validation against storage
// that had by then been corrected.
//
// The patient flow (otpState.ts) already persists before publishing; this suite
// pins the partner flow to the same ordering, and pins it as an ORDER rather
// than as "saveSession was called at some point". The partner API is mocked at
// its module boundary; the session-persistence module is the REAL one, so what
// lands in localStorage and in the presence-hint cookie is what production
// writes.

import { act, renderHook, waitFor } from "@testing-library/react";
import { createElement, useEffect, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LangProvider } from "@/lib/i18n/LangContext";
import { HINT_COOKIE, type StoredSession } from "@/lib/auth/session";
import { usePartnerLoginFlow } from "./partnerLoginState";

// The partner transport, mocked at the module boundary so the flow runs for
// real (its state machine, its attempt budget, its refusals) without HTTP.
const authApi = vi.hoisted(() => ({
  partnerLogin: vi.fn(),
  partnerVerify: vi.fn(),
  issuePartnerSession: vi.fn(),
  fetchDemoOtp: vi.fn(),
}));

vi.mock("@/lib/auth/api", () => ({
  partnerLogin: authApi.partnerLogin,
  partnerVerify: authApi.partnerVerify,
  issuePartnerSession: authApi.issuePartnerSession,
  fetchDemoOtp: authApi.fetchDemoOtp,
}));

// #584: the persistence module, with the REAL saveSession and readSession kept
// behind a spy. Call-through is the point: localStorage and the presence-hint
// cookie are written by the production function, so the storage assertions
// below are about what production writes - and `real`/`read` hand the spies
// those same functions rather than stand-ins for them.
const sessionModule = vi.hoisted(() => ({
  saveSession: vi.fn(),
  real: null as typeof import("@/lib/auth/session").saveSession | null,
  read: null as typeof import("@/lib/auth/session").readSession | null,
}));

vi.mock("@/lib/auth/session", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/auth/session")>();
  sessionModule.real = actual.saveSession;
  sessionModule.read = actual.readSession;
  return { ...actual, saveSession: sessionModule.saveSession };
});

// The factory fills these in before any test runs; this is where the test file
// insists on it, once, rather than asserting at every call site.
function required<T>(value: T | null, what: string): T {
  if (value === null) {
    throw new Error(
      `the @/lib/auth/session mock factory did not supply ${what}`,
    );
  }
  return value;
}

const realSaveSession = required(sessionModule.real, "the real saveSession");
const realReadSession = required(sessionModule.read, "the real readSession");

const PHONE = "+919876543210";
const OTP = "123456";

const MINTED = {
  jwt: "partner.header.signature",
  jti: "jti-partner-1",
  scope: "partner",
  identity_id: 77,
  expires_in_seconds: 900,
  refresh_token: "opaque-partner-refresh",
};

// The state a dual-registered phone is in when it starts a partner login: a
// patient session already in storage, which is what the resume seam used to
// read back.
const STALE_PATIENT_SESSION: StoredSession = {
  jwt: "stale.patient.signature",
  refresh_token: "stale-patient-refresh",
  jti: "jti-patient-1",
  scope: "patient",
  identity_id: 42,
  phone: PHONE,
};

const SENT = {
  outcome: "sent" as const,
  phone_e164: PHONE,
  challenge_id: 1,
  expires_in_seconds: 300,
  cooldown_remaining_seconds: 60,
  attempts_left: 5,
  lockout_remaining_seconds: null,
};

const VERIFIED = {
  outcome: "verified" as const,
  phone_e164: PHONE,
  identity_id: 77,
  attempts_left: 5,
  lockout_remaining_seconds: null,
};

/**
 * What the flow had published, and what storage held, at the instant the
 * session first became visible to the shell. The second field IS the
 * assertion: the resume seam reads storage the moment state is published, so a
 * session that is in hand but not yet in storage is a session the console
 * mis-resolves.
 */
interface PublishProbe {
  published: typeof MINTED | null;
  storedAtPublish: StoredSession | null;
}

function renderPartnerFlow() {
  const probe: PublishProbe = { published: null, storedAtPublish: null };
  const view = renderHook(
    () => {
      const flow = usePartnerLoginFlow();
      // The probe stands in for StaffLoginForm's resume effect: keyed on the
      // same published session, in the same commit, which is exactly when the
      // resume seam reads storage. `if (probe.published)` guards the re-run so
      // the FIRST observation is the one recorded.
      useEffect(() => {
        if (flow.state.session !== null && probe.published === null) {
          probe.published = flow.state.session;
          probe.storedAtPublish = realReadSession();
        }
      }, [flow.state.session]);
      return flow;
    },
    {
      wrapper: ({ children }: { children: ReactNode }) =>
        // createElement rather than JSX: this suite is a `.ts` flow-state
        // suite (the staffLoginState.test.ts naming precedent), and the only
        // thing the flow needs mounted above it is the language context.
        createElement(LangProvider, null, children),
    },
  );
  return { probe, view };
}

/** Drives the flow the way the card does: request, type the code, verify. */
async function loginThroughTheFlow() {
  const { probe, view } = renderPartnerFlow();
  act(() => {
    view.result.current.submitPhone(PHONE);
  });
  await waitFor(() => expect(view.result.current.state.stage).toBe("otp"));
  // One act per step: `submitOtp` closes over the render's state, so the draft
  // has to have been re-rendered before the verify that reads it runs.
  act(() => {
    view.result.current.setOtpDraft(OTP);
  });
  expect(view.result.current.state.otpDraft).toBe(OTP);
  act(() => {
    view.result.current.submitOtp();
  });
  await waitFor(() => expect(view.result.current.state.session).not.toBeNull());
  return { probe, view };
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  document.cookie = `${HINT_COOKIE}=; Path=/; Max-Age=0`;
  authApi.partnerLogin.mockResolvedValue(SENT);
  authApi.partnerVerify.mockResolvedValue(VERIFIED);
  authApi.issuePartnerSession.mockResolvedValue(MINTED);
  authApi.fetchDemoOtp.mockResolvedValue(null);
  // Delegating to the real writer, not replacing it: the call must produce the
  // production localStorage keys and the presence hint.
  sessionModule.saveSession.mockImplementation(realSaveSession);
});

afterEach(() => {
  localStorage.clear();
  document.cookie = `${HINT_COOKIE}=; Path=/; Max-Age=0`;
});

describe("usePartnerLoginFlow persistence ordering (#584)", () => {
  it("persists the minted partner session before the flow publishes it", async () => {
    // The report's precondition: the browser already holds a patient session,
    // so "the session is in storage" can only be true of the NEW one.
    localStorage.setItem(
      "caresetu.session",
      JSON.stringify(STALE_PATIENT_SESSION),
    );

    const { probe, view } = await loginThroughTheFlow();

    // The flow published the minted session...
    expect(view.result.current.state.session).toEqual(MINTED);
    expect(probe.published).toEqual(MINTED);
    // ...and at that exact instant storage already held the PARTNER session,
    // never the stale patient one. Publishing first and persisting later - the
    // defect - leaves the stale session right here.
    expect(probe.storedAtPublish?.jwt).toBe(MINTED.jwt);
    expect(probe.storedAtPublish?.jwt).not.toBe(STALE_PATIENT_SESSION.jwt);
  });

  it("writes the dual-JWT keys and the presence hint through the real module", async () => {
    const { view } = await loginThroughTheFlow();

    expect(sessionModule.saveSession).toHaveBeenCalledTimes(1);
    expect(sessionModule.saveSession).toHaveBeenCalledWith(MINTED, PHONE);
    expect(
      JSON.parse(localStorage.getItem("caresetu.session") ?? "{}"),
    ).toEqual({
      jwt: MINTED.jwt,
      refresh_token: MINTED.refresh_token,
      jti: MINTED.jti,
      scope: MINTED.scope,
      identity_id: MINTED.identity_id,
      phone: PHONE,
    });
    expect(localStorage.getItem("caresetu.access_jwt")).toBe(MINTED.jwt);
    expect(localStorage.getItem("caresetu.refresh_token")).toBe(
      MINTED.refresh_token,
    );
    // The hint the split-origin edge guard reads (ADR-0005 amendment).
    expect(document.cookie).toContain(`${HINT_COOKIE}=1`);
  });

  it("persists nothing at all while the code is unverified", async () => {
    const { view } = renderPartnerFlow();
    act(() => {
      view.result.current.submitPhone(PHONE);
    });
    await waitFor(() => expect(view.result.current.state.stage).toBe("otp"));

    // A challenge is not a login: no session, so no storage, and no hint.
    expect(sessionModule.saveSession).not.toHaveBeenCalled();
    expect(localStorage.getItem("caresetu.session")).toBeNull();
    expect(document.cookie).not.toContain(`${HINT_COOKIE}=1`);
  });
});
