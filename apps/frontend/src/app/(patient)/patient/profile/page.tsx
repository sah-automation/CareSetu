"use client";

// #548: the patient Profile page reorganized into three professional zones
// (US-24/US-25). Identity holds the editable personal details plus the photo
// control (upload/preview/remove against the private photo endpoint, #533);
// HealthBackground is a placeholder zone #549 fills; Settings holds notification
// preferences, the default language, consent-grant management, and the data
// export/delete leads.
//
// The save flow is unchanged and still the provider's: pre-filling from the
// saved server profile and the identity-keyed draft buffer, the same
// basics-complete gate that blocks the write with a plain explanation, and the
// same idempotent finishProfile (PUT /v1/me/profile). Only the presentation is
// new - the reorganization must not change what a save writes.
//
// The photo is a second, separate surface: it commits on its own endpoint, so
// the card reports the ref the backend stored and the provider adopts it
// (syncPhotoRef). That keeps the draft's photo field tracking the stored ref,
// or a later identity save would PUT a stale ref and detach the photo.

import { useState, type ReactNode } from "react";

import { PageHeader } from "@/components/layout/PageHeader";
import { ConsentGrantsPanel } from "@/components/patient/profile/ConsentGrantsPanel";
import { MeterBar } from "@/components/patient/profile/MeterBar";
import { ProfilePhotoCard } from "@/components/patient/profile/ProfilePhotoCard";
import { ProfileSaveStatusNotice } from "@/components/patient/profile/SaveStatusNotice";
import { Button } from "@/components/ui/button";
import {
  STRINGS,
  SUPPORTED_LOCALES,
  type Lang,
  type ProfileStrings,
} from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { useProfile } from "@/lib/profile/ProfileContext";
import {
  basicsComplete,
  profileCompleteness,
  step1Errors,
  type GenderId,
  type ProfileDraft,
} from "@/lib/profile/profileState";

const labelClass = "text-sm font-medium text-txt";

const inputClass =
  "mt-1 block h-9 w-full rounded-md border border-input bg-background px-3 text-sm text-txt shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring";

/** Notification preference rows Settings will offer once they can persist. */
const NOTIFICATION_KEYS = [
  "appointment_reminders",
  "prescription_updates",
  "report_ready",
  "care_messages",
] as const;

export default function ProfileSettingsPage() {
  const { lang, setLang } = useLang();
  const t: ProfileStrings = STRINGS[lang].profile;
  const z = STRINGS[lang].profileZones;
  const { draft, saveStatus, updateDraft, finishProfile, syncPhotoRef } =
    useProfile();

  // Field errors surface only after a blocked save attempt - never pre-nag.
  const [showErrors, setShowErrors] = useState(false);

  const patch = (partial: Partial<ProfileDraft>) => {
    updateDraft({ ...draft, ...partial });
  };

  const errors = step1Errors(draft);
  // Page-scoped meter: counts only the fields this page can edit (basics +
  // area + emergency). The wizard's chronic-interest toggles are not
  // collectable here, so the full-draft meter would leave a fully edited
  // profile permanently under 100% with nothing left to fill on this surface
  // (spec #520 story 22). The wizard/Home meters keep the full scope. The
  // photo is no longer excluded: it is collectable here now (#548).
  const pct = profileCompleteness(draft, "profile-settings");

  const handleSave = () => {
    if (!basicsComplete(draft)) {
      setShowErrors(true);
      return;
    }
    // Basics complete - reuse the provider's idempotent finish path; the
    // bilingual notice is never silent while the write runs or fails.
    void finishProfile();
  };

  const languageName =
    SUPPORTED_LOCALES.find((locale) => locale.code === draft.language)
      ?.nativeName ?? draft.language;

  return (
    <>
      <PageHeader title={t.settings.title} description={t.settings.sub} />
      <ProfileSaveStatusNotice saveStatus={saveStatus} />

      <div data-testid="profile-settings" className="flex flex-col gap-5">
        {/* ---------------------------------------------------------------
            Zone 1 - Identity: who the patient is and how they look.
        ----------------------------------------------------------------*/}
        <Zone
          id="ps-zone-identity"
          heading={z.identityHeading}
          sub={z.identitySub}
        >
          <ProfilePhotoCard
            photoRef={draft.photoFileName === "" ? null : draft.photoFileName}
            name={draft.name}
            onPhotoRefChange={syncPhotoRef}
          />

          {/* Completion meter: reflects only the fields this page edits, so
              "what is left to fill" is always fillable in place (#520 story
              22); the wizard/Home meters keep the full-draft scope. */}
          <div className="mt-5 flex items-center gap-3">
            <MeterBar pct={pct} label={t.meterLabel} />
            <span
              data-testid="ps-meter-label"
              className="shrink-0 text-xs font-medium text-txt-muted"
            >
              {pct}%
            </span>
          </div>

          <div
            className="mt-5 flex flex-col gap-4"
            data-testid="ps-step-basics"
          >
            <h3 className="text-sm font-semibold text-txt">
              {t.settings.basics}
            </h3>

            <div>
              <label htmlFor="ps-fullname" className={labelClass}>
                {t.name}
              </label>
              <input
                id="ps-fullname"
                data-testid="ps-fullname"
                className={inputClass}
                value={draft.name}
                onChange={(e) => patch({ name: e.target.value })}
                autoComplete="name"
                aria-describedby={
                  showErrors && errors.nameRequired
                    ? "ps-error-name"
                    : undefined
                }
              />
              {showErrors && errors.nameRequired && (
                <FieldError testId="ps-error-name">
                  {t.errors.nameRequired}
                </FieldError>
              )}
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label htmlFor="ps-age" className={labelClass}>
                  {t.age}
                </label>
                <input
                  id="ps-age"
                  data-testid="ps-age"
                  type="text"
                  inputMode="numeric"
                  placeholder={t.agePlaceholder}
                  className={inputClass}
                  value={draft.age}
                  onChange={(e) => patch({ age: e.target.value })}
                  aria-describedby={
                    showErrors && (errors.ageRequired || errors.ageInvalid)
                      ? "ps-error-age"
                      : undefined
                  }
                />
                {showErrors && errors.ageRequired && (
                  <FieldError testId="ps-error-age">
                    {t.errors.ageRequired}
                  </FieldError>
                )}
                {showErrors && !errors.ageRequired && errors.ageInvalid && (
                  <FieldError testId="ps-error-age">
                    {t.errors.ageInvalid}
                  </FieldError>
                )}
              </div>
              <div>
                <label htmlFor="ps-gender" className={labelClass}>
                  {t.gender}
                </label>
                <select
                  id="ps-gender"
                  data-testid="ps-gender"
                  className={inputClass}
                  value={draft.gender}
                  onChange={(e) =>
                    patch({ gender: e.target.value as GenderId | "" })
                  }
                  aria-describedby={
                    showErrors && errors.genderRequired
                      ? "ps-error-gender"
                      : undefined
                  }
                >
                  <option value="">{t.genderPlaceholder}</option>
                  <option value="female">{t.genders.female}</option>
                  <option value="male">{t.genders.male}</option>
                  <option value="other">{t.genders.other}</option>
                </select>
                {showErrors && errors.genderRequired && (
                  <FieldError testId="ps-error-gender">
                    {t.errors.genderRequired}
                  </FieldError>
                )}
              </div>
            </div>
          </div>

          {/* Language preference: mirrors the wizard's D1 field. Two separate
              stores - LangContext is the live client-held UI locale (the header
              toggle's store), draft.language is the profile's
              preferred_language written when Save runs. Mirroring the wizard,
              choosing flips the app locale immediately and records profile
              intent. */}
          <div className="mt-5 flex flex-col gap-4" data-testid="ps-step-lang">
            <h3 className="text-sm font-semibold text-txt">{t.langLabel}</h3>
            <div>
              <label htmlFor="ps-lang" className="sr-only">
                {t.langLabel}
              </label>
              <select
                id="ps-lang"
                data-testid="ps-lang"
                className={inputClass}
                value={draft.language}
                onChange={(e) => {
                  const next = e.target.value as Lang;
                  patch({ language: next });
                  setLang(next);
                }}
              >
                {/* Native names by convention: a language's name does not
                    translate with the surrounding locale; the list itself is
                    the single i18n source (SUPPORTED_LOCALES). */}
                {SUPPORTED_LOCALES.map((locale) => (
                  <option key={locale.code} value={locale.code}>
                    {locale.nativeName}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Emergency contact - optional, unsettable on save (null payload). */}
          <div className="mt-5 flex flex-col gap-4" data-testid="ps-step-ec">
            <h3 className="text-sm font-semibold text-txt">{t.ec}</h3>
            <div>
              <label htmlFor="ps-ec" className="sr-only">
                {t.ec}
              </label>
              <input
                id="ps-ec"
                data-testid="ps-ec"
                type="tel"
                className={inputClass}
                placeholder={t.ecPlaceholder}
                value={draft.emergencyContact}
                onChange={(e) => patch({ emergencyContact: e.target.value })}
                autoComplete="tel"
              />
            </div>
          </div>

          {/* Area - optional, but the delivery gate's requirement (§5.9). */}
          <div className="mt-5 flex flex-col gap-4" data-testid="ps-step-area">
            <h3 className="text-sm font-semibold text-txt">{t.area}</h3>
            <div>
              <label htmlFor="ps-area" className="sr-only">
                {t.area}
              </label>
              <input
                id="ps-area"
                data-testid="ps-area"
                className={inputClass}
                placeholder={t.areaPlaceholder}
                value={draft.area}
                onChange={(e) => patch({ area: e.target.value })}
                autoComplete="street-address"
              />
            </div>
          </div>

          {showErrors && !basicsComplete(draft) && (
            <p
              role="alert"
              data-testid="ps-save-blocked"
              className="mt-5 flex items-start gap-2 rounded-md border border-danger-border bg-danger-soft px-3 py-2 text-sm text-danger"
            >
              {t.settings.blocked}
            </p>
          )}

          <div className="mt-5 flex justify-end">
            <Button
              data-testid="ps-save"
              onClick={handleSave}
              loading={saveStatus === "saving"}
            >
              {t.settings.save}
            </Button>
          </div>
        </Zone>

        {/* ---------------------------------------------------------------
            Zone 2 - Health background: placeholder until #549 lands. The
            zone is present and named now so the page's shape does not change
            again when the content arrives.
        ----------------------------------------------------------------*/}
        <Zone id="ps-zone-health" heading={z.healthHeading}>
          <p
            data-testid="ps-health-pending"
            className="mt-3 text-sm text-txt-muted"
          >
            {z.healthPending}
          </p>
        </Zone>

        {/* ---------------------------------------------------------------
            Zone 3 - Settings: preferences, language, consent, and the data
            rights leads.
        ----------------------------------------------------------------*/}
        <Zone id="ps-zone-settings" heading={z.settingsHeading}>
          {/* Notification preferences. Marked coming soon and rendered
              disabled: the patient profile row models no notification
              preferences (only the doctor partner profile does), so a live
              toggle here would look like it saved and change nothing. The
              rows are shown so the eventual preference set is visible, and
              every one is inert until it can persist. */}
          <div className="mt-4" data-testid="ps-settings-notifications">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-sm font-medium text-txt">
                {z.notificationsHeading}
              </p>
              <SoonBadge label={z.notificationsSoon} />
            </div>
            <p className="mt-0.5 text-xs text-txt-muted">
              {z.notificationsHelp}
            </p>
            <ul className="mt-2 flex flex-col gap-1">
              {NOTIFICATION_KEYS.map((key) => (
                <li key={key}>
                  <label
                    htmlFor={`ps-notification-${key}`}
                    className="flex min-h-11 items-center gap-2 text-sm text-txt-muted"
                  >
                    <input
                      id={`ps-notification-${key}`}
                      type="checkbox"
                      disabled
                      data-testid={`ps-notification-${key}`}
                    />
                    {z.notificationLabels[key]}
                  </label>
                </li>
              ))}
            </ul>
          </div>

          {/* Default language: the language the record is written in. Shown as
              the current value rather than a second control - the editable
              select lives in Identity, and two bound controls for one profile
              field would drift from each other. */}
          <div className="mt-5" data-testid="ps-settings-language">
            <p className="text-sm font-medium text-txt">{z.languageHeading}</p>
            <p
              data-testid="ps-settings-language-value"
              className="mt-0.5 text-sm text-txt"
            >
              {languageName}
            </p>
            <p className="mt-0.5 text-xs text-txt-muted">{z.languageHelp}</p>
          </div>

          <div className="mt-5 border-t border-hairline pt-5">
            <ConsentGrantsPanel />
          </div>

          {/* Data export / delete: rights the patient has, capabilities the
              product does not have yet. Copy-only and explicitly marked, so
              the lead is findable without a button that would do nothing. */}
          <div
            className="mt-5 border-t border-hairline pt-5"
            data-testid="ps-settings-data"
          >
            <p className="text-sm font-medium text-txt">{z.dataHeading}</p>
            <ul className="mt-2 flex flex-col gap-2">
              <li
                data-testid="ps-data-export"
                className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-hairline bg-surface px-3 py-2"
              >
                <div className="min-w-0">
                  <p className="text-sm text-txt">{z.dataExport}</p>
                  <p className="text-xs text-txt-muted">{z.dataExportHelp}</p>
                </div>
                <SoonBadge label={z.dataSoon} />
              </li>
              <li
                data-testid="ps-data-delete"
                className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-hairline bg-surface px-3 py-2"
              >
                <div className="min-w-0">
                  <p className="text-sm text-txt">{z.dataDelete}</p>
                  <p className="text-xs text-txt-muted">{z.dataDeleteHelp}</p>
                </div>
                <SoonBadge label={z.dataSoon} />
              </li>
            </ul>
          </div>
        </Zone>
      </div>
    </>
  );
}

/**
 * One zone of the page. The heading is the zone's accessible name (so a
 * screen-reader user can jump between zones), and the body is whatever the
 * zone holds - fields, a control, or placeholder copy.
 */
function Zone({
  id,
  heading,
  sub,
  children,
}: {
  id: string;
  heading: string;
  sub?: string;
  children: ReactNode;
}) {
  const headingId = `${id}-heading`;
  return (
    <section
      aria-labelledby={headingId}
      data-testid={id}
      className="rounded-lg border border-hairline bg-surface p-5 shadow-card"
    >
      <h2 id={headingId} className="text-base font-semibold text-txt">
        {heading}
      </h2>
      {sub && <p className="mt-0.5 text-xs text-txt-muted">{sub}</p>}
      {children}
    </section>
  );
}

/** Marks a control the product cannot honour yet, so it is never a dead tap. */
function SoonBadge({ label }: { label: string }) {
  return (
    <span
      data-testid="ps-soon-badge"
      className="shrink-0 rounded-full bg-hairline-soft px-2 py-0.5 text-xs font-medium text-txt-muted"
    >
      {label}
    </span>
  );
}

function FieldError({
  testId,
  children,
}: {
  testId: string;
  children: string;
}) {
  return (
    <p
      id={testId}
      role="alert"
      data-testid={testId}
      className="mt-1 text-xs font-medium text-danger"
    >
      {children}
    </p>
  );
}
