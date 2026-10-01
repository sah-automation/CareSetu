"use client";

// #615: the address section - the practice address line and the languages the
// doctor consults in. Split out of the page's single `DetailsForm`. This is a
// SPLIT: the brief puts the address card's CONTENTS in #616, so exactly the two
// fields this card already edited are what it renders.
//
// The coordinates that used to sit beside these two fields are GONE (#615 AC 5),
// and their absence is the section's point, not a gap: the doctor is never asked
// to type a question only a map could answer. The backend derives the practice
// position from the declared PIN code (#609), so the server-written
// `practice_latitude`/`practice_longitude` travel through the transitional
// whole-form write unedited and are never shown.
//
// The structured parts - line, landmark, locality, city, PIN - are deliberately
// NOT rendered. The projection serves them for the address card's editable form
// to seed from, and #616 is the ticket that writes that card; printing them here
// as read-only rows would put the address in two places on the page and present a
// doctor with a PIN code they are told nothing about. The single free-text
// address below is the field the current whole-form write actually edits, so it
// stays.

import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { ProfileField, fieldClassName } from "./ProfileField";
import { PROFILE_ANCHORS } from "./ProfileSectionIndex";
import { LIMITS, type ProfileFieldName, type ProfileForm } from "./profileForm";

export interface AddressFieldsProps {
  form: ProfileForm;
  invalid: readonly ProfileFieldName[];
  onChange: (patch: Partial<ProfileForm>) => void;
}

export function AddressFields({ form, invalid, onChange }: AddressFieldsProps) {
  const { lang } = useLang();
  const t = STRINGS[lang].doctorProfile;
  const isInvalid = (field: ProfileFieldName) => invalid.includes(field);

  return (
    <div id={PROFILE_ANCHORS.address}>
      <ProfileField id="profile-address" label={t.addressLabel}>
        <textarea
          id="profile-address"
          maxLength={LIMITS.practiceAddress}
          value={form.practice_address}
          onChange={(event) =>
            onChange({ practice_address: event.target.value })
          }
          aria-invalid={isInvalid("practice_address")}
          className={`${fieldClassName(
            isInvalid("practice_address"),
          )} h-20 py-2`}
          data-testid="profile-address"
        />
      </ProfileField>

      <div className="mt-3">
        <ProfileField
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
            className={fieldClassName(isInvalid("languages"))}
            data-testid="profile-languages"
          />
        </ProfileField>
      </div>
    </div>
  );
}
