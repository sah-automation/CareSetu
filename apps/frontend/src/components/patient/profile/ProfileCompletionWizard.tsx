"use client";

// PHASE-2.6 T13 (#204): the bilingual first-login profile-completion wizard
// (blueprint §5.9, finalized PROTO-PHASE-2.6 view profile-completion.html is
// the binding visual/copy spec). Three steps: required basics (name, age,
// gender, language asked explicitly per spec #191 D1), skippable chronic-
// interest toggles, skippable photo/area/emergency contact. Step 1 blocks
// completion until basics validate; the optional steps are skippable with
// zero friction and never nag with modals.
//
// The component is fully controlled (draft + onDraftChange) so host surfaces
// can embed it - the inline gating presentation passes initialStep to open
// directly on the exact missing step (§5.9: gating explains itself at the
// action moment).
//
// INTEGRATION POINT (later phase): finishing persists nothing server-side -
// the draft lives client-side only (lib/profile/profileState, gap G5). Hosts
// receive onFinish and keep routing/local behavior their own.

import { useState, type ReactNode } from "react";
import { Check } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { Lang, ProfileStrings } from "@/lib/i18n/dictionaries";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { MeterBar } from "./MeterBar";
import {
  profileCompleteness,
  step1Errors,
  type GenderId,
  type ProfileDraft,
} from "@/lib/profile/profileState";
import { cn } from "@/lib/utils";

export interface ProfileCompletionWizardProps {
  draft: ProfileDraft;
  onDraftChange: (next: ProfileDraft) => void;
  /** Called when the wizard finishes on step 3. */
  onFinish?: () => void;
  /** Step to open on; defaults to 1. Inline gating opens on the gate step. */
  initialStep?: 1 | 2 | 3;
}

const labelClass = "text-sm font-medium text-txt";

export function ProfileCompletionWizard({
  draft,
  onDraftChange,
  onFinish,
  initialStep = 1,
}: ProfileCompletionWizardProps) {
  const { lang, setLang } = useLang();
  const t: ProfileStrings = STRINGS[lang].profile;

  const [step, setStep] = useState<1 | 2 | 3>(initialStep);
  // Field errors surface only once Continue was attempted - never pre-nag.
  const [showErrors, setShowErrors] = useState(false);

  const patch = (partial: Partial<ProfileDraft>) =>
    onDraftChange({ ...draft, ...partial });

  const errors = step1Errors(draft);
  const errorCount =
    Number(errors.nameRequired) +
    Number(errors.ageRequired || errors.ageInvalid) +
    Number(errors.genderRequired);

  const pct = profileCompleteness(draft);
  const isLast = step === 3;

  const goNext = () => {
    if (step === 1 && errorCount > 0) {
      setShowErrors(true);
      return;
    }
    if (isLast) {
      onFinish?.();
      return;
    }
    setStep(step === 1 ? 2 : 3);
  };

  return (
    <section
      aria-labelledby="pc-title"
      data-testid="profile-wizard"
      className="rounded-lg border border-hairline bg-surface p-5 shadow-card"
    >
      <div className="flex items-start justify-between gap-3">
        <h2 id="pc-title" className="text-lg font-semibold text-txt">
          {t.title}
        </h2>
      </div>
      <p className="mt-1 text-sm text-txt-sub">{t.sub}</p>

      {/* Completion meter: reflects draft completeness, not step position. */}
      <div className="mt-4 flex items-center gap-3">
        <MeterBar pct={pct} label={t.meterLabel} />
        <span
          data-testid="pc-meter-label"
          className="shrink-0 text-xs font-medium text-txt-muted"
        >
          {pct}%
        </span>
      </div>

      <ol className="mt-4 flex gap-2" data-testid="pc-stepper">
        {t.steps.map((label, index) => {
          const n = index + 1;
          return (
            <li
              key={n}
              aria-current={n === step ? "step" : undefined}
              className={cn(
                "flex-1 rounded-full border px-2 py-1 text-center text-xs font-medium",
                n < step
                  ? "border-success-soft bg-success-soft text-success-text"
                  : n === step
                    ? "border-primary/30 bg-primary/10 text-txt"
                    : "border-hairline text-txt-muted",
              )}
            >
              {n < step ? (
                <Check aria-hidden className="inline h-3 w-3" />
              ) : null}{" "}
              {label}
            </li>
          );
        })}
      </ol>

      <div className="mt-5">
        {step === 1 && (
          <div className="flex flex-col gap-4" data-testid="pc-step-1">
            <h3 className="text-base font-semibold text-txt">{t.s1}</h3>

            <div>
              <label htmlFor="pc-fullname" className={labelClass}>
                {t.name}
              </label>
              <input
                id="pc-fullname"
                data-testid="pc-fullname"
                className={cn(inputClass)}
                value={draft.name}
                onChange={(e) => patch({ name: e.target.value })}
                autoComplete="name"
                aria-describedby={
                  showErrors && errors.nameRequired
                    ? "pc-error-name"
                    : undefined
                }
              />
              {showErrors && errors.nameRequired && (
                <FieldError testId="pc-error-name">
                  {t.errors.nameRequired}
                </FieldError>
              )}
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label htmlFor="pc-age" className={labelClass}>
                  {t.age}
                </label>
                <input
                  id="pc-age"
                  data-testid="pc-age"
                  type="text"
                  inputMode="numeric"
                  placeholder={t.agePlaceholder}
                  className={inputClass}
                  value={draft.age}
                  onChange={(e) => patch({ age: e.target.value })}
                  aria-describedby={
                    showErrors && (errors.ageRequired || errors.ageInvalid)
                      ? "pc-error-age"
                      : undefined
                  }
                />
                {showErrors && errors.ageRequired && (
                  <FieldError testId="pc-error-age">
                    {t.errors.ageRequired}
                  </FieldError>
                )}
                {showErrors && !errors.ageRequired && errors.ageInvalid && (
                  <FieldError testId="pc-error-age">
                    {t.errors.ageInvalid}
                  </FieldError>
                )}
              </div>
              <div>
                <label htmlFor="pc-gender" className={labelClass}>
                  {t.gender}
                </label>
                <select
                  id="pc-gender"
                  data-testid="pc-gender"
                  className={inputClass}
                  value={draft.gender}
                  onChange={(e) =>
                    patch({ gender: e.target.value as GenderId | "" })
                  }
                  aria-describedby={
                    showErrors && errors.genderRequired
                      ? "pc-error-gender"
                      : undefined
                  }
                >
                  <option value="">{t.genderPlaceholder}</option>
                  <option value="female">{t.genders.female}</option>
                  <option value="male">{t.genders.male}</option>
                  <option value="other">{t.genders.other}</option>
                </select>
                {showErrors && errors.genderRequired && (
                  <FieldError testId="pc-error-gender">
                    {t.errors.genderRequired}
                  </FieldError>
                )}
              </div>
            </div>

            <div>
              <label htmlFor="pc-lang" className={labelClass}>
                {t.langLabel}
              </label>
              <select
                id="pc-lang"
                data-testid="pc-lang"
                className={inputClass}
                value={draft.language}
                onChange={(e) => {
                  const next = e.target.value as Lang;
                  // D1: language is asked explicitly here; choosing it flips
                  // the whole app locale immediately and records profile
                  // intent in the draft.
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
        )}

        {step === 2 && (
          <div className="flex flex-col gap-3" data-testid="pc-step-2">
            <h3 className="text-base font-semibold text-txt">{t.s2}</h3>
            <p className="text-sm text-txt-sub">{t.s2sub}</p>

            <ToggleTile
              testId="pc-bp"
              checked={draft.trackBp}
              label={t.bp}
              onToggle={() => patch({ trackBp: !draft.trackBp })}
            />
            <ToggleTile
              testId="pc-sugar"
              checked={draft.trackSugar}
              label={t.sugar}
              onToggle={() => patch({ trackSugar: !draft.trackSugar })}
            />
          </div>
        )}

        {step === 3 && (
          <div className="flex flex-col gap-4" data-testid="pc-step-3">
            <h3 className="text-base font-semibold text-txt">{t.s3}</h3>

            <div>
              <label htmlFor="pc-photo" className={labelClass}>
                {t.photo}
              </label>
              <input
                id="pc-photo"
                data-testid="pc-photo"
                type="file"
                accept="image/*"
                className="mt-1 block w-full text-sm text-txt-sub file:mr-3 file:rounded-md file:border-0 file:bg-secondary file:px-3 file:py-1.5 file:text-sm file:font-medium hover:file:bg-secondary/80"
                onChange={(e) =>
                  patch({
                    // Name only this phase - no upload exists yet
                    // (integration point for the later profile backend).
                    photoFileName: e.target.files?.[0]?.name ?? "",
                  })
                }
              />
            </div>

            <div>
              <label htmlFor="pc-area" className={labelClass}>
                {t.area}
              </label>
              <input
                id="pc-area"
                data-testid="pc-area"
                className={inputClass}
                placeholder={t.areaPlaceholder}
                value={draft.area}
                onChange={(e) => patch({ area: e.target.value })}
                autoComplete="street-address"
              />
            </div>

            <div>
              <label htmlFor="pc-ec" className={labelClass}>
                {t.ec}
              </label>
              <input
                id="pc-ec"
                data-testid="pc-ec"
                type="tel"
                className={inputClass}
                placeholder={t.ecPlaceholder}
                value={draft.emergencyContact}
                onChange={(e) => patch({ emergencyContact: e.target.value })}
                autoComplete="tel"
              />
            </div>
          </div>
        )}
      </div>

      <hr className="my-5 border-hairline" />

      <div className="flex items-center justify-between gap-3">
        {/* Skip exists only where something can actually be skipped: hidden
            on required step 1. On the optional steps it advances without
            touching anything - on step 3 that is the same as finishing. */}
        {step !== 1 ? (
          <Button variant="ghost" data-testid="pc-skip" onClick={goNext}>
            {t.skip}
          </Button>
        ) : (
          <span />
        )}
        <Button data-testid="pc-next" onClick={goNext}>
          {isLast ? t.finish : t.continueCta}
        </Button>
      </div>
    </section>
  );
}

const inputClass =
  "mt-1 block h-9 w-full rounded-md border border-input bg-background px-3 text-sm text-txt shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring";

function FieldError({
  testId,
  children,
}: {
  testId: string;
  children: ReactNode;
}) {
  return (
    <p
      role="alert"
      data-testid={testId}
      className="mt-1 text-xs font-medium text-danger"
    >
      {children}
    </p>
  );
}

function ToggleTile({
  testId,
  checked,
  label,
  onToggle,
}: {
  testId: string;
  checked: boolean;
  label: string;
  onToggle: () => void;
}) {
  return (
    <label className="flex cursor-pointer items-center justify-between rounded-md border border-hairline px-4 py-3 hover:bg-accent-soft/50">
      <span className="text-sm font-medium text-txt">{label}</span>
      <input
        type="checkbox"
        data-testid={testId}
        checked={checked}
        onChange={onToggle}
        className="h-5 w-5 accent-primary"
      />
    </label>
  );
}
