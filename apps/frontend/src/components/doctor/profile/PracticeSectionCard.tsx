"use client";

// #617: the Practice section card - who the doctor is and what kinds of care they
// offer, on its own route, its own buffer and its own save (#608).
//
// Four decisions in here are this card's, and three of them are about what it must
// NOT do:
//
//   1. **The specialties are a toggle group over the domain's closed list**, not a
//      text box and not a comma-separated string. #602 owns the list and refuses a
//      value outside it, and before #610 the only way a doctor could reach one was
//      to type a specialty they had to guess the spelling of. The chips are the
//      vocabulary made visible (`ProfileToggleField`).
//   2. **A rejected write adopts nothing.** Not the answer seam, not the dirty
//      flag, not the shared source, and not the attempt key - the retry is the
//      same attempt and must reuse its key. Every other section's unsaved buffer
//      keeps its own edits because of this, and so does this one (AC 3).
//   3. **A refusal lands under the control the server named.** #608's handler puts
//      the refused field's wire name in `details.errors[].path`, and that path is
//      the only thing that can map a 422 onto an input. A path this card cannot
//      map lands in the form summary instead, never on a guessed neighbour.
//   4. **The unsaved-changes guard is the `beforeunload` event**, registered and
//      removed with this card's dirty flag - the same first navigation guard
//      #616 added, repeated per saving card because a browser prompt is a
//      page-level event and there is one page.

import { useEffect, useRef } from "react";

import { fieldClassName, ProfileField } from "./ProfileField";
import { PROFILE_ANCHORS } from "./ProfileSectionIndex";
import {
  ProfileSectionShell,
  type SectionSaveResult,
} from "./ProfileSectionShell";
import { ProfileToggleField } from "./ProfileToggleField";
import { SPECIALTIES, type ProfileSpecialty } from "./profileVocabularies";
import {
  invalidPracticeFields,
  practiceFromProfile,
  practiceUpdateFromFields,
  PRACTICE_LIMITS,
  type PracticeFieldName,
  type PracticeFields,
} from "./practiceCardFields";
import { useRefusedFieldErrors } from "./useRefusedFieldErrors";
import { useSectionEditBuffer } from "./useSectionEditBuffer";
import { useSectionValidation } from "./useSectionValidation";
import { ApiError } from "@/lib/api-errors";
import { useDoctorProfile } from "@/lib/doctor/DoctorProfileContext";
import { updateDoctorProfilePractice } from "@/lib/doctor/api";
import { idempotencyKey } from "@/lib/idempotency";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

/**
 * The wire names this card can put a message under. A constant list rather than a
 * derived one, so adding a field to the slice without adding it here is a name in
 * the summary rather than a silent no-op.
 */
const MAPPABLE_PATHS = [
  "full_name",
  "clinic_name",
  "specialties",
  "experience_years",
] as const;

/**
 * One table per reason, rather than a `switch` per function: a field's client rule
 * and its server rule are both "what do we tell this doctor about `full_name`", and
 * splitting them across two `switch`es meant reading one to find half of the other.
 * A `specialties` refusal has no client rule because no client rule can fire - the
 * selection is a tap out of a closed list - so it appears in one table and not the
 * other, which is the honest shape of the asymmetry.
 */
const FIELD_MESSAGES: Record<
  string,
  {
    client?: keyof typeof STRINGS.en.doctorProfile;
    server: keyof typeof STRINGS.en.doctorProfile;
  }
> = {
  full_name: { client: "practiceNameRequired", server: "practiceNameRequired" },
  clinic_name: {
    client: "practiceClinicNameTooLong",
    server: "practiceClinicNameTooLong",
  },
  experience_years: {
    client: "practiceExperienceInvalid",
    server: "practiceExperienceInvalid",
  },
  specialties: { server: "practiceSpecialtiesRejected" },
};

export function PracticeSectionCard() {
  const { lang } = useLang();
  const t = STRINGS[lang].doctorProfile;
  // The same shared answer object every other surface reads, which is what makes
  // the buffer's identity guard correct.
  const { profile, adoptProfile } = useDoctorProfile();

  const buffer = useSectionEditBuffer(profile, practiceFromProfile);
  const fields = buffer.value;

  const validation = useSectionValidation<PracticeFieldName, PracticeFields>(
    fields,
    invalidPracticeFields,
  );
  const refused = useRefusedFieldErrors(MAPPABLE_PATHS);

  // One idempotency key per user attempt (api-standards §5): a retry of the same
  // attempt reuses it, and an edit mints a new one.
  const attemptKey = useRef<string | null>(null);
  const firstRef = useRef<HTMLInputElement | null>(null);
  const experienceRef = useRef<HTMLInputElement | null>(null);

  const nameFlag = isBad("full_name");
  const clinicFlag = isBad("clinic_name");
  const experienceFlag = isBad("experience_years");
  const specialtiesFlag = isBad("specialties");
  const summaryOpen =
    (validation.submitted && validation.invalid.length > 0) || refused.unmapped;

  /** True when the message under this field has something to say. */
  function isBad(field: string) {
    return (
      refused.refused.has(field) ||
      validation.showsError(field as PracticeFieldName)
    );
  }

  function messageFor(field: string, kind: "client" | "server") {
    const entry = FIELD_MESSAGES[field];
    const key = entry?.[kind];
    return key ? String(t[key]) : t.unmappedField;
  }

  function change(patch: Partial<PracticeFields>) {
    buffer.change(patch);
    validation.changed(patch);
    refused.clear();
    attemptKey.current = null;
  }

  function changeSpecialties(values: ProfileSpecialty[]) {
    change({ specialties: values });
  }

  // §9.4: a failed submit takes focus to the offending control. Only the text
  // inputs can hold a focus, so a refusal naming the toggle group takes the
  // selection's own first chip rather than the nearest input - which is the nearest
  // thing that is actually on screen above it. Gated on `submitted`, because a
  // blur-time check must never pull focus back to the field being left.
  useEffect(() => {
    if (!validation.submitted) return;
    if (experienceFlag) experienceRef.current?.focus();
    else if (nameFlag) firstRef.current?.focus();
  }, [validation.submitted, nameFlag, experienceFlag]);

  useEffect(() => {
    if (!buffer.dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [buffer.dirty]);

  async function savePractice(): Promise<SectionSaveResult> {
    if (fields == null) return { status: "declined" };

    if (validation.submit().length > 0) {
      refused.clear();
      return { status: "declined" };
    }
    refused.clear();

    const attempt = attemptKey.current ?? idempotencyKey();
    attemptKey.current = attempt;
    try {
      const answer = await updateDoctorProfilePractice(
        practiceUpdateFromFields(fields),
        attempt,
      );
      attemptKey.current = null;
      // The reply does NOT clear the dirty flag: it is just another answer, so a
      // doctor who kept typing across the save must not lose those keystrokes.
      adoptProfile(answer);
      validation.settled();
      return { status: "saved" };
    } catch (err) {
      // Adopts nothing and clears nothing except the refusal it is about to show.
      refused.record(err);
      const traceId = err instanceof ApiError ? err.traceId : undefined;
      return { status: "failed", failure: { traceId } };
    }
  }

  if (fields == null) return null;

  return (
    <ProfileSectionShell
      title={t.practiceSectionTitle}
      help={t.practiceSectionHelp}
      anchorId={PROFILE_ANCHORS.practice}
      testId="profile-practice-card"
      save={{
        onSave: savePractice,
        dirty: buffer.dirty,
        edits: buffer.edits,
        label: t.save,
        savedLabel: t.practiceSaved,
        unsavedLabel: t.unsavedChanges,
        failureMessage: t.practiceSaveFailed,
        buttonTestId: "profile-practice-save",
        savedTestId: "profile-practice-saved",
        unsavedTestId: "profile-practice-unsaved",
      }}
    >
      {summaryOpen && (
        <div
          className="mb-3 rounded-md border border-danger-border bg-danger-soft px-3 py-2 text-sm text-danger"
          role="alert"
          aria-live="assertive"
          data-testid="profile-practice-summary"
        >
          {validation.submitted && validation.invalid.length > 0 && (
            <p data-testid="profile-practice-summary-count">
              {t.invalidSummary(validation.invalid.length)}
            </p>
          )}
          {refused.unmapped && (
            <p data-testid="profile-practice-unmapped">{t.unmappedField}</p>
          )}
        </div>
      )}

      <div className="space-y-4">
        <ProfileField
          id="profile-practice-name"
          label={t.practiceFullNameLabel}
          help={t.practiceFullNameHelp}
        >
          <input
            id="profile-practice-name"
            ref={firstRef}
            type="text"
            maxLength={PRACTICE_LIMITS.fullName}
            value={fields.full_name}
            onChange={(event) => change({ full_name: event.target.value })}
            onBlur={() => validation.blur("full_name")}
            aria-invalid={nameFlag}
            aria-describedby={
              nameFlag ? "profile-practice-name-error" : undefined
            }
            className={fieldClassName(nameFlag)}
            data-testid="profile-practice-name"
          />
        </ProfileField>

        <ProfileField
          id="profile-practice-clinic"
          label={t.practiceClinicNameLabel}
          help={t.practiceClinicNameHelp}
        >
          <input
            id="profile-practice-clinic"
            type="text"
            maxLength={PRACTICE_LIMITS.clinicName}
            value={fields.clinic_name}
            onChange={(event) => change({ clinic_name: event.target.value })}
            onBlur={() => validation.blur("clinic_name")}
            aria-invalid={clinicFlag}
            aria-describedby={
              clinicFlag ? "profile-practice-clinic-error" : undefined
            }
            className={fieldClassName(clinicFlag)}
            data-testid="profile-practice-clinic"
          />
        </ProfileField>

        {/* The closed selection. Its refusal is stated under the whole group
            rather than on a chip, because the API's reason names the member it
            refused and no chip here can be the wrong one - a doctor cannot have
            meant a value the list does not contain. */}
        <div>
          <ProfileToggleField
            id="profile-practice-specialties"
            label={t.practiceSpecialtiesLabel}
            help={t.practiceSpecialtiesHelp}
            vocabulary={SPECIALTIES}
            selected={fields.specialties}
            labelFor={(value) => t.specialtyLabels[value]}
            onChange={changeSpecialties}
          />
          {specialtiesFlag && (
            <p
              className="mt-1 text-sm text-danger"
              role="alert"
              data-testid="profile-practice-specialties-error"
            >
              {messageFor("specialties", "server")}
            </p>
          )}
          {fields.specialties.length === 0 && !specialtiesFlag && (
            <p
              className="mt-1 text-xs text-txt-muted"
              data-testid="profile-practice-specialties-empty"
            >
              {t.noSpecialtiesYet}
            </p>
          )}
        </div>

        <div className="w-40">
          <ProfileField
            id="profile-experience"
            label={t.experienceLabel}
            help={t.experienceHelp}
          >
            <input
              id="profile-experience"
              ref={experienceRef}
              type="number"
              inputMode="numeric"
              min={PRACTICE_LIMITS.experienceYears.min}
              max={PRACTICE_LIMITS.experienceYears.max}
              value={fields.experience_years}
              onChange={(event) =>
                change({ experience_years: event.target.value })
              }
              onBlur={() => validation.blur("experience_years")}
              aria-invalid={experienceFlag}
              aria-describedby={
                experienceFlag ? "profile-experience-error" : undefined
              }
              className={fieldClassName(experienceFlag)}
              data-testid="profile-experience"
            />
          </ProfileField>
        </div>
      </div>

      {(nameFlag || clinicFlag || experienceFlag) && (
        <div className="mt-1 space-y-1">
          {nameFlag && (
            <p
              id="profile-practice-name-error"
              className="text-sm text-danger"
              // `alert` only for the client-side refusal, which is the invalid-field
              // line the accessibility floor asks for. A server refusal takes no
              // role: focus is already on the input and `aria-describedby` wires it.
              role={refused.refused.has("full_name") ? undefined : "alert"}
              data-testid="profile-practice-name-error"
            >
              {validation.refuses("full_name")
                ? // Too long is a different sentence from "not said", and the pass
                  // refuses both, so the message reads the value rather than the
                  // flag - otherwise the bound would be a mystery the doctor could
                  // only solve by guessing at the character count.
                  fields.full_name.trim() === ""
                  ? messageFor("full_name", "client")
                  : t.practiceNameTooLong
                : messageFor("full_name", "server")}
            </p>
          )}
          {clinicFlag && (
            <p
              id="profile-practice-clinic-error"
              className="text-sm text-danger"
              role={refused.refused.has("clinic_name") ? undefined : "alert"}
              data-testid="profile-practice-clinic-error"
            >
              {validation.refuses("clinic_name")
                ? messageFor("clinic_name", "client")
                : messageFor("clinic_name", "server")}
            </p>
          )}
          {experienceFlag && (
            <p
              id="profile-experience-error"
              className="text-sm text-danger"
              role={
                refused.refused.has("experience_years") ? undefined : "alert"
              }
              data-testid="profile-experience-error"
            >
              {validation.refuses("experience_years")
                ? messageFor("experience_years", "client")
                : messageFor("experience_years", "server")}
            </p>
          )}
        </div>
      )}
    </ProfileSectionShell>
  );
}
