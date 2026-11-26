"use client";

// FEAT-015 (operator console) / #862, #866, #868: the operator profile photo
// control. The host passes the current ref and is told when it moves; object
// URLs, streams and idempotency keys stay inside. A missing or unreadable photo
// degrades to the avatar fallback rather than an error surface, and every write
// answers the new ref so a rejected write can never look like a success.

import { useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Avatar } from "@/components/ui/avatar";
import { ApiError } from "@/lib/api-errors";
import { idempotencyKey } from "@/lib/idempotency";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import {
  deleteOperatorProfilePhoto,
  fetchOperatorProfilePhoto,
  uploadOperatorProfilePhoto,
} from "@/lib/operator/api";
import { useProfilePhotoSource } from "@/lib/profile/useProfilePhotoSource";

export interface OperatorProfilePhotoCardProps {
  photoRef: string | null;
  name: string;
  onPhotoRefChange: (ref: string | null) => void;
}

export function OperatorProfilePhotoCard({
  photoRef,
  name,
  onPhotoRefChange,
}: OperatorProfilePhotoCardProps) {
  const { lang } = useLang();
  const t = STRINGS[lang].operatorProfile;
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<{ traceId?: string } | null>(null);
  const removeAttemptKey = useRef<string | null>(null);

  const { src: photoUrl, absent: mediaAbsent } = useProfilePhotoSource(
    photoRef,
    fetchOperatorProfilePhoto,
  );

  async function uploadPhoto(file: File) {
    setBusy(true);
    setFailure(null);
    try {
      const updated = await uploadOperatorProfilePhoto(file, idempotencyKey());
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
    removeAttemptKey.current ??= idempotencyKey();
    try {
      await deleteOperatorProfilePhoto(removeAttemptKey.current);
      removeAttemptKey.current = null;
      onPhotoRefChange(null);
    } catch (err) {
      setFailure({
        traceId: err instanceof ApiError ? err.traceId : undefined,
      });
    } finally {
      setBusy(false);
    }
  }

  const hasPhoto = photoRef != null && !mediaAbsent;

  return (
    <div
      data-testid="operator-profile-photo-card"
      className="operator-profile-photo-card"
    >
      <p className="text-sm font-medium text-txt">{t.photoHeading}</p>
      <p className="mt-0.5 text-xs text-txt-muted">{t.photoHelp}</p>

      <div className="mt-3 flex flex-wrap items-center gap-4">
        <Avatar
          photoRef={photoUrl}
          name={name || t.tierOperator}
          data-testid="operator-profile-photo"
          className="h-16 w-16 bg-accent-soft text-lg font-semibold text-accent-strong"
        />
        <div className="flex flex-wrap items-center gap-2">
          <input
            ref={inputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            className="sr-only"
            tabIndex={-1}
            data-testid="operator-photo-input"
            aria-label={hasPhoto ? t.photoReplace : t.photoUpload}
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (file) void uploadPhoto(file);
            }}
          />
          <Button
            type="button"
            size="sm"
            disabled={busy}
            loading={busy}
            data-testid="operator-photo-upload"
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
              data-testid="operator-photo-remove"
            >
              {t.photoRemove}
            </Button>
          )}
        </div>
      </div>

      {failure && (
        <p
          role="alert"
          data-testid="operator-photo-failed"
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
