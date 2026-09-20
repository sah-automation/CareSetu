// PHASE-8.1 T2 (#488): patient dashboard hydration. A returning patient whose
// profile was completed on another device sees their saved profile reflected in
// the meter and nudge cards - a fresh empty browser would show the whole
// reminder stack, so a single tracking reminder proves the server hydrate won
// over an empty local buffer (#488 AC 1/2).

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PatientDashboardPage from "./page";
import { ProfileProvider } from "@/lib/profile/ProfileContext";
import type { StoredPatientProfile } from "@/lib/profile/api";
import { initialDraft, saveDraft } from "@/lib/profile/profileState";
import { __resetLangForTests } from "@/lib/i18n/LangContext";
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

describe("patient dashboard profile hydration (#488)", () => {
  it("reflects the saved server profile across the meter and nudge cards", async () => {
    state.getProfile.mockResolvedValue({ set: true, profile: completeProfile });
    render(
      <ProfileProvider>
        <PatientDashboardPage />
      </ProfileProvider>,
    );

    // The full server profile means only the tracking reminder remains - a
    // fresh empty browser would show the whole missing-group stack.
    await waitFor(() =>
      expect(screen.getAllByTestId("pc-nudge-card")).toHaveLength(1),
    );
    expect(
      screen.getByText(STRINGS.en.profile.nudges.trackingTitle),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(STRINGS.en.profile.nudges.areaTitle),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(STRINGS.en.profile.nudges.basicsTitle),
    ).not.toBeInTheDocument();
    // Meter carries the saved completeness, not an empty draft's.
    expect(screen.getByTestId("pc-meter-label")).not.toHaveTextContent("0%");
  });

  it("a fully filled local draft (same device) surfaces no nudge reminders", async () => {
    state.getProfile.mockResolvedValue({ set: false, profile: null });
    saveDraft(
      {
        ...initialDraft(),
        name: "Asha Devi",
        age: "30",
        gender: "female",
        language: "en",
        area: "Bishrampur",
        emergencyContact: "+91 98765 43210",
        photoFileName: "me.jpg",
        trackBp: true,
        trackSugar: true,
      },
      state.user.id,
    );
    render(
      <ProfileProvider>
        <PatientDashboardPage />
      </ProfileProvider>,
    );

    await waitFor(() =>
      expect(screen.queryByTestId("pc-nudge-stack")).not.toBeInTheDocument(),
    );
  });
});
