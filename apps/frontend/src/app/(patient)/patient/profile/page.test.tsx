// #522: the patient Profile & Settings route (blueprint §5.8). The completion
// meter reflects draft completeness; personal details pre-fill from the saved
// server profile and any identity-keyed in-progress draft. Save reuses the
// provider's idempotent finishProfile with the basics gate - incomplete basics
// block the write with a plain explanation, never a partial record - and
// success/error surface through the bilingual save-status notice plus an axe
// scan (spec #520 seam 2).

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import * as axe from "axe-core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ProfileSettingsPage from "./page";
import { __resetLangForTests } from "@/lib/i18n/LangContext";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { ProfileProvider } from "@/lib/profile/ProfileContext";
import type { StoredPatientProfile } from "@/lib/profile/api";
import {
  initialDraft,
  saveDraft,
  type ProfileDraft,
} from "@/lib/profile/profileState";

const state = vi.hoisted<{
  getProfile: ReturnType<typeof vi.fn>;
  saveProfile: ReturnType<typeof vi.fn>;
  user: { id: number; phone: string; roles: string[] } | null;
}>(() => ({
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

const savedProfile: StoredPatientProfile = {
  name: "Asha Devi",
  age: 30,
  gender: "female",
  preferred_language: "en",
  area: "Bishrampur",
  emergency_contact: "+91 98765 43210",
  photo_ref: "me.jpg",
};

const draftFixture = (overrides: Partial<ProfileDraft>): ProfileDraft => ({
  ...initialDraft(),
  ...overrides,
});

function type(testId: string, value: string) {
  fireEvent.change(screen.getByTestId(testId), { target: { value } });
}

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

describe("Profile & Settings page (#522)", () => {
  it("renders the §5.8 layout with a meter reflecting the saved profile", async () => {
    state.getProfile.mockResolvedValue({ set: true, profile: savedProfile });
    render(
      <ProfileProvider>
        <ProfileSettingsPage />
      </ProfileProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("ps-fullname")).toHaveValue("Asha Devi"),
    );
    expect(screen.getByTestId("ps-age")).toHaveValue("30");
    expect(screen.getByTestId("ps-gender")).toHaveValue("female");
    // name + age + gender + photo + area + emergency = 6/7 filled.
    expect(screen.getByTestId("pc-meter")).toHaveAttribute(
      "aria-valuenow",
      "86",
    );
    expect(screen.getByTestId("ps-meter-label")).toHaveTextContent("86%");
    expect(screen.queryByTestId("ps-save-blocked")).not.toBeInTheDocument();
  });

  it("pre-fills from an in-progress draft buffer when no saved profile exists", async () => {
    saveDraft(
      draftFixture({ name: "Meera Singh", age: "42", gender: "other" }),
      7,
    );
    render(
      <ProfileProvider>
        <ProfileSettingsPage />
      </ProfileProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("ps-fullname")).toHaveValue("Meera Singh"),
    );
    expect(screen.getByTestId("ps-age")).toHaveValue("42");
    expect(screen.getByTestId("ps-gender")).toHaveValue("other");
  });

  it("lets the saved server profile win over the draft buffer", async () => {
    state.getProfile.mockResolvedValue({ set: true, profile: savedProfile });
    saveDraft(
      draftFixture({ name: "Meera Singh", age: "42", gender: "other" }),
      7,
    );
    render(
      <ProfileProvider>
        <ProfileSettingsPage />
      </ProfileProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("ps-fullname")).toHaveValue("Asha Devi"),
    );
    expect(screen.getByTestId("ps-age")).toHaveValue("30");
  });

  it("blocks a save while basics are incomplete with a plain explanation, never writing", async () => {
    render(
      <ProfileProvider>
        <ProfileSettingsPage />
      </ProfileProvider>,
    );

    fireEvent.click(screen.getByTestId("ps-save"));

    expect(screen.getByTestId("ps-save-blocked")).toHaveTextContent(
      STRINGS.en.profile.settings.blocked,
    );
    expect(screen.getByTestId("ps-error-name")).toHaveTextContent(
      STRINGS.en.profile.errors.nameRequired,
    );
    expect(screen.getByTestId("ps-error-age")).toHaveTextContent(
      STRINGS.en.profile.errors.ageRequired,
    );
    expect(screen.getByTestId("ps-error-gender")).toHaveTextContent(
      STRINGS.en.profile.errors.genderRequired,
    );
    expect(state.saveProfile).not.toHaveBeenCalled();
  });

  it("persists complete basics through finishProfile and shows the saved notice", async () => {
    const draft = draftFixture({
      name: "Meera Singh",
      age: "42",
      gender: "other",
    });
    saveDraft(draft, 7);
    render(
      <ProfileProvider>
        <ProfileSettingsPage />
      </ProfileProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("ps-fullname")).toHaveValue("Meera Singh"),
    );
    fireEvent.click(screen.getByTestId("ps-save"));

    await waitFor(() =>
      expect(state.saveProfile).toHaveBeenCalledWith({
        name: "Meera Singh",
        age: 42,
        gender: "other",
        preferred_language: "en",
        area: null,
        emergency_contact: null,
        photo_ref: null,
      }),
    );
    await waitFor(() =>
      expect(
        screen.getByText(STRINGS.en.profile.save.saved),
      ).toBeInTheDocument(),
    );
    expect(screen.getByTestId("profile-save-status")).toBeInTheDocument();
    expect(screen.queryByTestId("ps-save-blocked")).not.toBeInTheDocument();
  });

  it("surfaces the bilingual save error when the write fails", async () => {
    state.saveProfile.mockRejectedValue(new Error("network down"));
    saveDraft(
      draftFixture({ name: "Meera Singh", age: "42", gender: "other" }),
      7,
    );
    render(
      <ProfileProvider>
        <ProfileSettingsPage />
      </ProfileProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("ps-fullname")).toHaveValue("Meera Singh"),
    );
    fireEvent.click(screen.getByTestId("ps-save"));

    await waitFor(() =>
      expect(screen.getByTestId("profile-save-error")).toBeInTheDocument(),
    );
    expect(screen.getByText(STRINGS.en.profile.save.error)).toBeInTheDocument();
  });

  it("ships every new settings string in both locales", () => {
    const enKeys = Object.keys(STRINGS.en.profile.settings) as Array<
      keyof typeof STRINGS.en.profile.settings
    >;
    expect(enKeys.length).toBeGreaterThan(0);
    for (const key of enKeys) {
      expect(STRINGS.hi.profile.settings[key]).toBeTruthy();
    }
  });

  it("scans clean on axe with a completed profile rendered", async () => {
    state.getProfile.mockResolvedValue({ set: true, profile: savedProfile });
    const { container } = render(
      <ProfileProvider>
        <ProfileSettingsPage />
      </ProfileProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("ps-fullname")).toHaveValue("Asha Devi"),
    );
    expect((await axe.run(container)).violations).toEqual([]);
  });

  it("scans clean on axe with the blocked-save explanation rendered", async () => {
    const { container } = render(
      <ProfileProvider>
        <ProfileSettingsPage />
      </ProfileProvider>,
    );

    fireEvent.click(screen.getByTestId("ps-save"));
    await waitFor(() =>
      expect(screen.getByTestId("ps-save-blocked")).toBeInTheDocument(),
    );
    expect((await axe.run(container)).violations).toEqual([]);
  });
});
