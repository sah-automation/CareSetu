// #556: the shared profile-photo resolution seam. A stored ref is an opaque
// object key (ADR-0020 D1/D2), so no consumer can build a URL for it - it asks
// this hook and gets a renderable object URL, or null to fall through to the
// name initial. These tests pin the hook's own contract, so the consumers
// (#548's card, #557's chrome avatars) can stay dumb: one ref resolves once
// whatever the consumer count, the object URL is revoked when its last holder
// lets go, and a definite "no media behind this ref" is never confused with a
// failed read.

import { cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  useProfilePhotoSource,
  type ProfilePhotoReader,
} from "./useProfilePhotoSource";
import { ApiError } from "@/lib/api-errors";
import { fetchPatientPhoto } from "@/lib/profile/api";

vi.mock("@/lib/profile/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/profile/api")>();
  return { ...mod, fetchPatientPhoto: vi.fn() };
});

const getPhoto = vi.mocked(fetchPatientPhoto);

const REF = "patient/7/photo-1.enc";
const OTHER_REF = "patient/7/photo-2.enc";
const DOCTOR_REF = "doctor/7/photo-1.enc";
const OTHER_DOCTOR_REF = "doctor/7/photo-2.enc";

// The two photo endpoints spell their 404 differently - /v1/me/photo answers
// PROFILE_PHOTO_NOT_FOUND and the doctor's own photo answers
// DOCTOR_PROFILE_PHOTO_NOT_FOUND - so the fixture takes the code.
function photoNotFound(code = "PROFILE_PHOTO_NOT_FOUND"): ApiError {
  return new ApiError({
    code,
    message: "no photo",
    trace_id: "trace-556",
    details: {},
  });
}

function networkBlip(): ApiError {
  return new ApiError({
    code: "NETWORK_ERROR",
    message: "offline",
    trace_id: "trace-556",
    details: {},
  });
}

let originalCreate: typeof URL.createObjectURL;
let originalRevoke: typeof URL.revokeObjectURL;
let created: number;

beforeEach(() => {
  getPhoto.mockReset();
  getPhoto.mockResolvedValue(new Blob(["photo"], { type: "image/png" }));
  originalCreate = URL.createObjectURL;
  originalRevoke = URL.revokeObjectURL;
  created = 0;
  // A distinct URL per call so a test can tell *which* bytes were revoked.
  URL.createObjectURL = vi.fn(
    () => `blob:http://localhost/photo-${(created += 1)}`,
  ) as unknown as typeof URL.createObjectURL;
  URL.revokeObjectURL = vi.fn() as unknown as typeof URL.revokeObjectURL;
});

afterEach(() => {
  // Unmounting is what drops the cache entry, so it has to happen before the
  // stubs are restored - otherwise the revoke is asserted against a real
  // revoke and the next test inherits a live entry.
  cleanup();
  URL.createObjectURL = originalCreate;
  URL.revokeObjectURL = originalRevoke;
  vi.clearAllMocks();
});

function renderSource(
  initialRef: string | null,
  /** A surface that brings its own account's transport rather than the default. */
  read?: ProfilePhotoReader,
) {
  return renderHook(
    ({ ref }: { ref: string | null }) => useProfilePhotoSource(ref, read),
    { initialProps: { ref: initialRef } },
  );
}

/** Let the mocked fetch settle and its handler run, without asserting on state. */
async function flush(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 0));
}

describe("useProfilePhotoSource", () => {
  it("streams the bytes over the authed transport and hands back an object URL", async () => {
    const { result } = renderSource(REF);

    await waitFor(() =>
      expect(result.current.src).toBe("blob:http://localhost/photo-1"),
    );
    expect(getPhoto).toHaveBeenCalledTimes(1);
    expect(result.current.absent).toBe(false);
  });

  it("yields no source and never asks for bytes when the ref is absent", () => {
    const { result } = renderSource(null);

    expect(result.current).toEqual({ src: null, absent: false });
    expect(getPhoto).not.toHaveBeenCalled();
  });

  it("asks the backend once for a ref however many consumers show it", async () => {
    const first = renderSource(REF);
    const second = renderSource(REF);

    await waitFor(() => expect(first.result.current.src).not.toBeNull());
    // One request for the ref, not one per consumer - that is the whole point
    // of the cache. The object URLs are per consumer, so each view only ever
    // revokes a URL it is itself rendering.
    expect(getPhoto).toHaveBeenCalledTimes(1);
    expect(first.result.current.src).toBe("blob:http://localhost/photo-1");
    expect(second.result.current.src).toBe("blob:http://localhost/photo-2");
  });

  it("keeps answering a ref while any consumer still shows it", async () => {
    // The desktop account menu opens and closes repeatedly against a trigger
    // that never unmounts, so a consumer mounting after another one let go must
    // still be answered from the live entry rather than re-reading the photo.
    const trigger = renderSource(REF);
    const menu = renderSource(REF);
    await waitFor(() => expect(trigger.result.current.src).not.toBeNull());
    menu.unmount();

    const reopened = renderSource(REF);
    await waitFor(() => expect(reopened.result.current.src).not.toBeNull());
    expect(getPhoto).toHaveBeenCalledTimes(1);
  });

  it("revokes only the URL its own consumer created", async () => {
    const first = renderSource(REF);
    const second = renderSource(REF);
    await waitFor(() => expect(first.result.current.src).not.toBeNull());

    first.unmount();
    // The other surface is still showing these bytes, so its URL must survive
    // the first one going away.
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(1);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith(
      "blob:http://localhost/photo-1",
    );
    expect(second.result.current.src).toBe("blob:http://localhost/photo-2");

    second.unmount();
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(2);
    expect(URL.revokeObjectURL).toHaveBeenLastCalledWith(
      "blob:http://localhost/photo-2",
    );
  });

  it("revokes the object URL on teardown", async () => {
    const { result, unmount } = renderSource(REF);
    await waitFor(() => expect(result.current.src).not.toBeNull());

    unmount();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith(
      "blob:http://localhost/photo-1",
    );
  });

  it("revokes the old bytes, resolves the new ref, and re-reads a replaced ref", async () => {
    const { result, rerender } = renderSource(REF);
    await waitFor(() =>
      expect(result.current.src).toBe("blob:http://localhost/photo-1"),
    );

    await rerender({ ref: OTHER_REF });
    expect(URL.revokeObjectURL).toHaveBeenCalledWith(
      "blob:http://localhost/photo-1",
    );
    await waitFor(() =>
      expect(result.current.src).toBe("blob:http://localhost/photo-2"),
    );

    // Back to the ref that was replaced: the entry it left behind is gone, so
    // the bytes are re-read rather than re-shown from a dead cache.
    await rerender({ ref: REF });
    await waitFor(() =>
      expect(result.current.src).toBe("blob:http://localhost/photo-3"),
    );
    expect(getPhoto).toHaveBeenCalledTimes(3);
  });

  it("drops the cache entry when the ref is cleared, so a stale ref cannot be re-shown", async () => {
    const { result, rerender } = renderSource(REF);
    await waitFor(() => expect(result.current.src).not.toBeNull());

    await rerender({ ref: null });
    expect(result.current).toEqual({ src: null, absent: false });

    // The cleared ref is re-read from the backend rather than answered from the
    // entry the removal was meant to invalidate.
    await rerender({ ref: REF });
    await waitFor(() =>
      expect(result.current.src).toBe("blob:http://localhost/photo-2"),
    );
    expect(getPhoto).toHaveBeenCalledTimes(2);
  });

  it("reports absence only when the backend says the ref has no media", async () => {
    getPhoto.mockRejectedValue(photoNotFound());
    const { result } = renderSource("me.jpg");

    await waitFor(() => expect(result.current.absent).toBe(true));
    expect(result.current.src).toBeNull();
  });

  it("keeps a failed read looking present so it can still be removed", async () => {
    getPhoto.mockRejectedValue(networkBlip());
    const { result } = renderSource(REF);

    // Read against the not-found test above: the same harness with that code
    // settles on `absent: true`, so a settled blip leaving it false is the
    // distinction, not just the state the hook starts in.
    await waitFor(() => expect(getPhoto).toHaveBeenCalled());
    await flush();
    expect(result.current).toEqual({ src: null, absent: false });
    // A blip must not even produce a partial photo to show.
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  it("yields no source where object URLs cannot be made", async () => {
    URL.createObjectURL = undefined as unknown as typeof URL.createObjectURL;
    const { result } = renderSource(REF);

    // Nothing renderable can come of the bytes, so the backend is not asked.
    expect(getPhoto).not.toHaveBeenCalled();
    expect(result.current).toEqual({ src: null, absent: false });
  });
});

// #568: a second account's surface brings its own byte reader rather than
// getting a second implementation. Every promise the seam makes is the same
// promise for that reader - one read per ref, the object URL owned by the
// consumer that renders it, a definite absence never confused with a failed
// read - so the cases above are re-run against an injected reader, plus the one
// thing a caller-supplied reader adds: it must not become a per-render input.
describe("useProfilePhotoSource with a caller-supplied reader", () => {
  /** The doctor's own transport: another account's `() => Promise<Blob>`. */
  function doctorReader() {
    return vi.fn(async () => new Blob(["doctor-photo"], { type: "image/png" }));
  }

  it("never asks a caller-supplied reader for bytes when the ref is absent", () => {
    const read = doctorReader();
    const { result } = renderSource(null, read);

    expect(result.current).toEqual({ src: null, absent: false });
    expect(read).not.toHaveBeenCalled();
  });

  it("asks a caller-supplied reader once for a ref however many consumers show it", async () => {
    const read = doctorReader();
    const first = renderSource(DOCTOR_REF, read);
    const second = renderSource(DOCTOR_REF, read);

    await waitFor(() => expect(first.result.current.src).not.toBeNull());
    expect(read).toHaveBeenCalledTimes(1);
    expect(first.result.current.src).toBe("blob:http://localhost/photo-1");
    expect(second.result.current.src).toBe("blob:http://localhost/photo-2");
  });

  it("does not re-read a ref when the reader arrives as a fresh function each render", async () => {
    // Which account to ask is not a per-render input, so an inline closure must
    // not count as a new one: re-reading per render would stream the photo
    // again, revoke the object URL mid-view and break the one-read contract.
    const read = doctorReader();
    const { result, rerender } = renderHook(
      ({ ref }: { ref: string | null }) =>
        useProfilePhotoSource(ref, () => read()),
      { initialProps: { ref: DOCTOR_REF } },
    );
    await waitFor(() => expect(result.current.src).not.toBeNull());

    await rerender({ ref: DOCTOR_REF });
    await rerender({ ref: DOCTOR_REF });
    expect(read).toHaveBeenCalledTimes(1);
    expect(URL.revokeObjectURL).not.toHaveBeenCalled();
    expect(result.current.src).toBe("blob:http://localhost/photo-1");
  });

  it("reports absence when the supplied reader's endpoint says there is no media", async () => {
    // The doctor's own 404 is a definite absence, so the seam has to read it as
    // one even though it is spelled differently from /v1/me/photo's.
    const read = vi
      .fn()
      .mockRejectedValue(photoNotFound("DOCTOR_PROFILE_PHOTO_NOT_FOUND"));
    const { result } = renderSource(DOCTOR_REF, read);

    await waitFor(() => expect(result.current.absent).toBe(true));
    expect(result.current.src).toBeNull();
  });

  it("keeps a caller-supplied reader's failed read looking present", async () => {
    const read = vi.fn().mockRejectedValue(networkBlip());
    const { result } = renderSource(OTHER_DOCTOR_REF, read);

    // Read against the two settled answers above: a settled blip leaves `absent`
    // false and shows nothing, so the stored photo still reads as a photo and
    // the surface can still offer to remove it.
    await waitFor(() => expect(read).toHaveBeenCalled());
    await flush();
    expect(result.current).toEqual({ src: null, absent: false });
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });
});
