"use client";

// PHASE-8.1 (#543): doctor console Profile page - the live destination behind
// the Profile nav entry that #541 left coming-soon. Renders and edits the
// private profile projection from #542: photo upload/preview/remove through the
// profile-media-backed private endpoints, practice details, experience,
// languages, about, availability, the verified/credential status, and the
// notification toggles. The consultation-fee editor moved here off the landing
// - its save still runs the unchanged PATCH /v1/partner/consultation-fee path
// against the same partner record. The public directory entry stays a
// read-only preview link. Desktop and mobile, all copy bilingual en/hi
// (REQ-006).

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";

import { ErrorBanner } from "@/components/layout/ErrorBanner";
import { PageHeader } from "@/components/layout/PageHeader";
import { formatFeePaise } from "@/components/pick/DoctorPickCard";
import { Avatar } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api-errors";
import {
  deleteDoctorProfilePhoto,
  fetchDoctorProfile,
  fetchDoctorProfilePhoto,
  updateDoctorProfile,
  uploadDoctorProfilePhoto,
  type DoctorCredentialStatus,
  type DoctorProfileCredential,
  type DoctorProfileUpdate,
  type DoctorProfileView,
} from "@/lib/doctor/api";
import { providerProfileHref } from "@/lib/directory/links";
import { idempotencyKey } from "@/lib/idempotency";
import { STRINGS, type Dictionary } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { updateConsultationFee } from "@/lib/partner/api";
import { cn } from "@/lib/utils";

type LoadStatus = "loading" | "ready" | "error";

/**
 * A failed mutation, carrying the API trace id when the failure came from the
 * API so support can correlate it (ErrorBanner falls back to a client id).
 */
interface Failure {
  traceId?: string;
}

// The private PUT is a whole-form write, not a patch: the backend requires the
// practice address and coordinates on every call and bounds every field
// (doctor_profile_models.py). The form mirrors those bounds so an unusable save
// fails here, against a named field, instead of round-tripping into a generic
// 422. Keep this block in lockstep with the model: a bound that is not mirrored
// here is a bound the doctor only learns about from the server.
const LIMITS = {
  practiceName: 120,
  practiceAddress: 1000,
  about: 5000,
  availability: 1000,
  experienceYears: { min: 0, max: 100 },
  latitude: { min: -90, max: 90 },
  longitude: { min: -180, max: 180 },
  languages: 20,
  languageNameLength: 50,
} as const;

// The backend keeps notification_preferences as a dict capped at 20 entries with
// 50-character keys, so this page owns the canonical key vocabulary it renders as
// toggles. A key the server already holds that this list does not know is
// carried through untouched on save, so a save never silently drops a stored
// preference.
const NOTIFICATION_KEYS = [
  "new_consultations",
  "record_shared",
  "pre_summary_ready",
  "case_updates",
  "credential_status",
] as const;

type NotificationKey = (typeof NOTIFICATION_KEYS)[number];

const MAX_NOTIFICATION_ENTRIES = 20;
const MAX_NOTIFICATION_KEY_LENGTH = 50;

type ProfileField =
  | "practice_name"
  | "practice_address"
  | "practice_latitude"
  | "practice_longitude"
  | "experience_years"
  | "languages"
  | "about"
  | "availability";

// Every value stays a string while editing so a field can be cleared mid-edit;
// only the submit path converts to the typed request body.
interface ProfileForm {
  practice_name: string;
  practice_address: string;
  practice_latitude: string;
  practice_longitude: string;
  experience_years: string;
  languages: string;
  about: string;
  availability: string;
  notifications: Record<string, boolean>;
}

function optionalText(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

/** Parse the comma-separated languages editor into the backend list shape. */
function splitLanguages(value: string): string[] {
  const seen = new Set<string>();
  const languages: string[] = [];
  for (const part of value.split(",")) {
    const language = part.trim();
    if (language === "") continue;
    // The backend rejects duplicate language names (case-insensitive), so fold
    // them here rather than failing the doctor's save over their typing.
    const key = language.toLocaleLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    languages.push(language);
  }
  return languages;
}

function seedNotifications(
  stored: Record<string, boolean>,
): Record<string, boolean> {
  const seeded: Record<string, boolean> = {};
  for (const [key, value] of Object.entries(stored)) {
    // A key the validator would refuse to accept back is dropped: keeping it
    // would make every later save 422. Nothing else is ever dropped.
    if (key.length <= MAX_NOTIFICATION_KEY_LENGTH) seeded[key] = value;
  }
  for (const key of NOTIFICATION_KEYS) {
    if (key in seeded) continue;
    // A stored dict already at the cap keeps its entries; the toggle still
    // renders and a flip adds the key once there is room on a later save.
    if (Object.keys(seeded).length >= MAX_NOTIFICATION_ENTRIES) continue;
    // An absent key means the doctor never chose, so the toggle starts off.
    seeded[key] = false;
  }
  return seeded;
}

function formFromProfile(profile: DoctorProfileView): ProfileForm {
  return {
    practice_name: profile.practice_name ?? "",
    practice_address: profile.practice_address,
    practice_latitude: String(profile.practice_latitude),
    practice_longitude: String(profile.practice_longitude),
    experience_years:
      profile.experience_years == null ? "" : String(profile.experience_years),
    languages: profile.languages.join(", "),
    about: profile.about ?? "",
    availability: profile.availability ?? "",
    notifications: seedNotifications(profile.notification_preferences),
  };
}

function invalidFields(form: ProfileForm): ProfileField[] {
  const invalid: ProfileField[] = [];

  if (form.practice_name.trim().length > LIMITS.practiceName) {
    invalid.push("practice_name");
  }

  const address = form.practice_address.trim();
  if (address === "" || address.length > LIMITS.practiceAddress) {
    invalid.push("practice_address");
  }

  const latitude = Number(form.practice_latitude);
  if (
    form.practice_latitude.trim() === "" ||
    !Number.isFinite(latitude) ||
    latitude < LIMITS.latitude.min ||
    latitude > LIMITS.latitude.max
  ) {
    invalid.push("practice_latitude");
  }

  const longitude = Number(form.practice_longitude);
  if (
    form.practice_longitude.trim() === "" ||
    !Number.isFinite(longitude) ||
    longitude < LIMITS.longitude.min ||
    longitude > LIMITS.longitude.max
  ) {
    invalid.push("practice_longitude");
  }

  if (form.experience_years.trim() !== "") {
    const years = Number(form.experience_years);
    if (
      !Number.isInteger(years) ||
      years < LIMITS.experienceYears.min ||
      years > LIMITS.experienceYears.max
    ) {
      invalid.push("experience_years");
    }
  }

  // The validator bounds the list length and each name inside it.
  const languages = splitLanguages(form.languages);
  if (
    languages.length > LIMITS.languages ||
    languages.some((language) => language.length > LIMITS.languageNameLength)
  ) {
    invalid.push("languages");
  }

  if (form.about.trim().length > LIMITS.about) {
    invalid.push("about");
  }

  if (form.availability.trim().length > LIMITS.availability) {
    invalid.push("availability");
  }

  return invalid;
}

function updateFromForm(form: ProfileForm): DoctorProfileUpdate {
  return {
    practice_name: optionalText(form.practice_name),
    practice_address: form.practice_address.trim(),
    practice_latitude: Number(form.practice_latitude),
    practice_longitude: Number(form.practice_longitude),
    experience_years:
      form.experience_years.trim() === ""
        ? null
        : Number(form.experience_years),
    languages: splitLanguages(form.languages),
    about: optionalText(form.about),
    availability: optionalText(form.availability),
    notification_preferences: form.notifications,
  };
}

function credentialExpiry(
  expiresAt: string | null,
  t: Dictionary["doctorProfile"],
  lang: "en" | "hi",
): string | null {
  if (expiresAt == null) return null;
  const date = new Date(expiresAt);
  if (Number.isNaN(date.getTime())) return null;
  return t.credentialExpires(
    date.toLocaleDateString(lang === "hi" ? "hi-IN" : "en-IN", {
      day: "numeric",
      month: "short",
      year: "numeric",
    }),
  );
}

function LoadingSkeleton() {
  return (
    <div className="space-y-3" data-testid="profile-skeleton">
      <div className="flex items-center gap-4 rounded-lg border border-hairline bg-surface p-4">
        <Skeleton className="h-16 w-16 rounded-full" />
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
  busy: boolean;
  failure: Failure | null;
  onPick: (file: File) => void;
  onRemove: () => void;
  onDismissFailure: () => void;
}

function PhotoCard({
  profile,
  photoUrl,
  busy,
  failure,
  onPick,
  onRemove,
  onDismissFailure,
}: PhotoCardProps) {
  const { lang } = useLang();
  const t = STRINGS[lang].doctorProfile;
  const inputRef = useRef<HTMLInputElement>(null);
  const hasPhoto = profile.photo_ref != null;

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

export default function DoctorProfilePage() {
  const { lang } = useLang();
  const t = STRINGS[lang].doctorProfile;

  const [profile, setProfile] = useState<DoctorProfileView | null>(null);
  const [form, setForm] = useState<ProfileForm | null>(null);
  const [loadStatus, setLoadStatus] = useState<LoadStatus>("loading");
  const [errorTraceId, setErrorTraceId] = useState<string | undefined>();
  const [bannerOpen, setBannerOpen] = useState(false);

  const [photoUrl, setPhotoUrl] = useState<string | null>(null);
  const [photoBusy, setPhotoBusy] = useState(false);
  const [photoFailure, setPhotoFailure] = useState<Failure | null>(null);

  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveFailure, setSaveFailure] = useState<Failure | null>(null);
  const [invalid, setInvalid] = useState<ProfileField[]>([]);
  // One idempotency key per user attempt: a retry of the same attempt reuses it
  // (so a lost response cannot write twice), and an edit starts a new attempt.
  const saveAttemptKey = useRef<string | null>(null);
  const removeAttemptKey = useRef<string | null>(null);

  const load = useCallback(() => {
    setLoadStatus("loading");
    setBannerOpen(false);
    fetchDoctorProfile()
      .then((view) => {
        setProfile(view);
        setForm(formFromProfile(view));
        setLoadStatus("ready");
      })
      .catch((err: unknown) => {
        setErrorTraceId(err instanceof ApiError ? err.traceId : undefined);
        setLoadStatus("error");
        setBannerOpen(true);
      });
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // The photo is a private profile-media key, never a public URL: stream the
  // bytes over the authed transport and present them as an object URL, the
  // same shape the consent-gated patient photo uses (#540). A missing or
  // unreadable photo degrades to the avatar fallback rather than an error
  // surface, and the object URL is revoked on teardown or replacement.
  useEffect(() => {
    if (profile?.photo_ref == null) {
      setPhotoUrl(null);
      return;
    }
    let cancelled = false;
    let objectUrl: string | null = null;
    setPhotoUrl(null);
    void fetchDoctorProfilePhoto()
      .then((blob) => {
        if (cancelled) return;
        if (typeof URL.createObjectURL !== "function") return;
        objectUrl = URL.createObjectURL(blob);
        setPhotoUrl(objectUrl);
      })
      .catch(() => {
        if (cancelled) return;
        setPhotoUrl(null);
      });
    return () => {
      cancelled = true;
      if (objectUrl != null) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [profile?.photo_ref]);

  function changeForm(patch: Partial<ProfileForm>) {
    setForm((current) => (current ? { ...current, ...patch } : current));
    setSaved(false);
    setSaveFailure(null);
    saveAttemptKey.current = null;
  }

  function toggleNotification(key: NotificationKey, value: boolean) {
    setForm((current) =>
      current
        ? {
            ...current,
            notifications: { ...current.notifications, [key]: value },
          }
        : current,
    );
    setSaved(false);
    setSaveFailure(null);
    saveAttemptKey.current = null;
  }

  async function saveProfile() {
    if (form == null) return;
    const problems = invalidFields(form);
    setInvalid(problems);
    if (problems.length > 0) return;
    setSaving(true);
    setSaved(false);
    setSaveFailure(null);
    const attemptKey = saveAttemptKey.current ?? idempotencyKey();
    saveAttemptKey.current = attemptKey;
    try {
      const view = await updateDoctorProfile(updateFromForm(form), attemptKey);
      saveAttemptKey.current = null;
      setProfile(view);
      setForm(formFromProfile(view));
      setSaved(true);
    } catch (err) {
      setSaveFailure({
        traceId: err instanceof ApiError ? err.traceId : undefined,
      });
    } finally {
      setSaving(false);
    }
  }

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
      // The new key re-runs the preview effect, which revokes the old object
      // URL and streams the stored photo back.
      setProfile((current) => (current ? { ...current, photo_ref } : current));
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
      setProfile((current) =>
        current ? { ...current, photo_ref: null } : current,
      );
    } catch (err) {
      setPhotoFailure({
        traceId: err instanceof ApiError ? err.traceId : undefined,
      });
    } finally {
      setPhotoBusy(false);
    }
  }

  function onFeeSaved(feePaise: number | null) {
    setProfile((current) =>
      current ? { ...current, consultation_fee: feePaise } : current,
    );
  }

  const ready = loadStatus === "ready" && profile != null && form != null;

  return (
    <>
      <PageHeader title={t.title} description={t.description} />

      {loadStatus === "error" && bannerOpen && (
        <ErrorBanner
          message={t.loadFailed}
          traceId={errorTraceId}
          onRetry={load}
          onDismiss={() => setBannerOpen(false)}
        />
      )}

      {loadStatus === "loading" && <LoadingSkeleton />}

      {ready && (
        <div className="space-y-4">
          <section
            className="rounded-lg border border-hairline bg-surface p-4"
            data-testid="profile-identity"
          >
            <h2 className="text-sm font-semibold text-txt">
              {t.identityHeading}
            </h2>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <span className="text-xs text-txt-muted">{t.specialtyLabel}</span>
              <span
                className="text-sm text-txt"
                data-testid="profile-specialty"
              >
                {profile.specialty ?? "-"}
              </span>
              <span
                data-testid="profile-verified"
                className={cn(
                  "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
                  profile.verified
                    ? "bg-success-soft text-success-text"
                    : "bg-accent-soft text-accent-strong",
                )}
              >
                {profile.verified ? t.verified : t.notVerified}
              </span>
            </div>
            {/* The area is the directory's own locality label for the saved
                address: server-derived, so it is shown, not edited. */}
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <span className="text-xs text-txt-muted">{t.areaLabel}</span>
              <span className="text-sm text-txt" data-testid="profile-area">
                {profile.area ?? "-"}
              </span>
            </div>
          </section>

          <PhotoCard
            profile={profile}
            photoUrl={photoUrl}
            busy={photoBusy}
            failure={photoFailure}
            onPick={(file) => void uploadPhoto(file)}
            onRemove={() => void removePhoto()}
            onDismissFailure={() => setPhotoFailure(null)}
          />

          <CredentialsCard profile={profile} />

          <DetailsForm
            form={form}
            invalid={invalid}
            saving={saving}
            saved={saved}
            failure={saveFailure}
            onChange={changeForm}
            onToggle={toggleNotification}
            onSubmit={() => void saveProfile()}
            onDismissFailure={() => setSaveFailure(null)}
          />

          <FeeEditor
            feePaise={profile.consultation_fee}
            onFeeSaved={onFeeSaved}
          />
        </div>
      )}
    </>
  );
}
