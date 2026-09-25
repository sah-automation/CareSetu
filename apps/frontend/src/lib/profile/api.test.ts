// #548: the patient profile photo client contract (backend #533). The photo
// surface is its own endpoint trio - PUT stores/replaces and answers the
// updated profile, GET streams the stored bytes for the preview, DELETE clears
// the ref and answers the updated profile. The ref stays private: it is an
// opaque profile-media key, never a public URL, and the preview streams the
// bytes over the authed transport.

import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-errors";
import { IDEMPOTENCY_KEY_HEADER } from "@/lib/idempotency";
import {
  deletePatientPhoto,
  fetchPatientPhoto,
  saveProfile,
  uploadPatientPhoto,
  type StoredPatientProfile,
} from "./api";

const profile: StoredPatientProfile = {
  name: "Asha Devi",
  age: 30,
  gender: "female",
  preferred_language: "en",
  area: "Bishrampur",
  emergency_contact: null,
  photo_ref: "patient/7/photo-1.enc",
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function photoFile(): File {
  return new File([new Uint8Array([1, 2, 3])], "me.png", {
    type: "image/png",
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("uploadPatientPhoto", () => {
  it("PUTs the picked file as multipart and resolves the updated profile", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ set: true, profile }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(uploadPatientPhoto(photoFile(), "retry-1")).resolves.toEqual(
      profile,
    );

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/v1/me/photo");
    expect(init.method).toBe("PUT");
    expect(init.credentials).toBe("include");
    const headers = new Headers(init.headers);
    expect(headers.get(IDEMPOTENCY_KEY_HEADER)).toBe("retry-1");
    // The boundary is the browser's to set: an explicit Content-Type here
    // would strip it and the multipart body would not parse.
    expect(headers.get("Content-Type")).toBeNull();
    const body = init.body as FormData;
    expect(body).toBeInstanceOf(FormData);
    expect((body.get("file") as File).name).toBe("me.png");
  });

  it("mints an idempotency key when the caller supplies none", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ set: true, profile }));
    vi.stubGlobal("fetch", fetchMock);

    await uploadPatientPhoto(photoFile());

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new Headers(init.headers).get(IDEMPOTENCY_KEY_HEADER)).toBeTruthy();
  });

  it("surfaces the backend's PROFILE_PHOTO_INVALID rejection", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            code: "PROFILE_PHOTO_INVALID",
            message: "unsupported media type",
            trace_id: "t-1",
            details: {},
          },
          422,
        ),
      ),
    );

    await expect(uploadPatientPhoto(photoFile())).rejects.toMatchObject({
      code: "PROFILE_PHOTO_INVALID",
    });
  });

  it("throws UNEXPECTED_ERROR when the backend answers a non-set profile", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ set: false, profile: null })),
    );

    await expect(uploadPatientPhoto(photoFile())).rejects.toBeInstanceOf(
      ApiError,
    );
  });
});

describe("fetchPatientPhoto", () => {
  it("streams the stored bytes as a blob", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(new Uint8Array([7, 8, 9]), {
        status: 200,
        headers: { "Content-Type": "image/png" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const blob = await fetchPatientPhoto();

    expect(blob).toBeInstanceOf(Blob);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/v1/me/photo");
    expect(init.credentials).toBe("include");
  });

  it("throws ApiError when no photo is stored (404)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            code: "PROFILE_PHOTO_NOT_FOUND",
            message: "no profile photo is set for this patient",
            trace_id: "t-2",
            details: {},
          },
          404,
        ),
      ),
    );

    await expect(fetchPatientPhoto()).rejects.toMatchObject({
      code: "PROFILE_PHOTO_NOT_FOUND",
    });
  });
});

describe("deletePatientPhoto", () => {
  it("DELETEs and resolves the profile with the ref cleared", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        jsonResponse({ set: true, profile: { ...profile, photo_ref: null } }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await expect(deletePatientPhoto("retry-2")).resolves.toMatchObject({
      photo_ref: null,
    });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/v1/me/photo");
    expect(init.method).toBe("DELETE");
    expect(new Headers(init.headers).get(IDEMPOTENCY_KEY_HEADER)).toBe(
      "retry-2",
    );
  });
});

describe("saveProfile (AC: the identity save keeps its idempotency)", () => {
  it("carries an Idempotency-Key, and the caller's key across a retry", async () => {
    // A fresh Response per call: a body can only be read once.
    const fetchMock = vi
      .fn()
      .mockImplementation(() => jsonResponse({ set: true, profile }));
    vi.stubGlobal("fetch", fetchMock);

    await saveProfile(profile);
    await saveProfile(profile, "retry-3");

    const first = new Headers(
      (fetchMock.mock.calls[0] as [string, RequestInit])[1].headers,
    ).get(IDEMPOTENCY_KEY_HEADER);
    const second = new Headers(
      (fetchMock.mock.calls[1] as [string, RequestInit])[1].headers,
    ).get(IDEMPOTENCY_KEY_HEADER);
    // A fresh key per attempt, but the retry's key is the one the caller chose,
    // so re-issuing the save is deduplicated rather than written twice.
    expect(first).toEqual(expect.any(String));
    expect(first).not.toBe("");
    expect(second).toBe("retry-3");
  });
});
