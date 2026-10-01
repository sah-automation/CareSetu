"use client";

// #617: the About section card - the doctor's own words, the languages they
// consult in, the days they consult on, and their hours as prose (#610).
//
// #610 SPLIT the old free-text `availability` blob in two because the two halves
// want opposite things, and this card is where that split becomes visible:
//
//   - **The days are a closed selection of the week.** A doctor taps them out of
//     #602's seven-day list, so the field is filterable and cannot carry a
//     spelling nobody can match. A hand-typed day list was a doctor guessing at
//     our vocabulary.
//   - **The hours stay prose, with no structure at all.** No weekly template, no
//     per-day ranges, no slots. The platform has no booking system, so a shape
//     that invited one would be a promise the server cannot keep, and the help
//     text says so where the doctor will read it before typing.
//
// Everything else on this card is #616's discipline applied to a different write:
// its own route, its own buffer, its own attempt key, a refusal under the control
// the server named, and a failed write that adopts nothing (AC 3).

import { useEffect, useRef } from "react";

import { inputClassName, ProfileField } from "./ProfileField";
import { PROFILE_ANCHORS } from "./ProfileSectionIndex";
import {
  ProfileSectionShell,
  type SectionSaveResult,
} from "./ProfileSectionShell";
import { ProfileToggleField } from "./ProfileToggleField";
import {
  CONSULTING_DAYS,
  CONSULT_LANGUAGES,
  type ProfileConsultingDay,
  type ProfileConsultLanguage,
} from "./profileVocabularies";
import {
  ABOUT_LIMITS,
  aboutFromProfile,
  aboutUpdateFromFields,
  invalidAboutFields,
  type AboutFieldName,
  type AboutFields,
} from "./aboutCardFields";
import { useRefusedFieldErrors } from "./useRefusedFieldErrors";
import { useSectionEditBuffer } from "./useSectionEditBuffer";
import { useSectionValidation } from "./useSectionValidation";
import { ApiError } from "@/lib/api-errors";
import { updateDoctorProfileAbout } from "@/lib/doctor/api";
import { useDoctorProfile } from "@/lib/doctor/DoctorProfileContext";
import { idempotencyKey } from "@/lib/idempotency";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

const MAPPABLE_PATHS = [
  "about",
  "languages",
  "consulting_days",
  "consulting_hours",
] as const;

/**
 * One table per reason rather than a `switch` per function: a field's client rule
 * and its server rule are both "what do we tell this doctor about `about`", so
 * splitting them across two lookups meant reading one to find half of the other.
 * `languages` and `consulting_days` have no client entry because no client rule can
 * fire - both are taps out of a closed list - which is the honest shape of that
 * asymmetry.
 */
const FIELD_MESSAGES: Record<
  string,
  {
    client?: keyof typeof STRINGS.en.doctorProfile;
    server: keyof typeof STRINGS.en.doctorProfile;
  }
> = {
  about: { client: "aboutTooLong", server: "aboutTooLong" },
  consulting_hours: {
    client: "aboutTooLong",
    server: "aboutTooLong",
  },
  languages: { server: "languagesRejected" },
  consulting_days: { server: "consultingDaysRejected" },
};

export function AboutSectionCard() {
  const { lang } = useLang();
  const t = STRINGS[lang].doctorProfile;
  const { profile, adoptProfile } = useDoctorProfile();

  const buffer = useSectionEditBuffer(profile, aboutFromProfile);
  const fields = buffer.value;

  const validation = useSectionValidation<AboutFieldName, AboutFields>(
    fields,
    invalidAboutFields,
  );
  const refused = useRefusedFieldErrors(MAPPABLE_PATHS);

  const attemptKey = useRef<string | null>(null);
  const aboutRef = useRef<HTMLTextAreaElement | null>(null);
  const hoursRef = useRef<HTMLTextAreaElement | null>(null);

  const aboutFlag = isBad("about");
  const hoursFlag = isBad("consulting_hours");
  const languagesFlag = isBad("languages");
  const daysFlag = isBad("consulting_days");
  const summaryOpen =
    (validation.submitted && validation.invalid.length > 0) || refused.unmapped;

  function isBad(field: string) {
    return (
      refused.refused.has(field) ||
      validation.showsError(field as AboutFieldName)
    );
  }

  function messageFor(field: string, kind: "client" | "server") {
    const key = FIELD_MESSAGES[field]?.[kind];
    return key ? String(t[key]) : t.unmappedField;
  }

  function change(patch: Partial<AboutFields>) {
    buffer.change(patch);
    validation.changed(patch);
    refused.clear();
    attemptKey.current = null;
  }

  // Gated on `submitted`: a blur-time check must never pull focus back to the
  // textarea the doctor just left.
  useEffect(() => {
    if (!validation.submitted) return;
    if (hoursFlag) hoursRef.current?.focus();
    else if (aboutFlag) aboutRef.current?.focus();
  }, [validation.submitted, aboutFlag, hoursFlag]);

  useEffect(() => {
    if (!buffer.dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [buffer.dirty]);

  async function saveAbout(): Promise<SectionSaveResult> {
    if (fields == null) return { status: "declined" };

    const problems = validation.submit();
    refused.clear();
    if (problems.length > 0) return { status: "declined" };

    const attempt = attemptKey.current ?? idempotencyKey();
    attemptKey.current = attempt;
    try {
      const answer = await updateDoctorProfileAbout(
        aboutUpdateFromFields(fields),
        attempt,
      );
      attemptKey.current = null;
      adoptProfile(answer);
      validation.settled();
      return { status: "saved" };
    } catch (err) {
      refused.record(err);
      const traceId = err instanceof ApiError ? err.traceId : undefined;
      return { status: "failed", failure: { traceId } };
    }
  }

  if (fields == null) return null;

  return (
    <ProfileSectionShell
      title={t.aboutSectionTitle}
      help={t.aboutSectionHelp}
      anchorId={PROFILE_ANCHORS.about}
      testId="profile-about-card"
      save={{
        onSave: saveAbout,
        dirty: buffer.dirty,
        edits: buffer.edits,
        label: t.save,
        savedLabel: t.aboutSaved,
        unsavedLabel: t.unsavedChanges,
        failureMessage: t.aboutSaveFailed,
        buttonTestId: "profile-about-save",
        savedTestId: "profile-about-saved",
        unsavedTestId: "profile-about-unsaved",
      }}
    >
      {summaryOpen && (
        <div
          className="mb-3 rounded-md border border-danger-border bg-danger-soft px-3 py-2 text-sm text-danger"
          role="alert"
          aria-live="assertive"
          data-testid="profile-about-summary"
        >
          {validation.submitted && validation.invalid.length > 0 && (
            <p data-testid="profile-about-summary-count">
              {t.invalidSummary(validation.invalid.length)}
            </p>
          )}
          {refused.unmapped && (
            <p data-testid="profile-about-unmapped">{t.unmappedField}</p>
          )}
        </div>
      )}

      <div className="space-y-4">
        <ProfileField
          id="profile-about"
          label={t.aboutLabel}
          help={t.aboutHelp}
        >
          <textarea
            id="profile-about"
            ref={aboutRef}
            rows={5}
            maxLength={ABOUT_LIMITS.about}
            placeholder={t.aboutPlaceholder}
            value={fields.about}
            onChange={(event) => change({ about: event.target.value })}
            onBlur={() => validation.blur("about")}
            aria-invalid={aboutFlag}
            aria-describedby={aboutFlag ? "profile-about-error" : undefined}
            className={`${inputClassName} h-auto py-2 ${
              aboutFlag ? "border-danger" : ""
            }`}
            data-testid="profile-about"
          />
        </ProfileField>

        {/* The languages MOVED here from the address section, and that is #610's
            decision rather than a tidy-up: the free-text language box lived on the
            address card only because the whole-form write carried languages and
            #615 had nowhere else to put them. The About write is the one that
            takes them, so this is where the editor belongs, and the address card
            is left with the address. */}
        <div>
          <ProfileToggleField
            id="profile-about-languages"
            label={t.languagesLabel}
            help={t.languagesHelp}
            vocabulary={CONSULT_LANGUAGES}
            selected={fields.languages}
            labelFor={(value) => t.languageLabels[value]}
            onChange={(values: ProfileConsultLanguage[]) =>
              change({ languages: values })
            }
          />
          {languagesFlag && (
            <p
              className="mt-1 text-sm text-danger"
              role="alert"
              data-testid="profile-about-languages-error"
            >
              {messageFor("languages", "server")}
            </p>
          )}
        </div>

        <div>
          <ProfileToggleField
            id="profile-about-days"
            label={t.consultingDaysLabel}
            help={t.consultingDaysHelp}
            vocabulary={CONSULTING_DAYS}
            selected={fields.consulting_days}
            labelFor={(value) => t.dayLabels[value]}
            onChange={(values: ProfileConsultingDay[]) =>
              change({ consulting_days: values })
            }
          />
          {daysFlag && (
            <p
              className="mt-1 text-sm text-danger"
              role="alert"
              data-testid="profile-about-days-error"
            >
              {messageFor("consulting_days", "server")}
            </p>
          )}
        </div>

        <ProfileField
          id="profile-consulting-hours"
          label={t.consultingHoursLabel}
          help={t.consultingHoursHelp}
        >
          <textarea
            id="profile-consulting-hours"
            ref={hoursRef}
            rows={3}
            maxLength={ABOUT_LIMITS.consultingHours}
            placeholder={t.consultingHoursPlaceholder}
            value={fields.consulting_hours}
            onChange={(event) =>
              change({ consulting_hours: event.target.value })
            }
            onBlur={() => validation.blur("consulting_hours")}
            aria-invalid={hoursFlag}
            aria-describedby={
              hoursFlag ? "profile-consulting-hours-error" : undefined
            }
            className={`${inputClassName} h-auto py-2 ${
              hoursFlag ? "border-danger" : ""
            }`}
            data-testid="profile-consulting-hours"
          />
        </ProfileField>
      </div>

      {(aboutFlag || hoursFlag) && (
        <div className="mt-1 space-y-1">
          {aboutFlag && (
            <p
              id="profile-about-error"
              className="text-sm text-danger"
              role={refused.refused.has("about") ? undefined : "alert"}
              data-testid="profile-about-error"
            >
              {t.aboutTooLong}
            </p>
          )}
          {hoursFlag && (
            <p
              id="profile-consulting-hours-error"
              className="text-sm text-danger"
              role={
                refused.refused.has("consulting_hours") ? undefined : "alert"
              }
              data-testid="profile-consulting-hours-error"
            >
              {t.aboutTooLong}
            </p>
          )}
        </div>
      )}
    </ProfileSectionShell>
  );
}
