// PHASE-8.1 T2 (#488): provider suite for patient profile hydration +
// persistence. The profile client is mocked at the module boundary, so these
// tests pin the ordering the ticket demands: hydrate from GET /v1/me/profile
// before local-draft fallback, a saved profile short-circuits the completion
// gate, Finish persists through PUT with optional fields unsettable, and two
// identities on one browser never share a draft view.

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProfileProvider, useProfile } from "./ProfileContext";
import type { ProfileReadResult, StoredPatientProfile } from "./api";
import { initialDraft, saveDraft } from "./profileState";
import { ProfileGate } from "@/components/patient/profile/ProfileGate";
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
    isAuthenticated: state.user !== null,
    isLoading: false,
  }),
}));

const savedProfile: StoredPatientProfile = {
  name: "Asha Devi",
  age: 30,
  gender: "female",
  preferred_language: "en",
  area: "Bishrampur",
  emergency_contact: null,
  photo_ref: null,
};

function Probe() {
  const {
    hydrated,
    savedProfile: saved,
    draft,
    saveStatus,
    updateDraft,
    finishProfile,
  } = useProfile();
  const basics = {
    name: "Asha Devi",
    age: "30",
    gender: "female",
  } as const;
  return (
    <div>
      <span data-testid="probe-hydrated">{String(hydrated)}</span>
      <span data-testid="probe-saved">{String(saved !== null)}</span>
      <span data-testid="probe-name">{draft.name}</span>
      <span data-testid="probe-status">{saveStatus}</span>
      <button
        data-testid="probe-set-draft"
        onClick={() => updateDraft({ ...draft, ...basics })}
      >
        set
      </button>
      <button
        data-testid="probe-finish"
        onClick={() => {
          void finishProfile();
        }}
      >
        finish
      </button>
    </div>
  );
}

beforeEach(() => {
  window.localStorage.clear();
  __resetLangForTests();
  state.getProfile.mockReset();
  state.saveProfile.mockReset();
  state.user = { id: 7, phone: "+91 98765 43210", roles: ["patient"] };
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

async function renderProvider(ui: React.ReactNode) {
  const view = render(<ProfileProvider>{ui}</ProfileProvider>);
  await waitFor(() =>
    expect(screen.getByTestId("probe-hydrated").textContent).toBe("true"),
  );
  return view;
}

describe("ProfileProvider hydration (#488 AC 2)", () => {
  it("keeps in-progress edits when a slower GET answers set=true", async () => {
    let settle: (value: ProfileReadResult) => void = () => {};
    state.getProfile.mockImplementation(
      () =>
        new Promise<ProfileReadResult>((resolve) => {
          settle = resolve;
        }),
    );
    render(
      <ProfileProvider>
        <div>
          <Probe />
        </div>
      </ProfileProvider>,
    );

    // The patient types before the GET settles; the reference-guard in the
    // provider must not let the server seed clobber their in-progress input.
    fireEvent.click(screen.getByTestId("probe-set-draft"));
    settle({
      set: true,
      profile: { ...savedProfile, name: "Server Name" },
    });

    await waitFor(() =>
      expect(screen.getByTestId("probe-hydrated").textContent).toBe("true"),
    );
    expect(screen.getByTestId("probe-name").textContent).toBe("Asha Devi");
    expect(screen.getByTestId("probe-saved").textContent).toBe("true");
  });

  it("seeds the buffer from a saved profile and short-circuits the gate", async () => {
    state.getProfile.mockResolvedValue({ set: true, profile: savedProfile });
    await renderProvider(
      <div>
        <Probe />
        <ProfileGate action="intake">
          <button data-testid="action-btn">Go</button>
        </ProfileGate>
      </div>,
    );

    expect(screen.getByTestId("probe-saved").textContent).toBe("true");
    expect(screen.getByTestId("probe-name").textContent).toBe("Asha Devi");
    expect(screen.getByTestId("action-btn")).toBeInTheDocument();
    expect(screen.queryByTestId("gate-trigger-intake")).not.toBeInTheDocument();
  });

  it("falls back to the identity-scoped local draft when GET answers not-set", async () => {
    saveDraft({ ...initialDraft(), name: "Local Name" }, state.user.id);
    state.getProfile.mockResolvedValue({ set: false, profile: null });
    await renderProvider(
      <div>
        <Probe />
        <ProfileGate action="intake">
          <button data-testid="action-btn">Go</button>
        </ProfileGate>
      </div>,
    );

    expect(screen.getByTestId("probe-saved").textContent).toBe("false");
    expect(screen.getByTestId("probe-name").textContent).toBe("Local Name");
    // Not saved server-side, so the basics gate still fires.
    expect(screen.getByTestId("gate-trigger-intake")).toBeInTheDocument();
  });

  it("falls back to the local draft when hydration itself fails", async () => {
    saveDraft({ ...initialDraft(), name: "Offline Name" }, state.user.id);
    state.getProfile.mockRejectedValue(new Error("network down"));
    await renderProvider(
      <div>
        <Probe />
      </div>,
    );

    expect(screen.getByTestId("probe-saved").textContent).toBe("false");
    expect(screen.getByTestId("probe-name").textContent).toBe("Offline Name");
  });
});

describe("ProfileProvider persist on Finish (#488 AC 1/4)", () => {
  it("puts the draft with optional fields unsettable and reports saved", async () => {
    state.getProfile.mockResolvedValue({ set: false, profile: null });
    state.saveProfile.mockResolvedValue(savedProfile);
    await renderProvider(
      <div>
        <Probe />
      </div>,
    );

    fireEvent.click(screen.getByTestId("probe-set-draft"));
    fireEvent.click(screen.getByTestId("probe-finish"));

    await waitFor(() =>
      expect(state.saveProfile).toHaveBeenCalledWith({
        name: "Asha Devi",
        age: 30,
        gender: "female",
        preferred_language: "en",
        area: null,
        emergency_contact: null,
        photo_ref: null,
      }),
    );
    await waitFor(() =>
      expect(screen.getByTestId("probe-status").textContent).toBe("saved"),
    );
  });

  it("reports an error when the write fails and never fakes a saved profile", async () => {
    state.getProfile.mockResolvedValue({ set: false, profile: null });
    state.saveProfile.mockRejectedValue(new Error("network down"));
    await renderProvider(
      <div>
        <Probe />
      </div>,
    );

    fireEvent.click(screen.getByTestId("probe-set-draft"));
    fireEvent.click(screen.getByTestId("probe-finish"));

    await waitFor(() =>
      expect(screen.getByTestId("probe-status").textContent).toBe("error"),
    );
    expect(screen.getByTestId("probe-saved").textContent).toBe("false");
  });
});

describe("ProfileProvider identity isolation (#488 AC 5)", () => {
  it("refetches and reseeds the buffer when the identity changes", async () => {
    state.getProfile.mockResolvedValue({ set: false, profile: null });
    const { rerender } = await renderProvider(
      <div>
        <Probe />
      </div>,
    );

    fireEvent.click(screen.getByTestId("probe-set-draft"));
    expect(
      window.localStorage.getItem("caresetu.profile.draft.7"),
    ).not.toBeNull();

    // Second identity on the same browser: no shared draft, fresh refetch.
    state.user = { id: 8, phone: "+91 11111 11111", roles: ["patient"] };
    state.getProfile.mockClear();
    state.getProfile.mockResolvedValue({ set: false, profile: null });

    const tree = (
      <ProfileProvider>
        <div>
          <Probe />
        </div>
      </ProfileProvider>
    );
    rerender(tree);

    await waitFor(() =>
      expect(screen.getByTestId("probe-hydrated").textContent).toBe("true"),
    );
    expect(screen.getByTestId("probe-name").textContent).toBe("");
    expect(state.getProfile).toHaveBeenCalledTimes(1);
    expect(window.localStorage.getItem("caresetu.profile.draft.8")).toBeNull();
  });
});
