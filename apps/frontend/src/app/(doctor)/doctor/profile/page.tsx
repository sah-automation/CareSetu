"use client";

// PHASE-8.1 (#543): doctor console Profile page - the live destination behind
// the Profile nav entry that #541 left coming-soon. Renders and edits the private
// profile projection from #542: photo upload/preview/remove through the
// profile-media-backed private endpoints, practice details, experience,
// languages, about, the verified/credential status, and the notification toggles.
// Desktop and mobile, all copy bilingual en/hi (REQ-006).
//
// The directive is load-bearing: this module reads the shared profile source the
// route-group layout mounts above it, holds the page's own photo/upload state, and
// renders client children. Without it Next treats the module as a Server Component
// and refuses to build it, so the route 500s rather than rendering a page with no
// profile on it. It went missing in #615 and nothing noticed until #621, whose first
// assertion failed - the vitest suite renders this component in jsdom, where there is
// no Server/Client boundary to get wrong.

// #583: the page keeps no local copy of the projection. It reads the shared
// doctor profile source the (doctor) route-group layout mounts above it and the
// console chrome, and hands that source the backend's answer after every edit -
// which is what makes an upload, a removal or a rename land in the account menu
// at once instead of after a reload.

// #605: the page's editable fields are one `useSectionEditBuffer` per section
// and the saving section renders through the reusable `ProfileSectionShell`, so
// the in-flight-edit discipline that used to be written out inline here is stated
// once, in the buffer, and a future section inherits it instead of restating it.

// #615: the page is now a SHELL. The identity band heads it, the sticky
// anchor-chip index sits under the chrome, and every section is a component in
// `@/components/doctor/profile` rather than markup inlined here. What stays on
// this page is exactly what the brief scopes to it: the photo seam's transport,
// the partial-field `adoptRef` seam, and the fee's own save callback.
//
// #617 closed the gap #615 recorded. The declared band no longer owns a save at
// all: the four section writes (#608/#609/#610) have their clients, so each
// declared section carries its own card, its own buffer, its own route and its
// own save. That retires this page's whole-form request builder, its validation
// pass, the per-attempt key it owned and the `updateDoctorProfile` call that
// #611's route removal had left 405ing - so the page below no longer calls a
// route that does not exist.
//
// The declared band is a plain `<section>` and not a `ProfileSectionShell`
// because it now GROUPS four cards rather than holding fields of its own: a card
// inside a card is two nested surfaces reading as one, which is exactly what the
// design system's own flat-card rule refuses. It keeps the band's heading, its
// help sentence, its anchor and its test id, so the chip index and the
// declared-vs-verified distinction are untouched by the move.
//
// The page heading is the identity band's, not `PageHeader`'s: the band renders
// the doctor's own name as the h1, which is what a profile page is for. The
// `PageHeader` therefore survives for the two states with no name to show -
// loading and a failed read.
//
// #618: the page mounts the live preview. The public profile's renderer now lives
// in one presentational component, and the page renders it in a second column
// beside the form - sticky on a desktop, collapsible on a phone - fed by a draft
// provider the two cards with a publishable field write into as the doctor types.
// So what a patient will see is on the doctor's own screen, updating per
// keystroke, and it cannot be a second copy that drifts.
//
// The one provider for the whole page is why the cards need to know nothing about
// each other: `PublicProfileDraftProvider` is seeded from the SAME `profile` the
// bands read, and the practice and address cards fold their typed values into it.
// No card fetches anything new and no field is stored twice.
//
// CLOSING NOTES, per the brief's ask to record what a reviewer cannot see:
//
// 1. Changed a landed sibling's contract: `ProfileSectionShell` gained an
//    optional `anchorId` (#615), and this ticket added a shared
//    `useRefusedFieldErrors` hook that all four saving cards read, so #616's
//    address card's bespoke pin-refusal bookkeeping is now the same hook with a
//    one-path mappable set. Optional and additive; no existing caller changed
//    shape.
// 2. Two dictionary keys were renamed, both `#616`'s: `addressInvalidSummary` and
//    `addressUnmappedField` became `invalidSummary` and `unmappedField`. They
//    were the two sentences every saving card needs and three more cards need
//    them now; four locale-spelled copies of one sentence is the thing this
//    avoids. The address card and its suite were re-pointed, and the copy lost
//    the word "address" - it had to, since it now serves cards that have none.
// 3. `profileForm.ts` is GONE, along with the three `*Fields` placeholders and
//    `AddressFields`. Each was the editable shape of a write that no longer
//    exists, and every field they rendered is now on a card that can save it -
//    which is the whole reason they were placeholders.
// 4. Vocabulary that does not resolve yet: `locality` and `clinic name` are
//    glossary entries #622 introduces. No glossary entry is added here.
// 5. The language editor MOVED from the address section to the About card. It
//    was on the address card only because #615 had nowhere else to put a field
//    the whole-form write carried, and #610's About write is the one that takes
//    languages - so the editor now sits on the card that can save it.
// 6. #618 changed the page's LAYOUT, which no earlier note records: the two bands
//    and the fee card moved into the left cell of a two-column grid with the
//    preview in the right. `items-start` is deliberately absent - the preview is
//    sticky and needs the full height of its cell - and the preview's cell is
//    `order-first` so a phone shows it directly under the identity band.
// 7. #618 renamed the identity band's tick test id from `profile-verified` to
//    `profile-identity-verified`, because the preview puts the public renderer's
//    `profile-verified` on this same page and two components cannot share a test
//    id. The renderer kept its name: it predates this page and its own suite pins
//    it. The band's markup, copy and dictionary keys are untouched.
// 8. A landed test changed meaning, not strength: "never renders the service-area
//    vocabulary name" now excludes the preview from the word's absence, because
//    the public profile labels the declared locality "Service area" and the
//    preview's job is to say what the patient surface says. The value the test was
//    really guarding - the platform seed - is still asserted absent from the whole
//    page, and the preview is additionally asserted to show the locality beside
//    that label.
// 9. Two cards now require `PublicProfileDraftProvider` to render. That is the
//    cost of the seam: a card that could silently fail to publish would show a
//    preview that stopped updating, which is worse than a loud failure.

import { useEffect, useRef, useState } from "react";

import { AboutSectionCard } from "@/components/doctor/profile/AboutSectionCard";
import { AddressSectionCard } from "@/components/doctor/profile/AddressSectionCard";
import { ConsultationFeeCard } from "@/components/doctor/profile/ConsultationFeeCard";
import { NotificationSectionCard } from "@/components/doctor/profile/NotificationSectionCard";
import { PracticeSectionCard } from "@/components/doctor/profile/PracticeSectionCard";
import { ProfileCredentialList } from "@/components/doctor/profile/ProfileCredentialList";
import { ProfileIdentityBand } from "@/components/doctor/profile/ProfileIdentityBand";
import { ProfileLivePreview } from "@/components/doctor/profile/ProfileLivePreview";
import { PublicProfileDraftProvider } from "@/components/doctor/profile/PublicProfileDraftContext";
import {
  PROFILE_ANCHORS,
  ProfileSectionIndex,
} from "@/components/doctor/profile/ProfileSectionIndex";
import {
  ProfileSectionShell,
  type SectionFailure,
} from "@/components/doctor/profile/ProfileSectionShell";
import { ErrorBanner } from "@/components/layout/ErrorBanner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api-errors";
import {
  deleteDoctorProfilePhoto,
  fetchDoctorProfilePhoto,
  uploadDoctorProfilePhoto,
  type DoctorProfileView,
} from "@/lib/doctor/api";
import { useDoctorProfile } from "@/lib/doctor/DoctorProfileContext";
import { idempotencyKey } from "@/lib/idempotency";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { useProfilePhotoSource } from "@/lib/profile/useProfilePhotoSource";

function LoadingSkeleton() {
  return (
    <div className="space-y-3" data-testid="profile-skeleton">
      <div className="flex items-center gap-4 rounded-lg border border-hairline bg-surface p-4">
        <Skeleton className="h-20 w-20 rounded-full" />
        <div className="space-y-2">
          <Skeleton className="h-4 w-40" />
          <Skeleton className="h-3 w-24" />
        </div>
      </div>
      <div className="space-y-2 rounded-lg border border-hairline bg-surface p-4">
        <Skeleton className="h-4 w-32" />
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-9 w-full" />
      </div>
    </div>
  );
}

=======
const inputClassName =
  "h-9 w-full rounded-md border border-hairline bg-surface px-3 text-sm text-txt placeholder:text-txt-muted focus:border-accent-border focus:outline-none";
const labelClassName = "text-xs font-medium text-txt-muted";

interface FieldProps {
  id: string;
  label: string;
  help?: string;
  children: ReactNode;
}

function Field({ id, label, help, children }: FieldProps) {
  return (
    <label className="flex flex-col gap-1" htmlFor={id}>
      <span className={labelClassName}>{label}</span>
      {children}
      {help && <span className="text-xs text-txt-muted">{help}</span>}
    </label>
  );
}

interface PhotoCardProps {
  profile: DoctorProfileView;
  photoUrl: string | null;
  /** The backend answered this ref has no media behind it, so there is nothing to remove. */
  mediaAbsent: boolean;
  busy: boolean;
  failure: Failure | null;
  onPick: (file: File) => void;
  onRemove: () => void;
  onDismissFailure: () => void;
}

function PhotoCard({
  profile,
  photoUrl,
  mediaAbsent,
  busy,
  failure,
  onPick,
  onRemove,
  onDismissFailure,
}: PhotoCardProps) {
  const { lang } = useLang();
  const t = STRINGS[lang].doctorProfile;
  const inputRef = useRef<HTMLInputElement>(null);
  // A ref is a claim, the bytes are the fact, exactly as on the patient's photo
  // card: a set ref with nothing behind it offers Upload rather than a Remove
  // that cannot succeed. A failed read is not that, so a blip leaves the stored
  // photo still removable.
  const hasPhoto = profile.photo_ref != null && !mediaAbsent;

  return (
    <section
      className="rounded-lg border border-hairline bg-surface p-4"
      data-testid="profile-photo"
    >
      <h2 className="text-sm font-semibold text-txt">{t.photoHeading}</h2>
      <p className="mt-1 text-sm text-txt-muted">{t.photoHelp}</p>

      <div className="mt-3 flex flex-wrap items-center gap-4">
        <Avatar
          photoRef={photoUrl}
          name={profile.practice_name}
          className="h-16 w-16 bg-accent-soft text-lg font-semibold text-accent-strong"
        />
        <div className="flex flex-wrap items-center gap-2">
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
    </section>
  );
}

interface CredentialsCardProps {
  profile: DoctorProfileView;
}

function CredentialsCard({ profile }: CredentialsCardProps) {
  const { lang } = useLang();
  const t = STRINGS[lang].doctorProfile;

  return (
    <section
      className="rounded-lg border border-hairline bg-surface p-4"
      data-testid="profile-credentials"
    >
      <h2 className="text-sm font-semibold text-txt">{t.credentialsHeading}</h2>

      {profile.credentials.length === 0 ? (
        <p
          className="mt-2 text-sm text-txt-muted"
          data-testid="profile-credentials-empty"
        >
          {t.credentialsEmpty}
        </p>
      ) : (
        <ul className="mt-3 space-y-2">
          {profile.credentials.map(
            (credential: DoctorProfileCredential, index) => {
              const expiry = credentialExpiry(credential.expires_at, t, lang);
              // Two credentials can share a type, so the index keeps the keys
              // unique; the type alone would collide.
              return (
                <li
                  key={`${credential.credential_type}-${index}`}
                  data-testid="profile-credential"
                  className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-hairline px-3 py-2"
                >
                  <span className="text-sm text-txt">
                    {t.credentialType[
                      credential.credential_type as keyof typeof t.credentialType
                    ] ?? credential.credential_type}
                  </span>
                  <span className="flex flex-wrap items-center gap-2">
                    {expiry && (
                      <span
                        className="text-xs text-txt-muted"
                        data-testid="profile-credential-expiry"
                      >
                        {expiry}
                      </span>
                    )}
                    <span
                      data-testid="profile-credential-status"
                      className={cn(
                        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
                        credential.status === "verified"
                          ? "bg-success-soft text-success-text"
                          : "bg-accent-soft text-accent-strong",
                      )}
                    >
                      {t.credentialStatus[credential.status]}
                    </span>
                  </span>
                </li>
              );
            },
          )}
        </ul>
      )}

      <div className="mt-4 border-t border-hairline pt-3">
        <h3 className="text-sm font-semibold text-txt">
          {t.publicPreviewHeading}
        </h3>
        <p className="mt-1 text-sm text-txt-muted">{t.publicPreviewHelp}</p>
        <Link
          href={providerProfileHref(profile.partner_id)}
          data-testid="profile-public-preview"
          className="mt-2 inline-flex items-center rounded-md border border-hairline bg-surface px-3 py-1.5 text-xs font-medium text-txt-sub transition-colors hover:border-accent-border hover:bg-accent-soft hover:text-accent-strong"
        >
          {t.publicPreviewAction}
        </Link>
      </div>
    </section>
  );
}

interface DetailsFormProps {
  form: ProfileForm;
  invalid: ProfileField[];
  saving: boolean;
  saved: boolean;
  failure: Failure | null;
  onChange: (patch: Partial<ProfileForm>) => void;
  onToggle: (key: NotificationKey, value: boolean) => void;
  onSubmit: () => void;
  onDismissFailure: () => void;
}

function DetailsForm({
  form,
  invalid,
  saving,
  saved,
  failure,
  onChange,
  onToggle,
  onSubmit,
  onDismissFailure,
}: DetailsFormProps) {
  const { lang } = useLang();
  const t = STRINGS[lang].doctorProfile;
  const isInvalid = (field: ProfileField) => invalid.includes(field);
  const fieldClass = (field: ProfileField) =>
    cn(inputClassName, isInvalid(field) && "border-danger");

  return (
    <form
      className="rounded-lg border border-hairline bg-surface p-4"
      data-testid="profile-details-form"
      // The page owns its own validation pass and renders one message for the
      // offending fields, so the browser's constraint bubbles must not preempt
      // the submit (and silently swallow the attempt).
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <h2 className="text-sm font-semibold text-txt">{t.detailsHeading}</h2>

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <Field id="profile-practice-name" label={t.practiceNameLabel}>
          <input
            id="profile-practice-name"
            type="text"
            maxLength={LIMITS.practiceName}
            value={form.practice_name}
            onChange={(event) =>
              onChange({ practice_name: event.target.value })
            }
            aria-invalid={isInvalid("practice_name")}
            className={fieldClass("practice_name")}
            data-testid="profile-practice-name"
          />
        </Field>
        <Field id="profile-experience" label={t.experienceLabel}>
          <input
            id="profile-experience"
            type="number"
            inputMode="numeric"
            min={LIMITS.experienceYears.min}
            max={LIMITS.experienceYears.max}
            value={form.experience_years}
            onChange={(event) =>
              onChange({ experience_years: event.target.value })
            }
            aria-invalid={isInvalid("experience_years")}
            className={fieldClass("experience_years")}
            data-testid="profile-experience"
          />
        </Field>
      </div>

      <div className="mt-3 grid gap-3">
        <Field id="profile-address" label={t.addressLabel}>
          <textarea
            id="profile-address"
            maxLength={LIMITS.practiceAddress}
            value={form.practice_address}
            onChange={(event) =>
              onChange({ practice_address: event.target.value })
            }
            aria-invalid={isInvalid("practice_address")}
            className={cn(fieldClass("practice_address"), "h-20 py-2")}
            data-testid="profile-address"
          />
        </Field>

        <Field
          id="profile-latitude"
          label={t.latitudeLabel}
          help={t.coordinatesHelp}
        >
          <input
            id="profile-latitude"
            type="number"
            inputMode="decimal"
            step="any"
            min={LIMITS.latitude.min}
            max={LIMITS.latitude.max}
            value={form.practice_latitude}
            onChange={(event) =>
              onChange({ practice_latitude: event.target.value })
            }
            aria-invalid={isInvalid("practice_latitude")}
            className={fieldClass("practice_latitude")}
            data-testid="profile-latitude"
          />
        </Field>

        <Field id="profile-longitude" label={t.longitudeLabel}>
          <input
            id="profile-longitude"
            type="number"
            inputMode="decimal"
            step="any"
            min={LIMITS.longitude.min}
            max={LIMITS.longitude.max}
            value={form.practice_longitude}
            onChange={(event) =>
              onChange({ practice_longitude: event.target.value })
            }
            aria-invalid={isInvalid("practice_longitude")}
            className={fieldClass("practice_longitude")}
            data-testid="profile-longitude"
          />
        </Field>

        <Field
          id="profile-languages"
          label={t.languagesLabel}
          help={t.languagesHelp}
        >
          <input
            id="profile-languages"
            type="text"
            value={form.languages}
            onChange={(event) => onChange({ languages: event.target.value })}
            placeholder={t.languagesPlaceholder}
            aria-invalid={isInvalid("languages")}
            className={fieldClass("languages")}
            data-testid="profile-languages"
          />
        </Field>

        <Field id="profile-about" label={t.aboutLabel}>
          <textarea
            id="profile-about"
            maxLength={LIMITS.about}
            value={form.about}
            onChange={(event) => onChange({ about: event.target.value })}
            placeholder={t.aboutPlaceholder}
            aria-invalid={isInvalid("about")}
            className={cn(fieldClass("about"), "h-24 py-2")}
            data-testid="profile-about"
          />
        </Field>

        <Field id="profile-availability" label={t.availabilityLabel}>
          <textarea
            id="profile-availability"
            maxLength={LIMITS.availability}
            value={form.availability}
            onChange={(event) => onChange({ availability: event.target.value })}
            placeholder={t.availabilityPlaceholder}
            aria-invalid={isInvalid("availability")}
            className={cn(fieldClass("availability"), "h-20 py-2")}
            data-testid="profile-availability"
          />
        </Field>
      </div>

      <h2 className="mt-5 text-sm font-semibold text-txt">
        {t.notificationsHeading}
      </h2>
      <ul className="mt-2 space-y-2">
        {NOTIFICATION_KEYS.map((key) => (
          <li key={key}>
            <label
              htmlFor={`profile-notification-${key}`}
              className="flex min-h-11 items-center gap-2 text-sm text-txt"
            >
              <input
                id={`profile-notification-${key}`}
                type="checkbox"
                checked={form.notifications[key] === true}
                onChange={(event) => onToggle(key, event.target.checked)}
                data-testid={`profile-notification-${key}`}
              />
              {t.notificationLabels[key]}
            </label>
          </li>
        ))}
      </ul>

      <div className="mt-4 flex items-center gap-2">
        <Button
          type="submit"
          size="sm"
          disabled={saving}
          loading={saving}
          data-testid="profile-save"
        >
          {t.save}
        </Button>
        {saved && (
          <p className="text-sm text-success" data-testid="profile-saved">
            {t.saved}
          </p>
        )}
      </div>

      {failure && (
        <ErrorBanner
          message={t.saveFailed}
          traceId={failure.traceId}
          onRetry={onSubmit}
          onDismiss={onDismissFailure}
        />
      )}

      {invalid.length > 0 && (
        <p
          className="mt-2 text-sm text-danger"
          role="alert"
          data-testid="profile-invalid"
        >
          {t.invalidFields}
        </p>
      )}
    </form>
  );
}

interface FeeEditorProps {
  feePaise: number | null;
  onFeeSaved: (feePaise: number | null) => void;
}

function FeeEditor({ feePaise, onFeeSaved }: FeeEditorProps) {
  const { lang } = useLang();
  const t = STRINGS[lang].doctorProfile;

  const [feeInput, setFeeInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [invalid, setInvalid] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);
  // One idempotency key per attempt, so a retry of the same amount cannot be
  // written twice; a new amount mints a new one.
  const attemptKey = useRef<string | null>(null);

  function changeFeeInput(value: string) {
    setFeeInput(value);
    setSaved(false);
    setInvalid(false);
    setFailure(null);
    attemptKey.current = null;
  }

  async function handleSave(event: FormEvent) {
    event.preventDefault();
    await saveFee();
  }

  async function saveFee() {
    const rupees = Number(feeInput);
    if (!Number.isFinite(rupees) || rupees < 0) {
      setInvalid(true);
      return;
    }
    setSaving(true);
    setSaved(false);
    setInvalid(false);
    setFailure(null);
    const key = attemptKey.current ?? idempotencyKey();
    attemptKey.current = key;
    try {
      // The unchanged fee path: the same PATCH route the landing used, against
      // the same partner record. The reply is a partner view without the fee,
      // so the parent's local projection is the source of truth for the value.
      await updateConsultationFee(Math.round(rupees * 100), key);
      attemptKey.current = null;
      setSaved(true);
      onFeeSaved(Math.round(rupees * 100));
    } catch (err) {
      setFailure({
        traceId: err instanceof ApiError ? err.traceId : undefined,
      });
    } finally {
      setSaving(false);
    }
  }

  async function handleClear() {
    setSaving(true);
    setSaved(false);
    setInvalid(false);
    setFailure(null);
    const key = idempotencyKey();
    try {
      await updateConsultationFee(null, key);
      setFeeInput("");
      setSaved(true);
      onFeeSaved(null);
    } catch (err) {
      setFailure({
        traceId: err instanceof ApiError ? err.traceId : undefined,
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <form
      id="fee-editor"
      className="rounded-lg border border-hairline bg-surface p-4"
      data-testid="fee-editor"
      // The editor validates the amount itself so a bad entry is named in the
      // form instead of being swallowed by a native bubble.
      noValidate
      onSubmit={handleSave}
    >
      <h2 className="text-sm font-semibold text-txt">{t.feeHeading}</h2>
      <p className="mt-1 text-sm text-txt-muted">{t.feeHelp}</p>

      {feePaise !== null && (
        <p className="mt-2 text-sm text-txt" data-testid="fee-current">
          {formatFeePaise(feePaise)}
        </p>
      )}

      <div className="mt-3 flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1" htmlFor="profile-fee">
          <span className={labelClassName}>{t.feeFieldLabel}</span>
          <input
            id="profile-fee"
            type="number"
            inputMode="decimal"
            min="0"
            step="1"
            value={feeInput}
            onChange={(event) => changeFeeInput(event.target.value)}
            aria-invalid={invalid}
            placeholder={t.feeFieldPlaceholder}
            className="h-9 w-40 rounded-md border border-hairline bg-surface px-3 text-sm text-txt placeholder:text-txt-muted focus:border-accent-border focus:outline-none"
            data-testid="fee-input"
          />
        </label>
        <Button
          type="submit"
          size="sm"
          disabled={saving || feeInput === ""}
          loading={saving}
          data-testid="fee-save"
        >
          {t.saveFee}
        </Button>
        {feePaise !== null && (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            disabled={saving}
            onClick={handleClear}
            data-testid="fee-clear"
          >
            {t.clearFee}
          </Button>
        )}
      </div>

      {saved && (
        <p className="mt-2 text-sm text-success" data-testid="fee-message">
          {t.feeSaved}
        </p>
      )}
      {invalid && (
        <p
          className="mt-2 text-sm text-danger"
          role="alert"
          data-testid="fee-invalid"
        >
          {t.feeInvalid}
        </p>
      )}
      {failure && (
        <ErrorBanner
          message={t.feeSaveFailed}
          traceId={failure.traceId}
          onRetry={() => void saveFee()}
          onDismiss={() => setFailure(null)}
        />
      )}
    </form>
  );
}

>>>>>>> origin/main
export default function DoctorProfilePage() {
  const { lang } = useLang();
  const t = STRINGS[lang].doctorProfile;

  // #583: the shared source, not a page-private read. It answers before any
  // console page renders its contents, and the account menu above this page
  // reads the same projection - so the two can never drift.
  const { profile, status, errorTraceId, reload, adoptProfile } =
    useDoctorProfile();
  const [bannerOpen, setBannerOpen] = useState(false);

  const [photoBusy, setPhotoBusy] = useState(false);
  const [photoFailure, setPhotoFailure] = useState<SectionFailure | null>(null);

  const removeAttemptKey = useRef<string | null>(null);

  // The newest projection, mirrored out of the render so the partial edits below
  // merge onto it rather than onto whatever this render happened to close over.
  // Each of them awaits a request, and a practice-details save that lands in that
  // window carries a moved `practice_name` and a moved fee - merging the older
  // render's copy would put them straight back.
  const newestProfile = useRef<DoctorProfileView | null>(null);
  useEffect(() => {
    newestProfile.current = profile;
  }, [profile]);

  // The one partial edit the source cannot answer on its own: the backend's
  // upload and remove endpoints hand back a ref (or its absence) and nothing
  // else, so the page folds that one field into the projection it already holds
  // and hands the whole view back through the single adopt seam.
  function adoptRef<K extends keyof DoctorProfileView>(
    field: K,
    value: DoctorProfileView[K],
  ) {
    const current = newestProfile.current;
    if (current === null) return;
    adoptProfile({ ...current, [field]: value });
  }

  // The photo is a private profile-media key, never a public URL, so the shared
  // seam resolves it: the bytes come over the authed transport and this page
  // names the transport, not the resolution. Its ref came with the profile, so
  // nothing extra is fetched to resolve it.
  const { src: photoUrl, absent: mediaAbsent } = useProfilePhotoSource(
    profile?.photo_ref ?? null,
    fetchDoctorProfilePhoto,
  );

  function retryLoad() {
    setBannerOpen(false);
    reload();
  }

  // The read now lives in the shared source, so the page is told the read
  // failed rather than catching it. Dismissing sticks until the status changes
  // again, which is what makes a retry that fails twice show the banner twice.
  useEffect(() => {
    if (status === "error") setBannerOpen(true);
  }, [status]);

  async function uploadPhoto(file: File) {
    setPhotoBusy(true);
    setPhotoFailure(null);
    try {
      // A pick is its own attempt: there is no stored file to retry with, so
      // the key is minted per upload rather than reused.
      const { photo_ref } = await uploadDoctorProfilePhoto(
        file,
        idempotencyKey(),
      );
      // The new key re-runs the resolution, which revokes the old object URL and
      // streams the stored photo back - in the identity band's avatar and in the
      // console chrome at the same time, because they are one source now.
      adoptRef("photo_ref", photo_ref);
    } catch (err) {
      setPhotoFailure({
        traceId: err instanceof ApiError ? err.traceId : undefined,
      });
    } finally {
      setPhotoBusy(false);
    }
  }

  async function removePhoto() {
    setPhotoBusy(true);
    setPhotoFailure(null);
    try {
      await deleteDoctorProfilePhoto(
        removeAttemptKey.current ?? idempotencyKey(),
      );
      removeAttemptKey.current = null;
      // Cleared, not stale: the chrome stops showing a photo the doctor has just
      // declared should not be there.
      adoptRef("photo_ref", null);
    } catch (err) {
      setPhotoFailure({
        traceId: err instanceof ApiError ? err.traceId : undefined,
      });
    } finally {
      setPhotoBusy(false);
    }
  }

  function onFeeSaved(feePaise: number | null) {
    adoptRef("consultation_fee", feePaise);
  }

  const ready = status === "ready" && profile != null;
  // The chip labels are the target sections' own dictionary headings, so a chip
  // never names a section differently from the way the section names itself.
  //
  // The two bands keep separate chips rather than sharing one "details" target:
  // two bands, two anchors, two ids, and no chip pointing at both.
  //
  // #617 closed the gap #615 recorded here. The practice, about and notification
  // chips used to address field groups inside the declared band, and those groups
  // carried no heading of their own, so a reader who jumped to one landed correctly
  // and heard nothing announced. Each of the three is now a card with a heading of
  // its own - the card is what carries it - and all four declared cards live
  // inside the declared band, which is why the band is a section rather than a
  // fourth card.
  const anchors = [
    { id: PROFILE_ANCHORS.verified, label: t.verifiedBandTitle },
    { id: PROFILE_ANCHORS.declared, label: t.declaredBandTitle },
    { id: PROFILE_ANCHORS.practice, label: t.practiceSectionTitle },
    { id: PROFILE_ANCHORS.address, label: t.addressSectionTitle },
    { id: PROFILE_ANCHORS.about, label: t.aboutSectionTitle },
    { id: PROFILE_ANCHORS.notifications, label: t.notificationsHeading },
    { id: PROFILE_ANCHORS.fee, label: t.feeHeading },
  ];

  return (
    <>
      {/* Only the two states with no doctor name to show get a header of their
          own: the ready state below renders its own h1 in the identity band. */}
      {status === "loading" && (
        <PageHeader title={t.title} description={t.description} />
      )}

      {status === "error" && bannerOpen && (
        <>
          <PageHeader title={t.title} description={t.description} />
          <ErrorBanner
            message={t.loadFailed}
            traceId={errorTraceId}
            onRetry={retryLoad}
            onDismiss={() => setBannerOpen(false)}
          />
        </>
      )}

      {status === "loading" && <LoadingSkeleton />}

      {ready && (
        // #618: one provider for the page, and the reason the cards can publish
        // without knowing about each other. It is seeded from the SAME projection
        // the bands read, and the two cards that carry a field the public profile
        // shows fold their typed values into it on every keystroke.
        <PublicProfileDraftProvider profile={profile}>
          <div className="space-y-4">
            <ProfileIdentityBand
              profile={profile}
              photoUrl={photoUrl}
              mediaAbsent={mediaAbsent}
              busy={photoBusy}
              failure={photoFailure}
              onPick={(file) => void uploadPhoto(file)}
              onRemove={() => void removePhoto()}
              onDismissFailure={() => setPhotoFailure(null)}
            />

            <ProfileSectionIndex anchors={anchors} />

            {/* Two columns on a desktop: the form, and the profile it is about.
                The preview is `order-first` so on a phone it sits directly under
                the identity band - the doctor sees the effect of a keystroke before
                the field they are typing in scrolls away - while on a desktop the
                grid places it in the second column. `items-start` is deliberately
                absent: the preview is sticky, and it needs the full height of its
                grid cell to have anywhere to stick to. */}
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px] lg:gap-6">
              <div className="min-w-0 space-y-4">
                {/* The verified band: what the platform derived and checked.
                    Read-only, and its tick is the identity band's tick - one flag,
                    read twice - so the two bands cannot disagree about the same
                    doctor. A false flag renders no tick here at all, never a tick
                    beside a stale list. The preview beside it reads that same flag
                    for its own tick, so all three agree or none does. */}
                <ProfileSectionShell
                  title={t.verifiedBandTitle}
                  help={t.verifiedBandHelp}
                  anchorId={PROFILE_ANCHORS.verified}
                  testId="profile-verified-band"
                >
                  <ProfileCredentialList profile={profile} />
                </ProfileSectionShell>

                {/* The declared band: everything the doctor declared, and it says
                    so in words. It is a plain section, NOT a card, because it
                    groups the four saving cards below rather than holding fields of
                    its own - and a card inside a card is two nested surfaces
                    reading as one.

                    The heading and the sentence beneath it are what make it a band
                    at all, and they are the reason the declared-vs-verified
                    distinction is still visible: every card inside this section is
                    unchecked by CareSetu, which is exactly what `declaredBandHelp`
                    says - and the preview in the second column is the rendered
                    proof of it. */}
                <section
                  id={PROFILE_ANCHORS.declared}
                  data-testid="profile-declared-band"
                  className="space-y-4"
                  aria-labelledby="profile-declared-band-heading"
                >
                  <div className="rounded-lg border border-hairline bg-surface p-4">
                    <h2
                      id="profile-declared-band-heading"
                      className="text-sm font-semibold text-txt"
                    >
                      {t.declaredBandTitle}
                    </h2>
                    <p className="mt-1 text-xs text-txt-muted">
                      {t.declaredBandHelp}
                    </p>
                  </div>

                  {/* Four cards, four routes, four buffers. #616 built the first
                      of these; #617 built the other three and brought the address
                      card inside the band it belongs to, so the band's four declared
                      sections are together rather than split across the page. */}
                  <PracticeSectionCard />
                  <AddressSectionCard />
                  <AboutSectionCard />
                  <NotificationSectionCard />
                </section>

                <ConsultationFeeCard
                  feePaise={profile.consultation_fee}
                  onFeeSaved={onFeeSaved}
                />
              </div>

              <div className="order-first min-w-0 lg:order-none">
                <ProfileLivePreview />
              </div>
            </div>
          </div>
        </PublicProfileDraftProvider>
      )}
    </>
  );
}
