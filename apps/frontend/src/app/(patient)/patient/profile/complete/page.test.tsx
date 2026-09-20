// PHASE-8.1 T2 (#488): the dedicated first-login profile-completion route.
// Hydrates the editable draft from GET /v1/me/profile, persists Finish through
// PUT /v1/me/profile, and routes back to the dashboard only when the write
// succeeded (#488 AC 1). A failed write keeps the patient on the page with the
// bilingual save error visible so they can retry.

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ProfileCompletionPage from "./page";
import { ProfileProvider } from "@/lib/profile/ProfileContext";
import type { StoredPatientProfile } from "@/lib/profile/api";
import { __resetLangForTests } from "@/lib/i18n/LangContext";
import { STRINGS } from "@/lib/i18n/dictionaries";

const state = vi.hoisted(() => ({
  getProfile: vi.fn(),
  saveProfile: vi.fn(),
  push: vi.fn(),
  refresh: vi.fn(),
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

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: state.push,
    refresh: state.refresh,
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

const savedProfile: StoredPatientProfile = {
  name: "Asha Devi",
  age: 30,
  gender: "female",
  preferred_language: "en",
  area: "Bishrampur",
  emergency_contact: "+91 98765 43210",
  photo_ref: "me.jpg",
};

function type(testId: string, value: string) {
  fireEvent.change(screen.getByTestId(testId), { target: { value } });
}

function select(testId: string, value: string) {
  fireEvent.change(screen.getByTestId(testId), { target: { value } });
}

beforeEach(() => {
  window.localStorage.clear();
  __resetLangForTests();
  state.getProfile.mockReset();
  state.saveProfile.mockReset();
  state.push.mockReset();
  state.refresh.mockReset();
  state.getProfile.mockResolvedValue({ set: false, profile: null });
  state.saveProfile.mockResolvedValue(savedProfile);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("profile complete page (#488)", () => {
  it("hydrates the editable draft from a saved profile", async () => {
    state.getProfile.mockResolvedValue({ set: true, profile: savedProfile });
    render(
      <ProfileProvider>
        <ProfileCompletionPage />
      </ProfileProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("pc-fullname")).toHaveValue("Asha Devi"),
    );
    expect(screen.getByTestId("pc-age")).toHaveValue("30");
  });

  it("persists Finish then routes back to the dashboard with a fresh page", async () => {
    render(
      <ProfileProvider>
        <ProfileCompletionPage />
      </ProfileProvider>,
    );

    type("pc-fullname", "Asha Devi");
    type("pc-age", "30");
    select("pc-gender", "female");
    fireEvent.click(screen.getByTestId("pc-next"));
    fireEvent.click(screen.getByTestId("pc-skip"));
    type("pc-area", "Bishrampur");
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
    await waitFor(() => expect(state.push).toHaveBeenCalledWith("/patient"));
    expect(state.refresh).toHaveBeenCalled();
  });

  it("stays on the page with the bilingual save error when the write fails", async () => {
    state.saveProfile.mockRejectedValue(new Error("network down"));
    render(
      <ProfileProvider>
        <ProfileCompletionPage />
      </ProfileProvider>,
    );

    type("pc-fullname", "Asha Devi");
    type("pc-age", "30");
    select("pc-gender", "female");
    fireEvent.click(screen.getByTestId("pc-next"));
    fireEvent.click(screen.getByTestId("pc-skip"));
    fireEvent.click(screen.getByTestId("pc-next"));

    await waitFor(() =>
      expect(screen.getByTestId("profile-save-error")).toBeInTheDocument(),
    );
    expect(screen.getByText(STRINGS.en.profile.save.error)).toBeInTheDocument();
    expect(state.push).not.toHaveBeenCalled();
  });
});
