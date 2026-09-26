// #522/#523: the patient Profile route (blueprint §5.8). The completion meter
// reflects draft completeness; personal details, language preference, emergency
// contact, and area pre-fill from the saved server profile and any
// identity-keyed in-progress draft. Save reuses the provider's idempotent
// finishProfile with the basics gate - incomplete basics block the write with a
// plain explanation, never a partial record - and success/error surface through
// the bilingual save-status notice plus an axe scan (spec #520 seams 1/2).
//
// #548: the page is now three zones (Identity / Health background / Settings).
// The save flow and its payload are unchanged - only the presentation moved -
// and the Identity zone gained the photo control, whose ref the provider
// adopts so a later save cannot detach an uploaded photo.

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import * as axe from "axe-core";
import {
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import ProfileSettingsPage from "./page";
import { ApiError } from "@/lib/api-errors";
import { __resetLangForTests } from "@/lib/i18n/LangContext";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { ProfileProvider } from "@/lib/profile/ProfileContext";
import type { StoredPatientProfile } from "@/lib/profile/api";
import {
  deletePatientPhoto,
  fetchPatientPhoto,
  uploadPatientPhoto,
} from "@/lib/profile/api";
import { fetchConsentLog, revokeConsent } from "@/lib/consent/api";
import {
  appendHealthMetric,
  fetchHealthBackground,
  fetchHealthMetrics,
  saveHealthBackground,
} from "@/lib/health-background/api";
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

vi.mock("@/lib/profile/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/profile/api")>();
  return {
    ...mod,
    getProfile: state.getProfile,
    saveProfile: state.saveProfile,
    uploadPatientPhoto: vi.fn(),
    fetchPatientPhoto: vi.fn(),
    deletePatientPhoto: vi.fn(),
  };
});

vi.mock("@/lib/consent/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/consent/api")>();
  return { ...mod, fetchConsentLog: vi.fn(), revokeConsent: vi.fn() };
});

// #549: the Health background zone reads the owner's health-background
// endpoints on mount, so the page suite stands in for them. The defaults are
// the zero-setup answers (no snapshot yet, no measurements) - this suite is
// about the page around the zone, and the zone's own behaviour is covered in
// HealthBackgroundZone.test.tsx.
vi.mock("@/lib/health-background/api", async (importOriginal) => {
  const mod =
    await importOriginal<typeof import("@/lib/health-background/api")>();
  return {
    ...mod,
    fetchHealthBackground: vi.fn(),
    saveHealthBackground: vi.fn(),
    fetchHealthMetrics: vi.fn(),
    appendHealthMetric: vi.fn(),
  };
});

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

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

beforeAll(() => {
  window.ResizeObserver =
    window.ResizeObserver ??
    (ResizeObserverStub as unknown as typeof ResizeObserver);
  if (!window.PointerEvent) {
    class PointerEventStub extends MouseEvent {}
    window.PointerEvent = PointerEventStub as unknown as typeof PointerEvent;
  }
});

const mockUploadPhoto = vi.mocked(uploadPatientPhoto);
const mockFetchPhoto = vi.mocked(fetchPatientPhoto);
const mockDeletePhoto = vi.mocked(deletePatientPhoto);
const mockFetchConsentLog = vi.mocked(fetchConsentLog);
const mockRevokeConsent = vi.mocked(revokeConsent);
const mockFetchHealthBackground = vi.mocked(fetchHealthBackground);
const mockSaveHealthBackground = vi.mocked(saveHealthBackground);
const mockFetchHealthMetrics = vi.mocked(fetchHealthMetrics);
const mockAppendHealthMetric = vi.mocked(appendHealthMetric);

const savedProfile: StoredPatientProfile = {
  name: "Asha Devi",
  age: 30,
  gender: "female",
  preferred_language: "en",
  area: "Bishrampur",
  emergency_contact: "+91 98765 43210",
  photo_ref: "patient/7/photo-1.enc",
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
  mockUploadPhoto.mockReset();
  mockFetchPhoto.mockReset();
  mockDeletePhoto.mockReset();
  mockFetchPhoto.mockResolvedValue(new Blob(["photo"], { type: "image/png" }));
  mockFetchConsentLog.mockReset();
  mockFetchConsentLog.mockResolvedValue({ items: [] });
  mockRevokeConsent.mockReset();
  mockFetchHealthBackground.mockReset();
  mockSaveHealthBackground.mockReset();
  mockFetchHealthMetrics.mockReset();
  mockAppendHealthMetric.mockReset();
  mockFetchHealthBackground.mockResolvedValue({
    set: false,
    acknowledged: false,
    background: null,
  });
  mockFetchHealthMetrics.mockResolvedValue({ items: [], total: 0 });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Profile & Settings page (#522/#523)", () => {
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
    // Language, emergency contact, and area sections pre-fill too.
    expect(screen.getByTestId("ps-lang")).toHaveValue("en");
    expect(screen.getByTestId("ps-area")).toHaveValue("Bishrampur");
    expect(screen.getByTestId("ps-ec")).toHaveValue("+91 98765 43210");
    // name + age + gender + area + emergency = 5/5 on the page-scoped meter
    // (photo and chronic-interest tracking are not collectable here, #527).
    expect(screen.getByTestId("pc-meter")).toHaveAttribute(
      "aria-valuenow",
      "100",
    );
    expect(screen.getByTestId("ps-meter-label")).toHaveTextContent("100%");
    expect(screen.queryByTestId("ps-save-blocked")).not.toBeInTheDocument();
  });

  it("pre-fills a saved Hindi language preference into the section", async () => {
    state.getProfile.mockResolvedValue({
      set: true,
      profile: { ...savedProfile, preferred_language: "hi" },
    });
    render(
      <ProfileProvider>
        <ProfileSettingsPage />
      </ProfileProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("ps-lang")).toHaveValue("hi"),
    );
  });

  it("pre-fills from an in-progress draft buffer when no saved profile exists", async () => {
    saveDraft(
      draftFixture({
        name: "Meera Singh",
        age: "42",
        gender: "other",
        area: "Bishrampur",
        emergencyContact: "+91 11111 22222",
      }),
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
    expect(screen.getByTestId("ps-lang")).toHaveValue("en");
    expect(screen.getByTestId("ps-area")).toHaveValue("Bishrampur");
    expect(screen.getByTestId("ps-ec")).toHaveValue("+91 11111 22222");
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

  it("still blocks the save with incomplete basics even when extra fields are filled", async () => {
    saveDraft(
      draftFixture({ area: "Bishrampur", emergencyContact: "+91 11111 22222" }),
      7,
    );
    render(
      <ProfileProvider>
        <ProfileSettingsPage />
      </ProfileProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("ps-area")).toHaveValue("Bishrampur"),
    );
    fireEvent.click(screen.getByTestId("ps-save"));

    expect(screen.getByTestId("ps-save-blocked")).toHaveTextContent(
      STRINGS.en.profile.settings.blocked,
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

  it("saves language, emergency contact, and area edits through the finish path", async () => {
    saveDraft(
      draftFixture({
        name: "Meera Singh",
        age: "42",
        gender: "other",
        area: "Patan",
        emergencyContact: "+91 11111 22222",
      }),
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
    // Choosing Hindi flips the live app locale at once - the app speaks the
    // chosen language (#520 story 24) - while draft.language records the
    // profile field for the save payload.
    fireEvent.change(screen.getByTestId("ps-lang"), {
      target: { value: "hi" },
    });
    expect(screen.getByTestId("ps-save")).toHaveTextContent(
      STRINGS.hi.profile.settings.save,
    );
    type("ps-area", "Bishrampur");
    type("ps-ec", "+91 99999 88888");
    fireEvent.click(screen.getByTestId("ps-save"));

    await waitFor(() =>
      expect(state.saveProfile).toHaveBeenCalledWith({
        name: "Meera Singh",
        age: 42,
        gender: "other",
        preferred_language: "hi",
        area: "Bishrampur",
        emergency_contact: "+91 99999 88888",
        photo_ref: null,
      }),
    );
    // The notice lands in the language just chosen.
    await waitFor(() =>
      expect(
        screen.getByText(STRINGS.hi.profile.save.saved),
      ).toBeInTheDocument(),
    );
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

  it("ships the language, emergency contact, and area section labels in both locales", () => {
    // #523's sections reuse the wizard's keys rather than duplicating them
    // (spec #520 i18n decision) - every key this page renders must resolve in
    // the active locale, whichever one is chosen.
    const labels = [
      STRINGS.en.profile.langLabel,
      STRINGS.en.profile.ec,
      STRINGS.en.profile.ecPlaceholder,
      STRINGS.en.profile.area,
      STRINGS.en.profile.areaPlaceholder,
    ];
    for (const label of labels) {
      expect(label).toBeTruthy();
    }
    expect(STRINGS.hi.profile.langLabel).toBeTruthy();
    expect(STRINGS.hi.profile.ecPlaceholder).toBeTruthy();
    expect(STRINGS.hi.profile.areaPlaceholder).toBeTruthy();
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

// #548 AC 1: the page is three zones, and the reorganization is presentational
// - the fields and the save flow are the ones #522/#523 shipped.
describe("Profile page zones (#548)", () => {
  async function renderReady() {
    state.getProfile.mockResolvedValue({ set: true, profile: savedProfile });
    render(
      <ProfileProvider>
        <ProfileSettingsPage />
      </ProfileProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("ps-fullname")).toHaveValue("Asha Devi"),
    );
  }

  it("presents Identity, Health background, and Settings as three named zones", async () => {
    await renderReady();

    const z = STRINGS.en.profileZones;
    expect(screen.getByTestId("ps-zone-identity")).toHaveTextContent(
      z.identityHeading,
    );
    expect(screen.getByTestId("ps-zone-health")).toHaveTextContent(
      z.healthHeading,
    );
    expect(screen.getByTestId("ps-zone-settings")).toHaveTextContent(
      z.settingsHeading,
    );

    // Each zone is a labelled landmark, so a screen reader can jump between
    // them rather than reading one undifferentiated form.
    for (const id of [
      "ps-zone-identity",
      "ps-zone-health",
      "ps-zone-settings",
    ]) {
      const zone = screen.getByTestId(id);
      const labelledBy = zone.getAttribute("aria-labelledby");
      expect(labelledBy).toBeTruthy();
      expect(document.getElementById(labelledBy ?? "")?.tagName).toBe("H2");
    }
  });

  it("keeps every existing profile field in the Identity zone", async () => {
    await renderReady();

    const identity = screen.getByTestId("ps-zone-identity");
    for (const testId of [
      "ps-fullname",
      "ps-age",
      "ps-gender",
      "ps-lang",
      "ps-ec",
      "ps-area",
      "ps-save",
    ]) {
      expect(identity.querySelector(`[data-testid="${testId}"]`)).toBeTruthy();
    }
  });

  it("hosts the health background zone's real surface, not a placeholder", async () => {
    await renderReady();

    // #549 filled the zone: the snapshot form and the series are here, and the
    // zone is a real labelled landmark rather than a "coming later" note.
    const health = screen.getByTestId("ps-zone-health");
    expect(
      health.querySelector('[data-testid="ps-hb-snapshot-form"]'),
    ).toBeTruthy();
    expect(health.querySelector('[data-testid="ps-hb-metrics"]')).toBeTruthy();
    expect(health).toHaveTextContent(STRINGS.en.profileZones.healthSub);
  });

  it("shows the default language in Settings without a second bound control", async () => {
    await renderReady();

    // The value is summarised, not re-editable: two bound controls for one
    // profile field would drift apart, and the editable one lives in Identity.
    expect(screen.getByTestId("ps-settings-language-value")).toHaveTextContent(
      "English",
    );
    expect(
      screen.getByTestId("ps-zone-settings").querySelector("#ps-lang"),
    ).toBeNull();
  });

  it("scans clean on axe with all three zones rendered", async () => {
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
});

// #548 AC 2: the photo control is wired to the photo endpoint and rendered
// from the stored key; remove clears it.
describe("Profile page photo (#548)", () => {
  it("previews the stored photo rather than showing the opaque ref", async () => {
    state.getProfile.mockResolvedValue({ set: true, profile: savedProfile });
    render(
      <ProfileProvider>
        <ProfileSettingsPage />
      </ProfileProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("ps-photo-remove")).toBeInTheDocument(),
    );
    expect(mockFetchPhoto).toHaveBeenCalled();
    expect(screen.getByTestId("ps-photo")).toBeInTheDocument();
  });

  it("uploads a picked photo and keeps it attached to the next save", async () => {
    // The stored ref moves, then the patient saves their name edit: the save
    // must carry the NEW ref, or it would detach the photo they just uploaded.
    mockUploadPhoto.mockResolvedValue({
      ...savedProfile,
      photo_ref: "patient/7/photo-2.enc",
    });
    state.getProfile.mockResolvedValue({ set: true, profile: savedProfile });
    render(
      <ProfileProvider>
        <ProfileSettingsPage />
      </ProfileProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("ps-photo-remove")).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByTestId("ps-photo-input"), {
      target: {
        files: [new File(["photo"], "me.png", { type: "image/png" })],
      },
    });
    await waitFor(() => expect(mockUploadPhoto).toHaveBeenCalled());

    fireEvent.click(screen.getByTestId("ps-save"));

    await waitFor(() =>
      expect(state.saveProfile).toHaveBeenCalledWith(
        expect.objectContaining({ photo_ref: "patient/7/photo-2.enc" }),
      ),
    );
  });

  it("removes the photo and the next save carries no ref", async () => {
    mockDeletePhoto.mockResolvedValue({ ...savedProfile, photo_ref: null });
    state.getProfile.mockResolvedValue({ set: true, profile: savedProfile });
    render(
      <ProfileProvider>
        <ProfileSettingsPage />
      </ProfileProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("ps-photo-remove")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("ps-photo-remove"));

    await waitFor(() => expect(mockDeletePhoto).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.queryByTestId("ps-photo-remove")).not.toBeInTheDocument(),
    );

    fireEvent.click(screen.getByTestId("ps-save"));
    await waitFor(() =>
      expect(state.saveProfile).toHaveBeenCalledWith(
        expect.objectContaining({ photo_ref: null }),
      ),
    );
  });

  it("leaves the stored photo in place when an upload is rejected", async () => {
    mockUploadPhoto.mockRejectedValue(
      new ApiError({
        code: "PROFILE_PHOTO_INVALID",
        message: "unsupported media type",
        trace_id: "trace-page-548",
        details: {},
      }),
    );
    state.getProfile.mockResolvedValue({ set: true, profile: savedProfile });
    render(
      <ProfileProvider>
        <ProfileSettingsPage />
      </ProfileProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("ps-photo-remove")).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByTestId("ps-photo-input"), {
      target: {
        files: [new File(["photo"], "me.gif", { type: "image/gif" })],
      },
    });

    await waitFor(() =>
      expect(screen.getByTestId("ps-photo-failed")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("ps-photo-remove")).toBeInTheDocument();
  });
});

// #548 AC 3: Settings carries consent management, and the export/delete leads
// are marked rather than left as buttons that would do nothing.
describe("Profile page settings (#548)", () => {
  async function renderReady() {
    state.getProfile.mockResolvedValue({ set: true, profile: savedProfile });
    render(
      <ProfileProvider>
        <ProfileSettingsPage />
      </ProfileProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("ps-fullname")).toHaveValue("Asha Devi"),
    );
  }

  it("surfaces the patient's consent grants inside the Settings zone", async () => {
    mockFetchConsentLog.mockResolvedValue({
      items: [
        {
          consent_id: 4,
          lineage_ref: "C-2026-004",
          patient_id: 7,
          counterparty_type: "doctor",
          counterparty_id: "dr-kumar",
          record_scope: "health_background",
          status: "granted",
          version: 1,
          created_at: "2026-09-01T10:00:00Z",
          updated_at: "2026-09-01T10:05:00Z",
          events: [],
        },
      ],
    });
    await renderReady();

    await waitFor(() =>
      expect(screen.getByTestId("ps-consent-4")).toBeInTheDocument(),
    );
    expect(
      screen
        .getByTestId("ps-zone-settings")
        .querySelector('[data-testid="ps-consent-4"]'),
    ).toBeTruthy();
  });

  it("revokes a health_background grant from Settings", async () => {
    const grant = {
      consent_id: 4,
      lineage_ref: "C-2026-004",
      patient_id: 7,
      counterparty_type: "doctor",
      counterparty_id: "dr-kumar",
      record_scope: "health_background",
      status: "granted",
      version: 1,
      created_at: "2026-09-01T10:00:00Z",
      updated_at: "2026-09-01T10:05:00Z",
      events: [],
    };
    mockFetchConsentLog.mockResolvedValue({ items: [grant] });
    mockRevokeConsent.mockResolvedValue({ ...grant, status: "revoked" });
    await renderReady();

    await waitFor(() =>
      expect(screen.getByTestId("ps-consent-revoke-4")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("ps-consent-revoke-4"));
    fireEvent.click(await screen.findByTestId("ps-consent-confirm"));

    await waitFor(() => expect(mockRevokeConsent).toHaveBeenCalledWith(4));
    await waitFor(() =>
      expect(screen.queryByTestId("ps-consent-4")).toBeNull(),
    );
  });

  it("marks the notification preferences coming soon instead of faking them", async () => {
    await renderReady();

    // The patient profile row models no notification preferences, so these
    // rows are inert and say so - a live toggle would read as saved and change
    // nothing.
    const checkbox = screen.getByTestId(
      "ps-notification-appointment_reminders",
    );
    expect(checkbox).toBeDisabled();
    expect(screen.getByTestId("ps-settings-notifications")).toHaveTextContent(
      STRINGS.en.profileZones.notificationsSoon,
    );
  });

  it("marks data export and delete as coming soon leads, not dead buttons", async () => {
    await renderReady();

    for (const testId of ["ps-data-export", "ps-data-delete"]) {
      const row = screen.getByTestId(testId);
      expect(row).toHaveTextContent(STRINGS.en.profileZones.dataSoon);
      // A lead, not a control: nothing here looks tappable and does nothing.
      expect(row.querySelector("button")).toBeNull();
      expect(row.querySelector("a")).toBeNull();
    }
  });

  it("speaks every zone in the chosen locale (EN/HI parity)", async () => {
    await renderReady();

    fireEvent.change(screen.getByTestId("ps-lang"), {
      target: { value: "hi" },
    });

    // The whole page flips, not just the field that was touched - every new
    // string this ticket added resolves in whichever locale is active.
    const hi = STRINGS.hi.profileZones;
    expect(screen.getByTestId("ps-zone-identity")).toHaveTextContent(
      hi.identityHeading,
    );
    expect(screen.getByTestId("ps-zone-health")).toHaveTextContent(
      hi.healthHeading,
    );
    expect(screen.getByTestId("ps-zone-settings")).toHaveTextContent(
      hi.settingsHeading,
    );
    expect(screen.getByTestId("ps-settings-language-value")).toHaveTextContent(
      "हिंदी",
    );
    expect(screen.getByTestId("ps-zone-identity")).toHaveTextContent(
      hi.photoReplace,
    );
    expect(screen.getByTestId("ps-health-pending")).toHaveTextContent(
      hi.healthPending,
    );
    // #549: the health background zone's own copy flips with the rest of the
    // page, not just the zone heading.
    expect(screen.getByTestId("ps-hb-zone")).toHaveTextContent(
      hi.bloodGroupLabel,
    );
    expect(screen.getByTestId("ps-hb-snapshot-save")).toHaveTextContent(
      hi.snapshotSave,
    );
    expect(screen.getByTestId("ps-hb-metric-add")).toHaveTextContent(
      hi.metricAdd,
    );
    expect(screen.getByTestId("ps-data-export")).toHaveTextContent(hi.dataSoon);
  });
});
