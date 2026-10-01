"use client";

// #615 AC 2: the identity band that heads the rebuilt profile page - a large
// avatar with the camera control opening the file picker where it sits, the
// doctor's name as the page heading, the clinic name beneath it, and a chip row
// carrying the verified tick and the declared specialty selection.
//
// Two decisions the band inherits rather than reinvents:
//
// - The picker is `PhotoCard`'s, lifted. Its `sr-only` file input, the `Button`
//   that clicks it, the ghost Remove, and the test ids the page suite already
//   reaches for all survive verbatim, because the resolution seam (a ref-keyed
//   module cache with owned object URLs) lives in the shared photo-source hook
//   and is exactly what a re-implementation loses.
// - The tick reads `profile.verified` and nothing else. Recomputing credential
//   validity in the client to decide what to tick is how a page grows a second
//   derivation site that disagrees with the backend's, and the disagreement is
//   the failure this product cannot have: "if the tick is gone, the card is gone"
//   (ADR-0011, blueprint §1.6). The verified band's credentials read the same
//   flag for the same reason.

import { useRef } from "react";
import { BadgeCheck, Camera } from "lucide-react";

import { ErrorBanner } from "@/components/layout/ErrorBanner";
import { Avatar } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { DoctorProfileView } from "@/lib/doctor/api";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { cn } from "@/lib/utils";
import type { SectionFailure } from "./ProfileSectionShell";

export interface ProfileIdentityBandProps {
  profile: DoctorProfileView;
  /**
   * The RESOLVED photo source from the shared hook, never the stored ref: the ref
   * is an opaque object key in the doctor's own namespace (ADR-0020) and means
   * nothing outside the authed transport that resolves it.
   */
  photoUrl: string | null;
  /** The backend answered this ref has no media behind it, so there is nothing to remove. */
  mediaAbsent: boolean;
  busy: boolean;
  failure: SectionFailure | null;
  onPick: (file: File) => void;
  onRemove: () => void;
  onDismissFailure: () => void;
}

export function ProfileIdentityBand({
  profile,
  photoUrl,
  mediaAbsent,
  busy,
  failure,
  onPick,
  onRemove,
  onDismissFailure,
}: ProfileIdentityBandProps) {
  const { lang } = useLang();
  const t = STRINGS[lang].doctorProfile;
  const inputRef = useRef<HTMLInputElement>(null);
  // A ref is a claim, the bytes are the fact, exactly as on the patient's photo
  // card: a set ref with nothing behind it offers Upload rather than a Remove
  // that cannot succeed. A failed read is not that, so a blip leaves the stored
  // photo still removable.
  const hasPhoto = profile.photo_ref != null && !mediaAbsent;
  // The heading is the doctor's own name. A doctor who has not typed one yet
  // falls back to the clinic, then to the platform's own name for the page, so
  // the band never renders an empty h1 - the one element on the page whose
  // absence would leave a screen with no title at all.
  const doctorName =
    profile.practice_name?.trim() || profile.clinic_name?.trim() || t.title;
  const specialties = profile.specialties;

  return (
    <Card data-testid="profile-identity">
      <CardContent className="flex flex-col gap-4 p-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-center gap-4">
          <Avatar
            photoRef={photoUrl}
            name={doctorName}
            className="h-20 w-20 shrink-0 bg-accent-soft text-2xl font-semibold text-accent-strong"
          />
          <div className="min-w-0">
            <h1 className="truncate text-lg font-semibold text-txt">
              {doctorName}
            </h1>
            {profile.clinic_name?.trim() && (
              <p
                className="truncate text-sm text-txt-muted"
                data-testid="profile-clinic"
              >
                {profile.clinic_name}
              </p>
            )}
          </div>
        </div>

        <div
          className="flex flex-wrap items-center gap-2"
          // The row is one group for assistive technology: three loose chips read
          // as unrelated facts, and the specialties are a selection that belongs
          // with the tick that qualifies the profile it describes.
          role="group"
          aria-label={t.identityChipsLabel}
        >
          {/* AC 2's "verified tick", read from the flag and nothing else. The tick
              is inside the chip and the verdict beside it, so the two cannot
              disagree - a tick without its word would be colour doing the talking,
              and the word without its tick would be a claim with no symbol the
              rest of this product uses for exactly that claim. When the flag is
              false neither appears, which is what "if the tick is gone, the card is
              gone" means on a doctor's own page (ADR-0011). */}
          <Badge
            variant={profile.verified ? "default" : "secondary"}
            data-testid="profile-verified"
            className={cn(
              "inline-flex items-center gap-1",
              profile.verified
                ? "bg-success-soft text-success-text"
                : "bg-accent-soft text-accent-strong",
            )}
          >
            {profile.verified && (
              <BadgeCheck aria-hidden="true" className="h-3.5 w-3.5" />
            )}
            {profile.verified ? t.verified : t.notVerified}
          </Badge>
          {specialties.length === 0 ? (
            <Badge
              variant="outline"
              className="border-hairline text-txt-muted"
              data-testid="profile-specialties-empty"
            >
              {t.noSpecialtiesYet}
            </Badge>
          ) : (
            specialties.map((specialty) => (
              <Badge
                key={specialty}
                variant="outline"
                className="border-hairline text-txt"
                data-testid="profile-specialty"
              >
                {specialty}
              </Badge>
            ))
          )}
        </div>
      </CardContent>

      {/* The picker sits in the band rather than in a card of its own: a camera
          control across the page from the face it replaces is the "settings
          dialog for my own face" problem this band exists to remove. The heading
          the old card gave this group is now its accessible name. */}
      <div
        className="border-t border-hairline px-4 py-3"
        role="group"
        aria-label={t.photoHeading}
        data-testid="profile-photo"
      >
        <p className="text-xs text-txt-muted">{t.photoHelp}</p>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <input
            ref={inputRef}
            type="file"
            accept="image/*"
            className="sr-only"
            data-testid="profile-photo-input"
            aria-label={hasPhoto ? t.photoReplace : t.photoUpload}
            onChange={(event) => {
              const file = event.target.files?.[0];
              // Reset the input so picking the same file twice re-fires change.
              event.target.value = "";
              if (file) onPick(file);
            }}
          />
          <Button
            type="button"
            size="sm"
            disabled={busy}
            loading={busy}
            data-testid="profile-photo-upload"
            onClick={() => inputRef.current?.click()}
          >
            {/* The camera glyph is what makes this a CAMERA control rather than a
                generic file button, which is AC 2's word. The text stays as the
                accessible name and carries the verb, so the icon is decorative -
                an icon with no text alternative would announce as "image". */}
            <Camera aria-hidden="true" className="h-4 w-4" />
            {hasPhoto ? t.photoReplace : t.photoUpload}
          </Button>
          {hasPhoto && (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={busy}
              onClick={onRemove}
              data-testid="profile-photo-remove"
            >
              {t.photoRemove}
            </Button>
          )}
        </div>

        {failure && (
          // No retry action: a failed upload has no stored file to re-send, so
          // the doctor picks again from the button above.
          <ErrorBanner
            message={t.photoFailed}
            traceId={failure.traceId}
            onDismiss={onDismissFailure}
          />
        )}
      </div>
    </Card>
  );
}
