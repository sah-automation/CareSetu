"use client";

// #522/#523: the patient Profile & Settings route (blueprint §5.8). Completion
// meter + editable personal details (name, age, gender), language preference,
// emergency contact, and area - all pre-filling from the saved patient profile
// and the identity-keyed draft buffer. Save reuses the ProfileProvider's
// finishProfile (PUT /v1/me/profile, idempotent) with the established basics
// gate - incomplete basics block the write with a plain explanation - and
// success/error surface through the bilingual notice.

import { useState } from "react";

import { PageHeader } from "@/components/layout/PageHeader";
import { MeterBar } from "@/components/patient/profile/MeterBar";
import { ProfileSaveStatusNotice } from "@/components/patient/profile/SaveStatusNotice";
import { Button } from "@/components/ui/button";
import {
  STRINGS,
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

export default function ProfileSettingsPage() {
  const { lang, setLang } = useLang();
  const t: ProfileStrings = STRINGS[lang].profile;
  const { draft, saveStatus, updateDraft, finishProfile } = useProfile();

  // Field errors surface only after a blocked save attempt - never pre-nag.
  const [showErrors, setShowErrors] = useState(false);

  const patch = (partial: Partial<ProfileDraft>) => {
    updateDraft({ ...draft, ...partial });
  };

  const errors = step1Errors(draft);
  const pct = profileCompleteness(draft);

  const handleSave = () => {
    if (!basicsComplete(draft)) {
      setShowErrors(true);
      return;
    }
    // Basics complete - reuse the provider's idempotent finish path; the
    // bilingual notice is never silent while the write runs or fails.
    void finishProfile();
  };

  return (
    <>
      <PageHeader title={t.settings.title} description={t.settings.sub} />
      <ProfileSaveStatusNotice saveStatus={saveStatus} />

      <section
        aria-label={t.settings.title}
        data-testid="profile-settings"
        className="rounded-lg border border-hairline bg-surface p-5 shadow-card"
      >
        {/* Completion meter: reflects draft completeness, same primitive the
            wizard and Home nudges use. */}
        <div className="flex items-center gap-3">
          <MeterBar pct={pct} label={t.meterLabel} />
          <span
            data-testid="ps-meter-label"
            className="shrink-0 text-xs font-medium text-txt-muted"
          >
            {pct}%
          </span>
        </div>

        <div className="mt-5 flex flex-col gap-4" data-testid="ps-step-basics">
          <h2 className="text-lg font-semibold text-txt">
            {t.settings.basics}
          </h2>

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
                showErrors && errors.nameRequired ? "ps-error-name" : undefined
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
            toggle's store), draft.language is the profile's preferred_language
            written when Save runs. Mirroring the wizard, choosing flips the
            app locale immediately and records profile intent. */}
        <div className="mt-5 flex flex-col gap-4" data-testid="ps-step-lang">
          <h2 className="text-lg font-semibold text-txt">{t.langLabel}</h2>
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
                  translate with the surrounding locale. */}
              <option value="hi">हिंदी</option>
              <option value="en">English</option>
            </select>
          </div>
        </div>

        {/* Emergency contact - optional, unsettable on save (null payload). */}
        <div className="mt-5 flex flex-col gap-4" data-testid="ps-step-ec">
          <h2 className="text-lg font-semibold text-txt">{t.ec}</h2>
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
          <h2 className="text-lg font-semibold text-txt">{t.area}</h2>
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
      </section>
    </>
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
