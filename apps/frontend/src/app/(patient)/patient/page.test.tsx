// PHASE-2.7 T1 (#499): the reworked patient home shell (PROTO-2.7 binding).
// A returning patient lands on a full-width greeting strip that names the saved
// first name in the current language, with a generic fallback when no name is
// saved, above the responsive feed. The profile completion meter, nudge stack
// and demo scaffolds no longer render on the home.
//
// #500: the slim one-line profile-completeness banner joins the same composed
// seam under the greeting strip - present when name/age/gender are missing and
// not dismissed, absent when basics are complete or the per-device dismissal
// flag is set.

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PatientDashboardPage from "./page";
import { ProfileProvider } from "@/lib/profile/ProfileContext";
import type { StoredPatientProfile } from "@/lib/profile/api";
import { __resetLangForTests, useLang } from "@/lib/i18n/LangContext";
import { STRINGS } from "@/lib/i18n/dictionaries";

const state = vi.hoisted(() => ({
  getProfile: vi.fn(),
  saveProfile: vi.fn(),
  user: { id: 7, phone: "+91 98765 43210", roles: ["patient"] },
}));

vi.mock("@/lib/profile/api", () => ({
  getProfile: state.getProfile,
  saveProfile: state.saveProfile,
}));

vi.mock("@/lib/auth/AuthContext", () => ({
  useAuth: () => ({
    user: state.user,
    selectedRole: null,
    switchRole: vi.fn(),
    logout: vi.fn(),
    isAuthenticated: true,
    isLoading: false,
  }),
}));

const completeProfile: StoredPatientProfile = {
  name: "Asha Devi",
  age: 30,
  gender: "female",
  preferred_language: "en",
  area: "Bishrampur",
  emergency_contact: "+91 98765 43210",
  photo_ref: "me.jpg",
};

function langFlip() {
  // Provider-less suites subscribe to the shared module store directly; this
  // button is the one-mutation-path way to flip locale mid-test.
  const { lang, setLang } = useLang();
  return (
    <button type="button" onClick={() => setLang(lang === "en" ? "hi" : "en")}>
      flip-lang
    </button>
  );
}

function renderHome() {
  return render(
    <ProfileProvider>
      <LangFlipHost />
    </ProfileProvider>,
  );
}

function LangFlipHost() {
  return (
    <>
      {langFlip()}
      <PatientDashboardPage />
    </>
  );
}

beforeEach(() => {
  window.localStorage.clear();
  __resetLangForTests();
  state.getProfile.mockReset();
  state.saveProfile.mockReset();
  state.getProfile.mockResolvedValue({ set: false, profile: null });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("patient home shell (#499)", () => {
  it("greets the saved first name in the current language", async () => {
    state.getProfile.mockResolvedValue({ set: true, profile: completeProfile });
    renderHome();

    const greeting = await screen.findByTestId("patient-home-greeting");
    await waitFor(() =>
      expect(greeting).toHaveTextContent(
        STRINGS.en.patientHome.welcome("Asha"),
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: "flip-lang" }));
    await waitFor(() =>
      expect(greeting).toHaveTextContent(
        STRINGS.hi.patientHome.welcome("Asha"),
      ),
    );
  });

  it("falls back to the generic greeting when no name is saved", async () => {
    state.getProfile.mockResolvedValue({ set: false, profile: null });
    renderHome();

    const greeting = await screen.findByTestId("patient-home-greeting");
    await waitFor(() =>
      expect(greeting).toHaveTextContent(STRINGS.en.patientHome.welcomeGuest),
    );
    expect(greeting).not.toHaveTextContent(
      STRINGS.en.patientHome.welcome("Asha"),
    );
  });

  it("no longer composes the meter, nudge stack or demo scaffolds", async () => {
    state.getProfile.mockResolvedValue({ set: true, profile: completeProfile });
    renderHome();

    await screen.findByTestId("patient-home-greeting");
    expect(screen.queryByTestId("pc-meter-label")).not.toBeInTheDocument();
    expect(screen.queryByTestId("pc-nudge-stack")).not.toBeInTheDocument();
    expect(screen.queryByTestId("profile-gate-demo")).not.toBeInTheDocument();
    expect(screen.queryByTestId("consent-demo-card")).not.toBeInTheDocument();
  });

  it("renders the greeting strip above the feed with an empty rail", async () => {
    renderHome();

    const greeting = await screen.findByTestId("patient-home-greeting");
    expect(screen.getByTestId("patient-home-rail")).toBeInTheDocument();
    expect(
      greeting.compareDocumentPosition(screen.getByTestId("patient-home-rail")),
    ).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });
});

describe("profile completeness banner (#500)", () => {
  it("renders when basics are incomplete and not dismissed", async () => {
    state.getProfile.mockResolvedValue({ set: false, profile: null });
    renderHome();

    const banner = await screen.findByTestId("pc-banner");
    expect(banner).toHaveTextContent(STRINGS.en.patientHome.banner);
    expect(banner).toHaveTextContent(STRINGS.en.patientHome.bannerCta);
    expect(
      screen.getByRole("button", {
        name: STRINGS.en.patientHome.bannerDismiss,
      }),
    ).toBeInTheDocument();
    // The slim banner is a separate element from the (removed) nudge stack.
    expect(screen.queryByTestId("pc-nudge-stack")).not.toBeInTheDocument();
  });

  it("renders nothing when basics are complete (testid absent, not hidden)", async () => {
    state.getProfile.mockResolvedValue({ set: true, profile: completeProfile });
    renderHome();

    await screen.findByTestId("patient-home-greeting");
    await waitFor(() =>
      expect(screen.queryByTestId("pc-banner")).not.toBeInTheDocument(),
    );
  });

  it("dismisses per device and stays gone on a later visit", async () => {
    state.getProfile.mockResolvedValue({ set: false, profile: null });
    renderHome();
    await screen.findByTestId("pc-banner");

    fireEvent.click(screen.getByTestId("pc-banner-dismiss"));
    await waitFor(() =>
      expect(screen.queryByTestId("pc-banner")).not.toBeInTheDocument(),
    );
    expect(
      window.localStorage.getItem("caresetu.profileBanner.dismissed"),
    ).toBe("1");

    // A fresh render (later visit) still honors the durable dismissal.
    cleanup();
    renderHome();
    await screen.findByTestId("patient-home-greeting");
    await waitFor(() =>
      expect(screen.queryByTestId("pc-banner")).not.toBeInTheDocument(),
    );
  });

  it("serves the banner copy in hi from the same patientHome surface", async () => {
    state.getProfile.mockResolvedValue({ set: false, profile: null });
    renderHome();
    await screen.findByTestId("pc-banner");

    fireEvent.click(screen.getByRole("button", { name: "flip-lang" }));
    await waitFor(() =>
      expect(screen.getByTestId("pc-banner")).toHaveTextContent(
        STRINGS.hi.patientHome.banner,
      ),
    );
  });
});
