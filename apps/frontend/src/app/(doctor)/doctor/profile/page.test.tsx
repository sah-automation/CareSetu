// PHASE-8.1 (#543): doctor console Profile page suite. Renders the private
// profile projection from #542 (photo preview, practice details, experience,
// languages, about, availability, credential/verified status, notification
// toggles), saves the editable fields through the private PUT, runs the
// consultation-fee editor through the unchanged PATCH fee path it inherited
// from the landing, drives photo upload/remove over the profile-media-backed
// endpoints, shows the read-only public-directory preview link, and covers
// load failure with retry plus bilingual EN/HI parity (REQ-006).

import {
  cleanup,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import DoctorProfilePage from "./page";
import { ApiError } from "@/lib/api-errors";
import { DoctorProfileProvider } from "@/lib/doctor/DoctorProfileContext";
import {
  deleteDoctorProfilePhoto,
  fetchDoctorProfile,
  fetchDoctorProfilePhoto,
  updateDoctorProfile,
  uploadDoctorProfilePhoto,
  type DoctorProfileView,
} from "@/lib/doctor/api";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { __resetLangForTests, useLang } from "@/lib/i18n/LangContext";
import { updateConsultationFee } from "@/lib/partner/api";
import { useProfilePhotoSource } from "@/lib/profile/useProfilePhotoSource";

vi.mock("next/link", () => {
  return {
    default: ({
      href,
      children,
      ...rest
    }: {
      href: string;
      children: ReactNode;
    }) => (
      <a href={href} {...rest}>
        {children}
      </a>
    ),
  };
});

vi.mock("@/lib/doctor/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/doctor/api")>();
  return {
    ...mod,
    fetchDoctorProfile: vi.fn(),
    updateDoctorProfile: vi.fn(),
    uploadDoctorProfilePhoto: vi.fn(),
    fetchDoctorProfilePhoto: vi.fn(),
    deleteDoctorProfilePhoto: vi.fn(),
  };
});

vi.mock("@/lib/partner/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/partner/api")>();
  return { ...mod, updateConsultationFee: vi.fn() };
});

// #583: the page no longer reads the projection for itself - the shared doctor
// profile source does, once, and the page renders whatever that source holds.
// The source keys its state on the doctor's identity, so this suite supplies one
// directly: standing up the real AuthProvider would put an async /me between the
// mount and the identity, and with it a remount and a second byte read, neither
// of which belongs to what this suite is about.
vi.mock("@/lib/auth/AuthContext", () => ({
  useAuth: () => ({
    user: { id: 7, phone: "+911234567890", roles: ["partner"] },
    selectedRole: "partner",
    switchRole: vi.fn(),
    logout: vi.fn(),
    isAuthenticated: true,
    isLoading: false,
  }),
}));

const t = STRINGS.en.doctorProfile;
const hiT = STRINGS.hi.doctorProfile;
const getProfile = vi.mocked(fetchDoctorProfile);
const saveProfile = vi.mocked(updateDoctorProfile);
const uploadPhoto = vi.mocked(uploadDoctorProfilePhoto);
const getPhoto = vi.mocked(fetchDoctorProfilePhoto);
const deletePhoto = vi.mocked(deleteDoctorProfilePhoto);
const setFee = vi.mocked(updateConsultationFee);

function profile(
  overrides: Partial<DoctorProfileView> = {},
): DoctorProfileView {
  return {
    partner_id: 7,
    photo_ref: null,
    practice_name: "Sunrise Clinic",
    specialty: "General Physician",
    verified: true,
    practice_address: "Main Road, Daltonganj",
    practice_latitude: 24.1957,
    practice_longitude: 85.3656,
    area: "Daltonganj",
    languages: ["Hindi", "English"],
    experience_years: 12,
    about: "Twelve years of primary care.",
    consultation_fee: 40000,
    availability: "Mon-Sat, 9am-1pm",
    credentials: [
      {
        credential_type: "medical_registration",
        status: "verified",
        expires_at: "2027-04-01T00:00:00Z",
      },
    ],
    notification_preferences: { new_consultations: true },
    ...overrides,
  };
}

// #583: the page is rendered inside the shared doctor profile source, as the
// (doctor) route-group layout does in production. The source owns the read, so
// the only thing the page's own render needs seeded is what the source answers.
async function renderReady(view: DoctorProfileView = profile()) {
  getProfile.mockResolvedValue(view);
  render(
    <DoctorProfileProvider>
      <DoctorProfilePage />
    </DoctorProfileProvider>,
  );
  await waitFor(() => screen.getByTestId("profile-details-form"));
}

let originalCreate: typeof URL.createObjectURL;
let originalRevoke: typeof URL.revokeObjectURL;

// The defaults every test starts from are installed in `beforeEach`, not
// `afterEach`: a save now hands its reply to the shared source, so a test that
// saves has to be holding a real projection to hand over, and a default left to
// the previous test's teardown is one `clearAllMocks` away from being nothing at
// all. Installed here, every test starts from the same known answers.
beforeEach(() => {
  originalCreate = URL.createObjectURL;
  originalRevoke = URL.revokeObjectURL;
  URL.createObjectURL = vi.fn(
    () => "blob:http://localhost/doctor-photo",
  ) as typeof URL.createObjectURL;
  URL.revokeObjectURL = vi.fn() as unknown as typeof URL.revokeObjectURL;
  getProfile.mockResolvedValue(profile());
  saveProfile.mockImplementation(async (update) =>
    profile({
      ...update,
      photo_ref: null,
      specialty: "General Physician",
      verified: true,
      area: "Daltonganj",
      consultation_fee: 40000,
    }),
  );
  uploadPhoto.mockResolvedValue({ photo_ref: "doctor/7/photo-1.enc" });
  getPhoto.mockResolvedValue(new Blob(["photo"], { type: "image/jpeg" }));
  deletePhoto.mockResolvedValue(undefined);
  setFee.mockResolvedValue({ partner_id: 7, status: "Active", round: 0 });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  __resetLangForTests();
  URL.createObjectURL = originalCreate;
  URL.revokeObjectURL = originalRevoke;
});

describe("DoctorProfilePage projection", () => {
  it("renders the private projection and the read-only public preview link", async () => {
    await renderReady();

    expect(screen.getByText(t.title)).toBeInTheDocument();
    expect(screen.getByTestId("profile-practice-name")).toHaveValue(
      "Sunrise Clinic",
    );
    expect(screen.getByTestId("profile-specialty")).toHaveTextContent(
      "General Physician",
    );
    expect(screen.getByTestId("profile-verified")).toHaveTextContent(
      t.verified,
    );
    // The directory's own locality label for the saved address is shown too.
    expect(screen.getByTestId("profile-area")).toHaveTextContent("Daltonganj");
    expect(screen.getByTestId("profile-address")).toHaveValue(
      "Main Road, Daltonganj",
    );
    expect(screen.getByTestId("profile-latitude")).toHaveValue(24.1957);
    expect(screen.getByTestId("profile-longitude")).toHaveValue(85.3656);
    expect(screen.getByTestId("profile-experience")).toHaveValue(12);
    expect(screen.getByTestId("profile-languages")).toHaveValue(
      "Hindi, English",
    );
    expect(screen.getByTestId("profile-about")).toHaveValue(
      "Twelve years of primary care.",
    );
    expect(screen.getByTestId("profile-availability")).toHaveValue(
      "Mon-Sat, 9am-1pm",
    );
    expect(
      screen.getByTestId("profile-notification-new_consultations"),
    ).toBeChecked();
    expect(
      screen.getByTestId("profile-notification-case_updates"),
    ).not.toBeChecked();
    expect(screen.getByTestId("profile-credential-status")).toHaveTextContent(
      t.credentialStatus.verified,
    );

    // The public directory entry is a read-only preview, never an editor here.
    const preview = screen.getByTestId("profile-public-preview");
    expect(preview).toHaveAttribute("href", "/providers/7");
    expect(preview).toHaveTextContent(t.publicPreviewAction);
  });

  it("shows the credential status vocabulary per credential", async () => {
    await renderReady(
      profile({
        credentials: [
          {
            credential_type: "medical_registration",
            status: "expired",
            expires_at: null,
          },
          {
            credential_type: "qualification_certificate",
            status: "reverification_failed",
            expires_at: null,
          },
        ],
      }),
    );

    const statuses = screen.getAllByTestId("profile-credential-status");
    expect(statuses).toHaveLength(2);
    expect(statuses[0]).toHaveTextContent(t.credentialStatus.expired);
    expect(statuses[1]).toHaveTextContent(
      t.credentialStatus.reverification_failed,
    );
    expect(screen.queryByTestId("profile-credential-expiry")).toBeNull();
  });

  it("labels the credential kinds instead of showing the raw API literal", async () => {
    await renderReady(
      profile({
        credentials: [
          {
            credential_type: "medical_registration",
            status: "verified",
            expires_at: null,
          },
          {
            // An unexpected literal still renders, rather than going blank.
            credential_type: "pharmacist_registration",
            status: "verified",
            expires_at: null,
          },
        ],
      }),
    );

    const rows = screen.getAllByTestId("profile-credential");
    expect(rows[0]).toHaveTextContent(t.credentialType.medical_registration);
    expect(rows[1]).toHaveTextContent("pharmacist_registration");
  });

  it("surfaces the retryable error state when the profile read fails", async () => {
    getProfile.mockRejectedValue(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "trace-p9001",
        details: {},
      }),
    );
    render(
      <DoctorProfileProvider>
        <DoctorProfilePage />
      </DoctorProfileProvider>,
    );

    await waitFor(() => screen.getByTestId("error-banner"));
    expect(screen.getByText(t.loadFailed)).toBeInTheDocument();

    getProfile.mockResolvedValue(profile());
    fireEvent.click(screen.getByTestId("error-banner-retry"));
    await waitFor(() => screen.getByTestId("profile-details-form"));
    expect(getProfile).toHaveBeenCalledTimes(2);
  });
});

describe("DoctorProfilePage editable fields", () => {
  it("saves the whole editable projection through the private PUT", async () => {
    await renderReady();

    fireEvent.change(screen.getByTestId("profile-practice-name"), {
      target: { value: "Sunrise Clinic 2" },
    });
    fireEvent.change(screen.getByTestId("profile-experience"), {
      target: { value: "13" },
    });
    fireEvent.change(screen.getByTestId("profile-languages"), {
      target: { value: "Hindi, English, Maithili" },
    });
    fireEvent.change(screen.getByTestId("profile-about"), {
      target: { value: "Now also runs evening clinics." },
    });
    fireEvent.click(screen.getByTestId("profile-notification-case_updates"));
    fireEvent.click(screen.getByTestId("profile-save"));

    await waitFor(() =>
      expect(screen.getByTestId("profile-saved")).toHaveTextContent(t.saved),
    );

    expect(saveProfile).toHaveBeenCalledWith(
      {
        practice_name: "Sunrise Clinic 2",
        practice_address: "Main Road, Daltonganj",
        practice_latitude: 24.1957,
        practice_longitude: 85.3656,
        experience_years: 13,
        languages: ["Hindi", "English", "Maithili"],
        about: "Now also runs evening clinics.",
        availability: "Mon-Sat, 9am-1pm",
        // The canonical toggles plus the one key the server already holds.
        notification_preferences: {
          new_consultations: true,
          record_shared: false,
          pre_summary_ready: false,
          case_updates: true,
          credential_status: false,
        },
      },
      expect.any(String),
    );
  });

  // #583, story 16: an answer that lands while the doctor is typing must not
  // throw the typing away. Object identity alone does not decide this - a save's
  // reply and an upload's ref are each a *new* projection, so both would reseed
  // the buffer and wipe whatever was typed since. Both writes are held open here
  // so the answer provably lands *after* the keystrokes; a write that resolved on
  // the spot would be adopted before the typing and prove nothing.
  it("keeps in-progress typing when a save's own reply lands after it", async () => {
    await renderReady();
    let settle: (view: DoctorProfileView) => void = () => {};
    saveProfile.mockImplementationOnce(
      () =>
        new Promise<DoctorProfileView>((resolve) => {
          settle = resolve;
        }),
    );

    fireEvent.click(screen.getByTestId("profile-save"));
    await waitFor(() => expect(saveProfile).toHaveBeenCalledTimes(1));
    fireEvent.change(screen.getByTestId("profile-practice-name"), {
      target: { value: "Sunrise Clinic, typing" },
    });

    // The write lands now, carrying the name as it was when it was clicked.
    settle(profile({ practice_name: "Sunrise Clinic" }));
    await waitFor(() =>
      expect(screen.getByTestId("profile-saved")).toHaveTextContent(t.saved),
    );

    expect(screen.getByTestId("profile-practice-name")).toHaveValue(
      "Sunrise Clinic, typing",
    );
  });

  it("keeps in-progress typing when an upload's answer lands after it", async () => {
    await renderReady();
    fireEvent.change(screen.getByTestId("profile-about"), {
      target: { value: "Mid-sentence edit." },
    });
    let settle: (ref: { photo_ref: string }) => void = () => {};
    uploadPhoto.mockImplementationOnce(
      () =>
        new Promise<{ photo_ref: string }>((resolve) => {
          settle = resolve;
        }),
    );

    fireEvent.change(screen.getByTestId("profile-photo-input"), {
      target: {
        files: [new File(["photo"], "me.jpg", { type: "image/jpeg" })],
      },
    });
    await waitFor(() => expect(uploadPhoto).toHaveBeenCalled());
    settle({ photo_ref: "doctor/7/photo-2.enc" });

    // The photo answer reseeds nothing the doctor was writing. Waited on the
    // settled preview rather than the button, because the reseed lands in an
    // effect after the commit that hides the button.
    await waitFor(() =>
      expect(
        screen.getByTestId("profile-photo").querySelector("img"),
      ).not.toBeNull(),
    );
    expect(screen.getByTestId("profile-about")).toHaveValue(
      "Mid-sentence edit.",
    );
  });

  it("reuses one idempotency key across a retry of the same save", async () => {
    saveProfile.mockRejectedValueOnce(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "t",
        details: {},
      }),
    );
    await renderReady();

    fireEvent.click(screen.getByTestId("profile-save"));
    await waitFor(() => expect(saveProfile).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByTestId("error-banner-retry"));
    await waitFor(() => expect(saveProfile).toHaveBeenCalledTimes(2));

    expect(saveProfile.mock.calls[0][1]).toBe(saveProfile.mock.calls[1][1]);
  });

  it("mints a new idempotency key once the form is edited", async () => {
    saveProfile.mockRejectedValue(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "t",
        details: {},
      }),
    );
    await renderReady();

    fireEvent.click(screen.getByTestId("profile-save"));
    await waitFor(() => expect(saveProfile).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByTestId("profile-practice-name"), {
      target: { value: "Sunrise Clinic 3" },
    });
    fireEvent.click(screen.getByTestId("profile-save"));
    await waitFor(() => expect(saveProfile).toHaveBeenCalledTimes(2));

    expect(saveProfile.mock.calls[0][1]).not.toBe(saveProfile.mock.calls[1][1]);
  });

  it("carries an unknown stored notification key through the save", async () => {
    await renderReady(
      profile({ notification_preferences: { sms_digest: true } }),
    );

    fireEvent.click(screen.getByTestId("profile-save"));

    await waitFor(() => expect(saveProfile).toHaveBeenCalled());
    expect(saveProfile.mock.calls[0][0]?.notification_preferences).toEqual({
      new_consultations: false,
      record_shared: false,
      pre_summary_ready: false,
      case_updates: false,
      credential_status: false,
      sms_digest: true,
    });
  });

  it("keeps a full stored preference dict saveable without exceeding the cap", async () => {
    // The validator refuses more than 20 entries, so a doctor holding a full
    // dict must not have the canonical toggles added on top of it.
    const stored = Object.fromEntries(
      Array.from({ length: 20 }, (_, i) => [`legacy_${i}`, i % 2 === 0]),
    );
    await renderReady(profile({ notification_preferences: stored }));

    fireEvent.click(screen.getByTestId("profile-save"));

    await waitFor(() => expect(saveProfile).toHaveBeenCalled());
    const sent = saveProfile.mock.calls[0][0]?.notification_preferences ?? {};
    expect(Object.keys(sent)).toHaveLength(20);
    expect(sent.legacy_0).toBe(true);
    expect(sent.legacy_19).toBe(false);
    // The toggles still render, and a flip is what adds the key back.
    expect(
      screen.getByTestId("profile-notification-new_consultations"),
    ).not.toBeChecked();
    // The save has to have settled before the next interaction: its reply lands
    // on the shared source, and the buffer is the thing the flip is about.
    await waitFor(() =>
      expect(screen.getByTestId("profile-saved")).toHaveTextContent(t.saved),
    );
    fireEvent.click(screen.getByTestId("profile-notification-case_updates"));
    fireEvent.click(screen.getByTestId("profile-save"));
    await waitFor(() => expect(saveProfile).toHaveBeenCalledTimes(2));
    expect(
      saveProfile.mock.calls[1][0]?.notification_preferences.case_updates,
    ).toBe(true);
  });

  it("blocks a save with an unusable address or latitude before calling the API", async () => {
    await renderReady();

    fireEvent.change(screen.getByTestId("profile-address"), {
      target: { value: "  " },
    });
    fireEvent.change(screen.getByTestId("profile-latitude"), {
      target: { value: "120" },
    });
    fireEvent.click(screen.getByTestId("profile-save"));

    await waitFor(() =>
      expect(screen.getByTestId("profile-invalid")).toHaveTextContent(
        t.invalidFields,
      ),
    );
    expect(saveProfile).not.toHaveBeenCalled();
    expect(screen.getByTestId("profile-address")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(screen.getByTestId("profile-latitude")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
  });

  it("blocks an over-long free-text field before calling the API", async () => {
    await renderReady();

    fireEvent.change(screen.getByTestId("profile-about"), {
      target: { value: "x".repeat(5001) },
    });
    fireEvent.click(screen.getByTestId("profile-save"));

    await waitFor(() =>
      expect(screen.getByTestId("profile-invalid")).toHaveTextContent(
        t.invalidFields,
      ),
    );
    expect(saveProfile).not.toHaveBeenCalled();
    expect(screen.getByTestId("profile-about")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
  });

  it("blocks an over-long or over-numerous language list", async () => {
    await renderReady();

    fireEvent.change(screen.getByTestId("profile-languages"), {
      target: { value: "Hindi, " + "x".repeat(51) },
    });
    fireEvent.click(screen.getByTestId("profile-save"));
    await waitFor(() =>
      expect(screen.getByTestId("profile-invalid")).toBeInTheDocument(),
    );
    expect(saveProfile).not.toHaveBeenCalled();

    fireEvent.change(screen.getByTestId("profile-languages"), {
      target: {
        value: Array.from({ length: 21 }, (_, i) => `Lang${i}`).join(", "),
      },
    });
    fireEvent.click(screen.getByTestId("profile-save"));
    await waitFor(() =>
      expect(screen.getByTestId("profile-languages")).toHaveAttribute(
        "aria-invalid",
        "true",
      ),
    );
    expect(saveProfile).not.toHaveBeenCalled();
  });

  it("surfaces the save failure with the API trace id and a retry", async () => {
    saveProfile.mockRejectedValue(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "trace-save-543",
        details: {},
      }),
    );
    await renderReady();

    fireEvent.click(screen.getByTestId("profile-save"));

    const banner = await screen.findByTestId("error-banner");
    expect(banner).toHaveTextContent(t.saveFailed);
    expect(
      within(screen.getByTestId("profile-details-form")).getByTestId(
        "error-banner-trace-id",
      ),
    ).toHaveTextContent("trace-save-543");
  });
});

describe("DoctorProfilePage photo", () => {
  it("previews the stored photo through an object URL, never the media key", async () => {
    await renderReady(profile({ photo_ref: "doctor/7/photo-1.enc" }));

    await waitFor(() => expect(getPhoto).toHaveBeenCalled());
    const avatar = screen.getByTestId("profile-photo").querySelector("img");
    await waitFor(() => expect(avatar).not.toBeNull());
    expect(avatar?.getAttribute("src")).toBe(
      "blob:http://localhost/doctor-photo",
    );
    expect(avatar?.getAttribute("src")).not.toBe("doctor/7/photo-1.enc");
  });

  it("reads the doctor's photo once, shared with any other surface on that ref", async () => {
    await renderReady(profile({ photo_ref: "doctor/7/photo-1.enc" }));
    // A second surface on the same ref - the account menu and the dropdown
    // header are later work - asks the shared seam, not this page, so the bytes
    // are read once between them rather than once each.
    const other = renderHook(() =>
      useProfilePhotoSource("doctor/7/photo-1.enc", fetchDoctorProfilePhoto),
    );

    await waitFor(() => expect(other.result.current.src).not.toBeNull());
    expect(getPhoto).toHaveBeenCalledTimes(1);
    expect(other.result.current.src).toBe("blob:http://localhost/doctor-photo");
  });

  it("uploads a picked photo and re-streams the stored one", async () => {
    await renderReady();
    const file = new File(["photo"], "me.jpg", { type: "image/jpeg" });

    fireEvent.change(screen.getByTestId("profile-photo-input"), {
      target: { files: [file] },
    });

    await waitFor(() =>
      expect(uploadPhoto).toHaveBeenCalledWith(file, expect.any(String)),
    );
    await waitFor(() => expect(getPhoto).toHaveBeenCalled());
    expect(screen.getByTestId("profile-photo-remove")).toBeInTheDocument();
  });

  it("removes the photo and falls back to the avatar placeholder", async () => {
    await renderReady(profile({ photo_ref: "doctor/7/photo-1.enc" }));
    await waitFor(() => expect(getPhoto).toHaveBeenCalled());

    fireEvent.click(screen.getByTestId("profile-photo-remove"));

    await waitFor(() => expect(deletePhoto).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.queryByTestId("profile-photo-remove")).toBeNull(),
    );
    // The preview effect clears the object URL once the ref drops, so the
    // avatar is asserted on the settled state, not the first render after.
    await waitFor(() =>
      expect(
        screen.getByTestId("profile-photo").querySelector("img"),
      ).toBeNull(),
    );
  });

  it("reports an upload failure with the API trace, keeping the stored photo", async () => {
    uploadPhoto.mockRejectedValue(
      new ApiError({
        code: "INVALID_ARGS",
        message: "unsupported type",
        trace_id: "trace-photo-543",
        details: {},
      }),
    );
    await renderReady(profile({ photo_ref: "doctor/7/photo-1.enc" }));

    fireEvent.change(screen.getByTestId("profile-photo-input"), {
      target: { files: [new File(["x"], "x.txt", { type: "text/plain" })] },
    });

    const banner = await screen.findByTestId("error-banner");
    expect(banner).toHaveTextContent(t.photoFailed);
    expect(screen.getByTestId("error-banner-trace-id")).toHaveTextContent(
      "trace-photo-543",
    );
    // A failed upload leaves the stored photo in place and offers no retry:
    // the picked file is gone, so the doctor picks again.
    expect(screen.getByTestId("profile-photo-remove")).toBeInTheDocument();
    expect(
      within(screen.getByTestId("error-banner")).queryByTestId(
        "error-banner-retry",
      ),
    ).toBeNull();
  });

  it("degrades to the avatar fallback when the photo stream fails", async () => {
    getPhoto.mockRejectedValue(
      new ApiError({
        code: "DOCTOR_PROFILE_PHOTO_NOT_FOUND",
        message: "no photo",
        trace_id: "t",
        details: {},
      }),
    );
    await renderReady(profile({ photo_ref: "doctor/7/photo-1.enc" }));

    await waitFor(() => expect(getPhoto).toHaveBeenCalled());
    expect(screen.getByTestId("profile-photo").querySelector("img")).toBeNull();
    expect(screen.queryByTestId("error-banner")).toBeNull();
    // Nothing is behind the ref, so there is nothing to remove: a definite
    // absence offers Upload rather than a Remove that cannot succeed.
    expect(screen.queryByTestId("profile-photo-remove")).toBeNull();
    expect(screen.getByTestId("profile-photo-upload")).toHaveTextContent(
      t.photoUpload,
    );
  });

  it("keeps the stored photo removable when the read fails rather than finding no photo", async () => {
    getPhoto.mockRejectedValue(
      new ApiError({
        code: "NETWORK_ERROR",
        message: "offline",
        trace_id: "t",
        details: {},
      }),
    );
    await renderReady(profile({ photo_ref: "doctor/7/photo-1.enc" }));

    await waitFor(() => expect(getPhoto).toHaveBeenCalled());
    // A blip is not an absence, so the preview falls back to the avatar and
    // offers no error surface, but the stored photo still reads as a photo the
    // doctor can clear.
    expect(screen.getByTestId("profile-photo").querySelector("img")).toBeNull();
    expect(screen.queryByTestId("error-banner")).toBeNull();
    expect(screen.getByTestId("profile-photo-remove")).toBeInTheDocument();
  });
});

describe("DoctorProfilePage fee editor (moved from the landing)", () => {
  it("shows the current fee from the profile projection", async () => {
    await renderReady();

    expect(screen.getByTestId("fee-editor")).toBeInTheDocument();
    expect(screen.getByTestId("fee-current")).toHaveTextContent("\u20B9400");
    expect(screen.getByTestId("fee-clear")).toBeInTheDocument();
  });

  it("saves the fee through the unchanged fee path", async () => {
    await renderReady();

    fireEvent.change(screen.getByTestId("fee-input"), {
      target: { value: "500" },
    });
    fireEvent.click(screen.getByTestId("fee-save"));

    await waitFor(() =>
      expect(screen.getByTestId("fee-message")).toHaveTextContent(t.feeSaved),
    );
    expect(setFee).toHaveBeenCalledWith(50000, expect.any(String));
    expect(screen.getByTestId("fee-current")).toHaveTextContent("\u20B9500");
  });

  it("names a negative amount instead of silently ignoring the save", async () => {
    await renderReady();

    fireEvent.change(screen.getByTestId("fee-input"), {
      target: { value: "-5" },
    });
    fireEvent.click(screen.getByTestId("fee-save"));

    await waitFor(() =>
      expect(screen.getByTestId("fee-invalid")).toHaveTextContent(t.feeInvalid),
    );
    expect(setFee).not.toHaveBeenCalled();
  });

  it("clears the fee back to unset", async () => {
    await renderReady();

    fireEvent.click(screen.getByTestId("fee-clear"));

    await waitFor(() =>
      expect(screen.getByTestId("fee-message")).toHaveTextContent(t.feeSaved),
    );
    expect(setFee).toHaveBeenCalledWith(null, expect.any(String));
    expect(screen.queryByTestId("fee-current")).toBeNull();
    expect(screen.queryByTestId("fee-clear")).toBeNull();
  });

  it("surfaces the fee save failure with the API trace id", async () => {
    setFee.mockRejectedValue(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "trace-fee-543",
        details: {},
      }),
    );
    await renderReady();

    fireEvent.change(screen.getByTestId("fee-input"), {
      target: { value: "500" },
    });
    fireEvent.click(screen.getByTestId("fee-save"));

    const banner = await within(screen.getByTestId("fee-editor")).findByTestId(
      "error-banner",
    );
    expect(banner).toHaveTextContent(t.feeSaveFailed);
    expect(
      within(screen.getByTestId("fee-editor")).getByTestId(
        "error-banner-trace-id",
      ),
    ).toHaveTextContent("trace-fee-543");
  });
});

describe("DoctorProfilePage bilingual parity (REQ-006)", () => {
  function LangFlipHost() {
    const { lang, setLang } = useLang();
    return (
      <>
        <button
          type="button"
          onClick={() => setLang(lang === "en" ? "hi" : "en")}
        >
          flip-lang
        </button>
        <DoctorProfilePage />
      </>
    );
  }

  it("renders the profile copy in Hindi when the locale flips", async () => {
    getProfile.mockResolvedValue(profile());
    render(
      <DoctorProfileProvider>
        <LangFlipHost />
      </DoctorProfileProvider>,
    );
    await waitFor(() => screen.getByTestId("profile-details-form"));

    fireEvent.click(screen.getByText("flip-lang"));
    await waitFor(() => screen.getByText(hiT.title));

    expect(screen.getByTestId("profile-save")).toHaveTextContent(hiT.save);
    expect(screen.getByTestId("fee-editor")).toHaveTextContent(hiT.feeHeading);
    expect(screen.getByTestId("profile-public-preview")).toHaveTextContent(
      hiT.publicPreviewAction,
    );
  });
});
