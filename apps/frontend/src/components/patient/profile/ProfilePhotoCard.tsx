"use client";

// #548: the patient profile photo control (Identity zone, backend #533).
// Deep by design: the host passes the current ref and is told when it moves -
// it never learns about object URLs, streams, or idempotency keys.
//
// The stored ref is private profile media (ADR-0020), never a public URL, so
// the preview streams the bytes over the authed transport and presents an
// object URL, revoked on teardown or replacement. A missing or unreadable photo
// degrades to the avatar fallback rather than an error surface - a broken
// image is worse than an initial.
//
// Upload and remove are committed writes in their own right, each answering the
// updated profile. That answer is the only source of the new ref: the card
// never invents one, so a rejected write can never look like a successful one.

import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Avatar } from "@/components/ui/avatar";
import { ApiError } from "@/lib/api-errors";
import { idempotencyKey } from "@/lib/idempotency";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import {
  deletePatientPhoto,
  fetchPatientPhoto,
  uploadPatientPhoto,
} from "@/lib/profile/api";

export interface ProfilePhotoCardProps {
  /** The stored profile-media ref, or null when no photo is set. */
  photoRef: string | null;
  /** Falls back to the name initial when no photo is previewable. */
  name: string;
  /** Called with the ref the photo endpoint stored, or null once removed. */
  onPhotoRefChange: (ref: string | null) => void;
}

/** The backend's answer when the ref has no media behind it. */
const PHOTO_NOT_FOUND_CODE = "PROFILE_PHOTO_NOT_FOUND";

export function ProfilePhotoCard({
  photoRef,
  name,
  onPhotoRefChange,
}: ProfilePhotoCardProps) {
  const { lang } = useLang();
  const t = STRINGS[lang].profileZones;
  const inputRef = useRef<HTMLInputElement>(null);
  const [photoUrl, setPhotoUrl] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<{ traceId?: string } | null>(null);
  // A removal is idempotent on the backend, so a failed one is safe to re-issue
  // with the same key; an upload cannot be (there is no stored file to re-send),
  // so its key is minted per pick instead of reused.
  const removeAttemptKey = useRef<string | null>(null);
  // A ref is a claim, the bytes are the fact. The profile row can hold a ref
  // with no media behind it: the completion wizard persists a bare file name as
  // a placeholder until a real upload lands (#548 review). Trusting the ref
  // alone would then offer "Remove" for a photo that was never stored, so the
  // fetch decides - but only a definite "not found" downgrades, never a
  // transport blip, which must not make a stored photo look absent.
  const [mediaAbsent, setMediaAbsent] = useState(false);
  const hasPhoto = photoRef != null && !mediaAbsent;

  useEffect(() => {
    if (photoRef == null) {
      setPhotoUrl(null);
      setMediaAbsent(false);
      return;
    }
    let cancelled = false;
    let objectUrl: string | null = null;
    setPhotoUrl(null);
    setMediaAbsent(false);
    void fetchPatientPhoto()
      .then((blob) => {
        if (cancelled) return;
        if (typeof URL.createObjectURL !== "function") return;
        objectUrl = URL.createObjectURL(blob);
        setPhotoUrl(objectUrl);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setPhotoUrl(null);
        if (err instanceof ApiError && err.code === PHOTO_NOT_FOUND_CODE) {
          setMediaAbsent(true);
        }
      });
    return () => {
      cancelled = true;
      if (objectUrl != null) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [photoRef]);

  async function uploadPhoto(file: File) {
    setBusy(true);
    setFailure(null);
    try {
      const updated = await uploadPatientPhoto(file, idempotencyKey());
      onPhotoRefChange(updated.photo_ref);
    } catch (err) {
      setFailure({
        traceId: err instanceof ApiError ? err.traceId : undefined,
      });
    } finally {
      setBusy(false);
    }
  }

  async function removePhoto() {
    setBusy(true);
    setFailure(null);
    // Mint the key before the call, not in the catch: a key stored only on
    // failure would be a *different* key from the one the request carried, so
    // the retry would look like a fresh removal instead of the same attempt.
    removeAttemptKey.current ??= idempotencyKey();
    try {
      const updated = await deletePatientPhoto(removeAttemptKey.current);
      removeAttemptKey.current = null;
      onPhotoRefChange(updated.photo_ref);
    } catch (err) {
      // Keep the key so a retry is deduplicated against the same attempt.
      setFailure({
        traceId: err instanceof ApiError ? err.traceId : undefined,
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div data-testid="ps-photo">
      <p className="text-sm font-medium text-txt">{t.photoHeading}</p>
      <p className="mt-0.5 text-xs text-txt-muted">{t.photoHelp}</p>

      <div className="mt-3 flex flex-wrap items-center gap-4">
        <Avatar
          photoRef={photoUrl}
          name={name}
          data-testid="ps-photo-preview"
          className="h-16 w-16 bg-accent-soft text-lg font-semibold text-accent-strong"
        />
        <div className="flex flex-wrap items-center gap-2">
          <input
            ref={inputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            className="sr-only"
            // The button below owns the affordance; keeping the input out of
            // the tab order means "Upload photo" is not announced twice. The
            // label stays because a file input with no accessible name is its
            // own axe violation.
            tabIndex={-1}
            data-testid="ps-photo-input"
            aria-label={hasPhoto ? t.photoReplace : t.photoUpload}
            onChange={(event) => {
              const file = event.target.files?.[0];
              // Reset the input so picking the same file twice re-fires change.
              event.target.value = "";
              if (file) void uploadPhoto(file);
            }}
          />
          <Button
            type="button"
            size="sm"
            disabled={busy}
            loading={busy}
            data-testid="ps-photo-upload"
            onClick={() => inputRef.current?.click()}
          >
            {hasPhoto ? t.photoReplace : t.photoUpload}
          </Button>
          {hasPhoto && (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={busy}
              onClick={() => void removePhoto()}
              data-testid="ps-photo-remove"
            >
              {t.photoRemove}
            </Button>
          )}
        </div>
      </div>

      {failure && (
        // No retry action: a failed upload has no stored file to re-send, so the
        // patient picks again from the button above. A failed removal is
        // idempotent, but the same pick-again affordance keeps one story.
        <p
          role="alert"
          data-testid="ps-photo-failed"
          className="mt-3 rounded-md border border-danger-border bg-danger-soft px-3 py-2 text-sm text-danger"
        >
          {t.photoFailed}
          {failure.traceId && (
            <span className="ml-1 font-mono text-xs">({failure.traceId})</span>
          )}
        </p>
      )}
    </div>
  );
}
