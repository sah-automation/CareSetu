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

import { useProfilePhotoSource } from "./useProfilePhotoSource";
import { ApiError } from "@/lib/api-errors";
import { fetchPatientPhoto } from "@/lib/profile/api";

vi.mock("@/lib/profile/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/profile/api")>();
  return { ...mod, fetchPatientPhoto: vi.fn() };
});

const getPhoto = vi.mocked(fetchPatientPhoto);

const REF = "patient/7/photo-1.enc";
const OTHER_REF = "patient/7/photo-2.enc";

function photoNotFound(): ApiError {
  return new ApiError({
    code: "PROFILE_PHOTO_NOT_FOUND",
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

function renderSource(initialRef: string | null) {
  return renderHook(
    ({ ref }: { ref: string | null }) => useProfilePhotoSource(ref),
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
