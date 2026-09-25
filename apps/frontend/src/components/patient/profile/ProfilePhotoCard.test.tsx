// #548: the patient profile photo control (Identity zone). The photo is
// private profile media, so the preview streams the stored bytes over the
// authed transport and renders them as an object URL - the stored ref is never
// linked. Upload and remove are their own committed writes, and each answers
// the updated profile, so the card reports the new ref upward rather than
// guessing one.

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProfilePhotoCard } from "./ProfilePhotoCard";
import { ApiError } from "@/lib/api-errors";
import { __resetLangForTests } from "@/lib/i18n/LangContext";
import { STRINGS } from "@/lib/i18n/dictionaries";
import {
  deletePatientPhoto,
  fetchPatientPhoto,
  uploadPatientPhoto,
  type StoredPatientProfile,
} from "@/lib/profile/api";

vi.mock("@/lib/profile/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/profile/api")>();
  return {
    ...mod,
    uploadPatientPhoto: vi.fn(),
    fetchPatientPhoto: vi.fn(),
    deletePatientPhoto: vi.fn(),
  };
});

const uploadPhoto = vi.mocked(uploadPatientPhoto);
const getPhoto = vi.mocked(fetchPatientPhoto);
const removePhoto = vi.mocked(deletePatientPhoto);

const t = STRINGS.en.profileZones;

const profile = (overrides: Partial<StoredPatientProfile> = {}) => ({
  name: "Asha Devi",
  age: 30,
  gender: "female",
  preferred_language: "en",
  area: "Bishrampur",
  emergency_contact: null,
  photo_ref: "patient/7/photo-1.enc" as string | null,
  ...overrides,
});

let originalCreate: typeof URL.createObjectURL;
let originalRevoke: typeof URL.revokeObjectURL;

function setup(photoRef: string | null) {
  const onPhotoRefChange = vi.fn();
  const view = render(
    <ProfilePhotoCard
      photoRef={photoRef}
      name="Asha Devi"
      onPhotoRefChange={onPhotoRefChange}
    />,
  );
  return { ...view, onPhotoRefChange };
}

beforeEach(() => {
  window.localStorage.clear();
  __resetLangForTests();
  uploadPhoto.mockReset();
  getPhoto.mockReset();
  removePhoto.mockReset();
  getPhoto.mockResolvedValue(new Blob(["photo"], { type: "image/png" }));
  originalCreate = URL.createObjectURL;
  originalRevoke = URL.revokeObjectURL;
  URL.createObjectURL = vi.fn(
    () => "blob:http://localhost/patient-photo",
  ) as unknown as typeof URL.createObjectURL;
  URL.revokeObjectURL = vi.fn() as unknown as typeof URL.revokeObjectURL;
});

afterEach(() => {
  cleanup();
  URL.createObjectURL = originalCreate;
  URL.revokeObjectURL = originalRevoke;
  vi.clearAllMocks();
});

describe("ProfilePhotoCard", () => {
  it("shows the upload control and the avatar fallback with no stored photo", () => {
    setup(null);

    expect(screen.getByTestId("ps-photo-upload")).toHaveTextContent(
      t.photoUpload,
    );
    expect(screen.queryByTestId("ps-photo-remove")).not.toBeInTheDocument();
    // Nothing to stream, so the bytes endpoint is never asked for.
    expect(getPhoto).not.toHaveBeenCalled();
  });

  it("previews the stored photo through an object URL, never the media key", async () => {
    setup("patient/7/photo-1.enc");

    await waitFor(() => expect(getPhoto).toHaveBeenCalledTimes(1));
    const image = screen.getByTestId("ps-photo-preview").querySelector("img");
    expect(image?.getAttribute("src")).toBe(
      "blob:http://localhost/patient-photo",
    );
    expect(image?.getAttribute("src")).not.toBe("patient/7/photo-1.enc");
    expect(screen.getByTestId("ps-photo-upload")).toHaveTextContent(
      t.photoReplace,
    );
  });

  it("revokes the object URL when the card unmounts", async () => {
    const { unmount } = setup("patient/7/photo-1.enc");

    await waitFor(() => expect(getPhoto).toHaveBeenCalled());
    unmount();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith(
      "blob:http://localhost/patient-photo",
    );
  });

  it("degrades to the avatar fallback when the photo stream fails", async () => {
    getPhoto.mockRejectedValue(
      new ApiError({
        code: "PROFILE_PHOTO_NOT_FOUND",
        message: "no photo",
        trace_id: "trace-548",
        details: {},
      }),
    );
    setup("patient/7/photo-1.enc");

    await waitFor(() => expect(getPhoto).toHaveBeenCalled());
    expect(
      screen.getByTestId("ps-photo-preview").querySelector("img"),
    ).toBeNull();
  });

  it("uploads a picked photo and reports the ref the backend stored", async () => {
    const next = profile({ photo_ref: "patient/7/photo-2.enc" });
    uploadPhoto.mockResolvedValue(next);
    const { onPhotoRefChange } = setup(null);

    const file = new File(["photo"], "me.png", { type: "image/png" });
    fireEvent.change(screen.getByTestId("ps-photo-input"), {
      target: { files: [file] },
    });

    await waitFor(() =>
      expect(uploadPhoto).toHaveBeenCalledWith(file, expect.any(String)),
    );
    await waitFor(() =>
      expect(onPhotoRefChange).toHaveBeenCalledWith("patient/7/photo-2.enc"),
    );
  });

  it("re-fires change when the same file is picked twice", async () => {
    uploadPhoto.mockResolvedValue(profile());
    setup(null);

    const file = new File(["photo"], "me.png", { type: "image/png" });
    const input = screen.getByTestId("ps-photo-input");
    fireEvent.change(input, { target: { files: [file] } });
    await waitFor(() => expect(uploadPhoto).toHaveBeenCalledTimes(1));
    fireEvent.change(input, { target: { files: [file] } });
    await waitFor(() => expect(uploadPhoto).toHaveBeenCalledTimes(2));
  });

  it("keeps the stored photo and reports the failure when an upload is rejected", async () => {
    uploadPhoto.mockRejectedValue(
      new ApiError({
        code: "PROFILE_PHOTO_INVALID",
        message: "unsupported media type",
        trace_id: "trace-photo-548",
        details: {},
      }),
    );
    const { onPhotoRefChange } = setup("patient/7/photo-1.enc");

    const file = new File(["photo"], "me.gif", { type: "image/gif" });
    fireEvent.change(screen.getByTestId("ps-photo-input"), {
      target: { files: [file] },
    });

    await waitFor(() =>
      expect(screen.getByTestId("ps-photo-failed")).toHaveTextContent(
        t.photoFailed,
      ),
    );
    expect(screen.getByTestId("ps-photo-failed")).toHaveTextContent(
      "trace-photo-548",
    );
    // A rejected upload must not pretend the ref moved.
    expect(onPhotoRefChange).not.toHaveBeenCalled();
    expect(screen.getByTestId("ps-photo-remove")).toBeInTheDocument();
  });

  it("removes the photo and reports the cleared ref", async () => {
    removePhoto.mockResolvedValue(profile({ photo_ref: null }));
    const { onPhotoRefChange } = setup("patient/7/photo-1.enc");

    await waitFor(() => expect(getPhoto).toHaveBeenCalled());
    fireEvent.click(screen.getByTestId("ps-photo-remove"));

    await waitFor(() => expect(removePhoto).toHaveBeenCalled());
    await waitFor(() => expect(onPhotoRefChange).toHaveBeenCalledWith(null));
  });

  it("reports a failed removal and keeps the stored photo", async () => {
    removePhoto.mockRejectedValue(
      new ApiError({
        code: "NETWORK_ERROR",
        message: "offline",
        trace_id: "trace-net-548",
        details: {},
      }),
    );
    const { onPhotoRefChange } = setup("patient/7/photo-1.enc");

    await waitFor(() => expect(getPhoto).toHaveBeenCalled());
    fireEvent.click(screen.getByTestId("ps-photo-remove"));

    await waitFor(() =>
      expect(screen.getByTestId("ps-photo-failed")).toBeInTheDocument(),
    );
    expect(onPhotoRefChange).not.toHaveBeenCalled();
    expect(screen.getByTestId("ps-photo-remove")).toBeInTheDocument();
  });

  it("ships every photo string in both locales", () => {
    for (const key of [
      "photoHeading",
      "photoHelp",
      "photoUpload",
      "photoReplace",
      "photoRemove",
      "photoFailed",
    ] as const) {
      expect(STRINGS.hi.profileZones[key]).toBeTruthy();
    }
  });
});
