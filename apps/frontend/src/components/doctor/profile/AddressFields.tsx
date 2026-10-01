"use client";

// #615: the languages the doctor consults in, as the one field the transitional
// whole-form write still edits. Split out of the page's single `DetailsForm`.
//
// #616 changed what this component IS. It used to be the address section: a
// free-text `practice_address` textarea beside the languages field, both edited by
// the declared band's one save. The address now has its own card -
// `AddressSectionCard` - with its own route, its own buffer and its own save, and
// it saves the structured parts the backend assembles `practice_address` from. So
// the textarea is GONE rather than left beside the card, and two consequences
// follow from that rather than being tidied up:
//
//   1. **The address lives in exactly one editor.** Keeping a free-text address
//      next to a structured one would be two editors for one value that disagree,
//      with no way for a doctor to tell which one the listing shows. The card is
//      the only place the address is written.
//
//   2. **This component no longer owns an anchor.** `PROFILE_ANCHORS.address`
//      belongs to the card now, because the card is what a doctor jumps to when
//      they tap the Address chip. Two elements carrying one id would make the
//      chip's target a coin toss, so the id leaves with the field.
//
// The languages field stays exactly where it was, on the declared band's whole-form
// save, and #617's about card is what eventually gives it a section of its own.
// It is deliberately not moved here: a component that owns nothing but one field
// the next ticket is already re-homing is not this ticket's decision to make.
//
// `practice_address` remains in `ProfileForm` because the transitional write's
// request builder still declares it. It is seeded from the projection, never
// edited, and sent back unedited - exactly as the two coordinates already are.

import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { ProfileField, fieldClassName } from "./ProfileField";
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
  );
}
