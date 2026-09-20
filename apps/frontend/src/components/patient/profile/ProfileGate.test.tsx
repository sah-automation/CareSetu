// PHASE-2.6 T13 (#204): component suite for the inline gating presentation.
// Covers the ticket's acceptance criteria: browse actions never gated;
// intake/booking gated on basics; medicine-delivery checkout gated on
// area; the gate presents the exact missing step inline.
//
// PHASE-8.1 T2 (#488): the ProfileProvider behind the gate is exercised with
// the profile client mocked - so hydration short-circuits a saved profile's
// gates and an inline Finish persists through PUT /v1/me/profile with optional
// fields unsettable (#488 AC 1/2/4).

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProfileGate, ProfileGateDemo } from "./ProfileGate";
import { ProfileProvider } from "@/lib/profile/ProfileContext";
import type { StoredPatientProfile } from "@/lib/profile/api";
import { loadDraft } from "@/lib/profile/profileState";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { __resetLangForTests } from "@/lib/i18n/LangContext";

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

const en = STRINGS.en.profile;
const savedProfile: StoredPatientProfile = {
  name: "Asha Devi",
  age: 30,
  gender: "female",
  preferred_language: "en",
  area: "Bishrampur",
  emergency_contact: "+91 98765 43210",
  photo_ref: "me.jpg",
};

beforeEach(() => {
  window.localStorage.clear();
  __resetLangForTests();
  state.getProfile.mockReset();
  state.saveProfile.mockReset();
  state.getProfile.mockResolvedValue({ set: false, profile: null });
  state.saveProfile.mockResolvedValue(savedProfile);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function type(testId: string, value: string) {
  fireEvent.change(screen.getByTestId(testId), { target: { value } });
}

function select(testId: string, value: string) {
  fireEvent.change(screen.getByTestId(testId), { target: { value } });
}

function renderGate(ui: React.ReactNode) {
  return render(<ProfileProvider>{ui}</ProfileProvider>);
}

interface HostProps {
  action: "findCare" | "intake" | "booking" | "medicineCheckout";
}

function Host({ action }: HostProps) {
  return (
    <ProfileGate action={action}>
      <span data-testid="action-btn">Action</span>
    </ProfileGate>
  );
}

describe("ProfileGate", () => {
  it("never gates findCare - renders children directly", () => {
    renderGate(<Host action="findCare" />);
    expect(screen.getByTestId("action-btn")).toBeInTheDocument();
    expect(
      screen.queryByTestId("gate-wizard-findCare"),
    ).not.toBeInTheDocument();
  });

  it("never gates viewRecord - renders children directly", () => {
    const HostView = () => (
      <ProfileGate action="viewRecord">
        <button data-testid="action-btn">Action</button>
      </ProfileGate>
    );
    renderGate(<HostView />);
    expect(screen.getByTestId("action-btn")).toBeInTheDocument();
  });

  it("gates intake on basics and opens wizard on step 1", () => {
    renderGate(<Host action="intake" />);

    // Click the trigger button
    fireEvent.click(screen.getByTestId("gate-trigger-intake"));

    // Wizard should open on step 1 (About you)
    expect(screen.getByTestId("gate-wizard-intake")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: en.s1 })).toBeInTheDocument();
  });

  it("gates booking on basics and opens wizard on step 1", () => {
    renderGate(<Host action="booking" />);

    fireEvent.click(screen.getByTestId("gate-trigger-booking"));

    expect(screen.getByTestId("gate-wizard-booking")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: en.s1 })).toBeInTheDocument();
  });

  it("gates medicineCheckout on area and opens wizard on step 3", () => {
    renderGate(<Host action="medicineCheckout" />);

    fireEvent.click(screen.getByTestId("gate-trigger-medicineCheckout"));

    expect(
      screen.getByTestId("gate-wizard-medicineCheckout"),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: en.s3 })).toBeInTheDocument();
  });

  it("shows gate explanation text", () => {
    renderGate(<Host action="intake" />);

    fireEvent.click(screen.getByTestId("gate-trigger-intake"));

    expect(screen.getByText(en.gate.basicsExplain)).toBeInTheDocument();
  });

  it("shows area gate explanation for medicineCheckout", () => {
    renderGate(<Host action="medicineCheckout" />);

    fireEvent.click(screen.getByTestId("gate-trigger-medicineCheckout"));

    expect(screen.getByText(en.gate.areaExplain)).toBeInTheDocument();
  });

  it("lets user complete basics in inline wizard and closes", async () => {
    renderGate(<Host action="intake" />);

    fireEvent.click(screen.getByTestId("gate-trigger-intake"));

    // Wizard opens on step 1 - verify it renders with all step 1 fields
    expect(screen.getByTestId("gate-wizard-intake")).toBeInTheDocument();
    expect(screen.getByTestId("pc-fullname")).toBeInTheDocument();
    expect(screen.getByTestId("pc-age")).toBeInTheDocument();
    expect(screen.getByTestId("pc-gender")).toBeInTheDocument();
    expect(screen.getByTestId("pc-next")).toBeInTheDocument();

    // Fill basics and advance
    type("pc-fullname", "Asha Devi");
    type("pc-age", "30");
    select("pc-gender", "female");

    fireEvent.click(screen.getByTestId("pc-next"));

    // Should advance to step 2
    expect(screen.getByRole("heading", { name: en.s2 })).toBeInTheDocument();
    expect(screen.getByTestId("pc-skip")).toBeInTheDocument();

    // Skip to step 3
    fireEvent.click(screen.getByTestId("pc-skip"));
    expect(screen.getByRole("heading", { name: en.s3 })).toBeInTheDocument();

    // Finish persists through the profile client, then the wizard closes
    fireEvent.click(screen.getByTestId("pc-next"));

    expect(state.saveProfile).toHaveBeenCalledTimes(1);
    await waitFor(() =>
      expect(
        screen.queryByTestId("gate-wizard-intake"),
      ).not.toBeInTheDocument(),
    );
  });

  it("persists the draft to the identity-scoped local buffer while editing", () => {
    renderGate(<Host action="intake" />);

    fireEvent.click(screen.getByTestId("gate-trigger-intake"));
    type("pc-fullname", "Asha Devi");
    type("pc-age", "30");
    select("pc-gender", "female");

    expect(loadDraft(7).name).toBe("Asha Devi");
    // No cross-identity leakage: the legacy global key stays untouched.
    const draft = loadDraft();
    expect(draft.name).toBe("");
  });

  it("persists FINISH through PUT /v1/me/profile with optional fields unsettable", async () => {
    renderGate(<Host action="intake" />);
    fireEvent.click(screen.getByTestId("gate-trigger-intake"));

    type("pc-fullname", "Asha Devi");
    type("pc-age", "30");
    select("pc-gender", "female");
    fireEvent.click(screen.getByTestId("pc-next"));
    fireEvent.click(screen.getByTestId("pc-skip"));
    type("pc-area", " Bishrampur ");
    fireEvent.click(screen.getByTestId("pc-next"));

    await waitFor(() =>
      expect(state.saveProfile).toHaveBeenCalledWith({
        name: "Asha Devi",
        age: 30,
        gender: "female",
        preferred_language: "en",
        area: "Bishrampur",
        emergency_contact: null,
        photo_ref: null,
      }),
    );
  });

  it("short-circuits the gate when a saved profile hydrates (#488 AC 2)", async () => {
    state.getProfile.mockResolvedValue({ set: true, profile: savedProfile });
    renderGate(<Host action="intake" />);

    await waitFor(() =>
      expect(screen.getByTestId("action-btn")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("gate-trigger-intake")).not.toBeInTheDocument();
  });

  it("shows the bilingual save error inline when the write fails", async () => {
    state.saveProfile.mockRejectedValue(new Error("network down"));
    renderGate(<Host action="intake" />);
    fireEvent.click(screen.getByTestId("gate-trigger-intake"));

    type("pc-fullname", "Asha Devi");
    type("pc-age", "30");
    select("pc-gender", "female");
    fireEvent.click(screen.getByTestId("pc-next"));
    fireEvent.click(screen.getByTestId("pc-skip"));
    fireEvent.click(screen.getByTestId("pc-next"));

    await waitFor(() =>
      expect(screen.getByTestId("profile-save-error")).toBeInTheDocument(),
    );
    expect(screen.getByText(en.save.error)).toBeInTheDocument();
    // The wizard stays open so the patient can retry.
    expect(screen.getByTestId("gate-wizard-intake")).toBeInTheDocument();
  });

  // #496 Seam 1: the medicine-delivery gate opens the wizard directly on step
  // 3, so Finish is reachable with incomplete basics - the second silent-return
  // branch. It must refuse with the visible save error, never silently.
  it("surfaces the visible save error when Finish runs with incomplete basics (#496)", async () => {
    renderGate(<Host action="medicineCheckout" />);
    fireEvent.click(screen.getByTestId("gate-trigger-medicineCheckout"));

    // Opens directly on the area step; the patient can hit Finish untouched.
    expect(
      screen.getByTestId("gate-wizard-medicineCheckout"),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: en.s3 })).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("pc-next"));

    await waitFor(() =>
      expect(screen.getByTestId("profile-save-error")).toBeInTheDocument(),
    );
    expect(screen.getByText(en.save.error)).toBeInTheDocument();
    expect(state.saveProfile).not.toHaveBeenCalled();
    // The wizard stays open so the patient can fix what is missing.
    expect(
      screen.getByTestId("gate-wizard-medicineCheckout"),
    ).toBeInTheDocument();
  });
});

describe("ProfileGateDemo", () => {
  it("renders three demo gates for intake, booking, checkout", () => {
    renderGate(<ProfileGateDemo />);

    expect(screen.getByText(en.demo.intake)).toBeInTheDocument();
    expect(screen.getByText(en.demo.booking)).toBeInTheDocument();
    expect(screen.getByText(en.demo.checkout)).toBeInTheDocument();
  });
});
