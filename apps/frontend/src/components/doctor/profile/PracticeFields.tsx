"use client";

// #615: the practice section - the doctor's own name and their years of
// experience, the two fields this card already edited, split out of the page's
// single `DetailsForm` so the page renders a component per section rather than a
// section's fields inline.
//
// This is a SPLIT, not a re-design. The brief puts the section's contents in
// #616/#617, so nothing is added here: whatever this card showed before, it shows
// now, in a component the page can address by anchor.
//
// The clinic name and the specialty SELECTION are deliberately NOT repeated
// here. Both are already on this page - the identity band shows the clinic
// beneath the doctor's name and the selection as chips - and the projection's
// comment says the selection has two writers and the closed pick-list behind it
// has no client yet. A second read-only copy would be a second place to delete
// when the real editor lands, and would answer a question the identity band has
// already answered.

import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { ProfileField, fieldClassName } from "./ProfileField";
import { PROFILE_ANCHORS } from "./ProfileSectionIndex";
import { LIMITS, type ProfileFieldName, type ProfileForm } from "./profileForm";

export interface PracticeFieldsProps {
  form: ProfileForm;
  invalid: readonly ProfileFieldName[];
  onChange: (patch: Partial<ProfileForm>) => void;
}

export function PracticeFields({
  form,
  invalid,
  onChange,
}: PracticeFieldsProps) {
  const { lang } = useLang();
  const t = STRINGS[lang].doctorProfile;
  const isInvalid = (field: ProfileFieldName) => invalid.includes(field);

  return (
    <div id={PROFILE_ANCHORS.practice}>
      <div className="grid gap-3 sm:grid-cols-2">
        <ProfileField id="profile-practice-name" label={t.practiceNameLabel}>
          <input
            id="profile-practice-name"
            type="text"
            maxLength={LIMITS.practiceName}
            value={form.practice_name}
            onChange={(event) =>
              onChange({ practice_name: event.target.value })
            }
            aria-invalid={isInvalid("practice_name")}
            className={fieldClassName(isInvalid("practice_name"))}
            data-testid="profile-practice-name"
          />
        </ProfileField>

        <ProfileField id="profile-experience" label={t.experienceLabel}>
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
            className={fieldClassName(isInvalid("experience_years"))}
            data-testid="profile-experience"
          />
        </ProfileField>
      </div>
    </div>
  );
}
