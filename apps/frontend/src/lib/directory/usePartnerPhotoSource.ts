"use client";

import { useEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api-errors";
import { fetchPartnerPhoto } from "@/lib/directory/profile";

const PHOTO_NOT_FOUND_CODES: ReadonlySet<string> = new Set([
  "PROFILE_PHOTO_NOT_FOUND",
  "DOCTOR_PROFILE_PHOTO_NOT_FOUND",
  "OPERATOR_PROFILE_PHOTO_NOT_FOUND",
  "PROVIDER_PROFILE_NOT_FOUND",
  "PARTNER_PHOTO_NOT_FOUND",
]);

export type PartnerPhotoReader = (partnerId: number) => Promise<Blob>;

export interface PartnerPhotoSource {
  src: string | null;
  absent: boolean;
}

interface ResolvedPhoto {
  blob: Blob | null;
  absent: boolean;
}

interface CacheEntry {
  ready: Promise<ResolvedPhoto>;
  holders: number;
  ref: string | null;
}

const NO_SOURCE: PartnerPhotoSource = { src: null, absent: false };
const ABSENT: PartnerPhotoSource = { src: null, absent: true };

const CACHE = new Map<number, CacheEntry>();

async function resolveStoredPhoto(
  read: PartnerPhotoReader,
  partnerId: number,
): Promise<ResolvedPhoto> {
  try {
    return { blob: await read(partnerId), absent: false };
  } catch (err) {
    return {
      blob: null,
      absent: err instanceof ApiError && PHOTO_NOT_FOUND_CODES.has(err.code),
    };
  }
}

function acquire(
  partnerId: number,
  photoRef: string | null,
  read: PartnerPhotoReader,
): CacheEntry {
  const cached = CACHE.get(partnerId);
  if (cached !== undefined && cached.ref === photoRef) {
    cached.holders += 1;
    return cached;
  }
  const entry: CacheEntry = {
    ready: resolveStoredPhoto(read, partnerId),
    holders: 1,
    ref: photoRef,
  };
  CACHE.set(partnerId, entry);
  return entry;
}

function release(partnerId: number, entry: CacheEntry): void {
  entry.holders -= 1;
  if (entry.holders > 0) return;
  if (CACHE.get(partnerId) === entry) {
    CACHE.delete(partnerId);
  }
}

export function usePartnerPhotoSource(
  partnerId: number,
  photoRef: string | null,
  read: PartnerPhotoReader = fetchPartnerPhoto,
): PartnerPhotoSource {
  const [source, setSource] = useState<PartnerPhotoSource>(NO_SOURCE);
  const reader = useRef(read);
  reader.current = read;

  useEffect(() => {
    if (photoRef == null) {
      setSource(NO_SOURCE);
      return;
    }
    if (typeof URL.createObjectURL !== "function") {
      setSource(NO_SOURCE);
      return;
    }
    let live = true;
    let objectUrl: string | null = null;
    setSource(NO_SOURCE);
    const entry = acquire(partnerId, photoRef, reader.current);

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
      release(partnerId, entry);
    };
  }, [partnerId, photoRef]);

  return source;
}
