"use client";

// #556 (slice C1 of #553): the one client-side seam that turns a stored
// profile-media ref into something an <img> can render. A ref is an opaque
// object key (ADR-0020 D1) and photos are never publicly addressable (D2), so
// the bytes are streamed through the authed transport and presented as an
// object URL. No consumer builds that URL itself: it hands the ref here and
// gets a renderable source, or null to fall through to the name initial. The
// avatar primitive therefore stays presentational and keeps no transport
// knowledge - the photo branch it already carries simply has a producer now.
//
// It lives beside the profile client (lib/profile/, next to api.ts) because
// that is where the transport wrapper it builds on sits, and it follows the
// lib/auth/useRoleHomeHref.ts shape for a shared hook. More than one surface
// shows "me" (#548's card, #557's chrome avatars), so the resolution is cached
// by ref: one ref, one request, however many consumers ask.
//
// Two failure answers stay distinct, because they are not the same fact. A
// definite "no media behind this ref" (PROFILE_PHOTO_NOT_FOUND) is an answer -
// the completion wizard persists a bare file name as a placeholder until a real
// upload lands, so a set ref is a claim, not proof of media, and a claim with
// nothing behind it must offer Upload rather than Remove. Any other failure is
// a blip, not an answer: absence is never reported, because a stored photo that
// would not load must not look absent or the patient's only way to clear it
// disappears. A blip is cached like any other answer and re-read on the next
// ref change, so nothing retries in a loop and a surface mounting later shares
// the one request rather than adding a second failure.

import { useEffect, useState } from "react";

import { ApiError } from "@/lib/api-errors";
import { fetchPatientPhoto } from "@/lib/profile/api";

/** The backend's answer when the ref has no media behind it. */
const PHOTO_NOT_FOUND_CODE = "PROFILE_PHOTO_NOT_FOUND";

export interface ProfilePhotoSource {
  /**
   * A renderable object URL for the stored bytes, or null when there is nothing
   * to show - no ref, still streaming, or unreadable. The avatar primitive
   * falls through to the name initial on null.
   */
  src: string | null;
  /**
   * True only when the backend answered that this ref has no media behind it.
   * A failed read is not absence: it leaves `absent` false so the stored photo
   * still reads as a photo.
   */
  absent: boolean;
}

/** The bytes a ref resolved to, or the fact that there are none to show. */
interface ResolvedPhoto {
  /** The stored bytes, or null when the ref resolved to nothing renderable. */
  blob: Blob | null;
  /** True only for the definite PROFILE_PHOTO_NOT_FOUND answer. */
  absent: boolean;
}

interface CacheEntry {
  /** The one resolution for this ref; every consumer of it awaits this promise. */
  ready: Promise<ResolvedPhoto>;
  /** Live consumers of this ref. The entry is dropped when the last one lets go. */
  holders: number;
}

const NO_SOURCE: ProfilePhotoSource = { src: null, absent: false };
const ABSENT: ProfilePhotoSource = { src: null, absent: true };

/**
 * Keyed by the stored ref, so the same photo is read once no matter how many
 * surfaces show it, and a replace, a remove, or a fresh mount never inherits
 * bytes that may have moved on.
 */
const CACHE = new Map<string, CacheEntry>();

async function resolveStoredPhoto(): Promise<ResolvedPhoto> {
  try {
    const blob = await fetchPatientPhoto();
    // An environment with no object URLs (SSR, a bare jsdom) has no renderable
    // source to hand back. That is a missing capability, not a missing photo, so
    // absence stays false and the consumer falls through to the name initial.
    if (typeof URL.createObjectURL !== "function") {
      return { blob: null, absent: false };
    }
    return { blob, absent: false };
  } catch (err) {
    return {
      blob: null,
      absent: err instanceof ApiError && err.code === PHOTO_NOT_FOUND_CODE,
    };
  }
}

function acquire(ref: string): CacheEntry {
  const cached = CACHE.get(ref);
  if (cached !== undefined) {
    cached.holders += 1;
    return cached;
  }
  const entry: CacheEntry = { ready: resolveStoredPhoto(), holders: 1 };
  CACHE.set(ref, entry);
  return entry;
}

function release(ref: string, entry: CacheEntry): void {
  entry.holders -= 1;
  if (entry.holders > 0) return;
  // Nothing is showing these bytes any more, so the entry goes with them: a
  // later ask re-reads the ref instead of being answered from a dead cache.
  CACHE.delete(ref);
}

/**
 * Resolve a stored profile-media ref to a renderable source. Null in, null out:
 * with no ref there is nothing to ask for, so the bytes endpoint is never
 * touched.
 */
export function useProfilePhotoSource(
  photoRef: string | null,
): ProfilePhotoSource {
  const [source, setSource] = useState<ProfilePhotoSource>(NO_SOURCE);

  useEffect(() => {
    if (photoRef == null) {
      setSource(NO_SOURCE);
      return;
    }
    let live = true;
    // The URL is the consumer's to own: it is created only while this consumer
    // is still mounted, and revoked only by the cleanup that ends that mount.
    // So a ref change can never leave a revoked URL behind in a view, and an
    // unmount mid-stream never creates one at all.
    let objectUrl: string | null = null;
    setSource(NO_SOURCE);
    const entry = acquire(photoRef);

    void entry.ready.then((resolved) => {
      if (!live) return;
      if (resolved.blob == null) {
        setSource(resolved.absent ? ABSENT : NO_SOURCE);
        return;
      }
      objectUrl = URL.createObjectURL(resolved.blob);
      setSource({ src: objectUrl, absent: false });
    });

    return () => {
      live = false;
      if (objectUrl != null) {
        URL.revokeObjectURL(objectUrl);
      }
      release(photoRef, entry);
    };
  }, [photoRef]);

  return source;
}
