"use client";

// #615: the about section - what the doctor tells patients about their practice,
// in the free-text field the current whole-form write still edits. A split, not a
// re-design: the brief puts the section's contents in #617.
//
// The declared consulting DAYS and HOURS the projection now carries (#610
// replaced the retired `availability` blob) are deliberately not rendered here.
// Printing raw wire values would mean a doctor reading "mon, wed" instead of
// their working days, and the closed-vocabulary day labels and the hours editor
// are #617's content to write. Until then the section shows the one field that
// has an editor, and nothing claims to show hours it has not translated.

import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { ProfileField, fieldClassName } from "./ProfileField";
import { PROFILE_ANCHORS } from "./ProfileSectionIndex";
import { LIMITS, type ProfileFieldName, type ProfileForm } from "./profileForm";

export interface AboutFieldsProps {
  form: ProfileForm;
  invalid: readonly ProfileFieldName[];
  onChange: (patch: Partial<ProfileForm>) => void;
}

export function AboutFields({ form, invalid, onChange }: AboutFieldsProps) {
  const { lang } = useLang();
  const t = STRINGS[lang].doctorProfile;
  const isInvalid = (field: ProfileFieldName) => invalid.includes(field);

  return (
    <div id={PROFILE_ANCHORS.about}>
      <ProfileField id="profile-about" label={t.aboutLabel}>
        <textarea
          id="profile-about"
          maxLength={LIMITS.about}
          value={form.about}
          onChange={(event) => onChange({ about: event.target.value })}
          placeholder={t.aboutPlaceholder}
          aria-invalid={isInvalid("about")}
          className={`${fieldClassName(isInvalid("about"))} h-24 py-2`}
          data-testid="profile-about"
        />
      </ProfileField>
    </div>
  );
}
