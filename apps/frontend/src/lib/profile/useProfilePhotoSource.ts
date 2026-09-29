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
// shows "me" (#548's card, #557's chrome avatars, #568's doctor profile page),
// so the resolution is cached by ref: one ref, one request, however many
// consumers ask. Each surface supplies its own byte reader - a doctor's photo
// is a different endpoint - so the seam is the resolution discipline, not a
// call to one account's transport: a second account gets the same cache, the
// same object-URL ownership and the same two failure answers without a second
// implementation to drift.
//
// Two failure answers stay distinct, because they are not the same fact. Only a
// definite not-found reports absence: the completion wizard persists a bare
// file name as a placeholder until a real upload lands, so a set ref is a claim,
// not proof of media, and a claim with nothing behind it must offer Upload
// rather than Remove. Any other failure leaves `absent` false, because a stored
// photo that would not load must not look absent or the patient's only way to
// clear it disappears. A blip is cached like any other answer and re-read on the
// next ref change, so nothing retries in a loop and a surface that mounts later
// shares the one request instead of adding a second failure.

import { useEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api-errors";
import { fetchPatientPhoto } from "@/lib/profile/api";

/**
 * The backend's answers that a ref has no media behind it. The two photo
 * endpoints stream private bytes under their own 404 code - `/v1/me/photo`
 * answers `PROFILE_PHOTO_NOT_FOUND` and the doctor's own photo answers
 * `DOCTOR_PROFILE_PHOTO_NOT_FOUND` - so the seam reads absence off the set
 * rather than one endpoint's spelling. What it distinguishes is a *definite*
 * absence from a blip, not which route answered.
 */
const PHOTO_NOT_FOUND_CODES: ReadonlySet<string> = new Set([
  "PROFILE_PHOTO_NOT_FOUND",
  "DOCTOR_PROFILE_PHOTO_NOT_FOUND",
]);

/**
 * Reads the caller's own current stored photo bytes over the authed transport.
 * It takes no ref, because both endpoints serve the caller's *current* photo:
 * the ref says which generation a consumer believes it is showing, so it keys
 * the cache rather than selecting the bytes. Refs are actor-namespaced, so two
 * readers never collide on one cache key.
 */
export type ProfilePhotoReader = () => Promise<Blob>;

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
  /** True only for a definite not-found answer from the bytes endpoint. */
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
 *
 * The ref is the cache key, not a request parameter: the endpoint serves the
 * caller's *current* photo, so a ref says which generation a consumer believes
 * it is showing, never which bytes to ask for.
 */
const CACHE = new Map<string, CacheEntry>();

async function resolveStoredPhoto(
  read: ProfilePhotoReader,
): Promise<ResolvedPhoto> {
  try {
    return { blob: await read(), absent: false };
  } catch (err) {
    return {
      blob: null,
      absent: err instanceof ApiError && PHOTO_NOT_FOUND_CODES.has(err.code),
    };
  }
}

function acquire(ref: string, read: ProfilePhotoReader): CacheEntry {
  const cached = CACHE.get(ref);
  if (cached !== undefined) {
    cached.holders += 1;
    return cached;
  }
  const entry: CacheEntry = { ready: resolveStoredPhoto(read), holders: 1 };
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
 * touched. The reader defaults to the caller's own patient transport, so every
 * surface showing the caller's photo asks for it without naming an endpoint.
 */
export function useProfilePhotoSource(
  photoRef: string | null,
  read: ProfilePhotoReader = fetchPatientPhoto,
): ProfilePhotoSource {
  const [source, setSource] = useState<ProfilePhotoSource>(NO_SOURCE);
  // Which account to ask is not a per-render input, so the reader is held here
  // rather than listed as an effect dependency: an inline closure would arrive
  // as a fresh identity every render and re-read - and revoke - the photo every
  // render. A different account brings a different ref, so a genuine change of
  // transport still arrives as a ref change and re-resolves.
  const reader = useRef(read);
  reader.current = read;

  useEffect(() => {
    if (photoRef == null) {
      setSource(NO_SOURCE);
      return;
    }
    // Some environments (SSR, a bare jsdom) cannot make an object URL at all, so
    // there is no renderable source to produce whatever the backend answers. That
    // is a missing capability, not a missing photo, so nothing is asked for and
    // absence stays false - the consumer falls through to the name initial.
    if (typeof URL.createObjectURL !== "function") {
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
    const entry = acquire(photoRef, reader.current);

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
