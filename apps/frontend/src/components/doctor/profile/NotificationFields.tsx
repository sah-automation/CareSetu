"use client";

// #615: the notification section - the doctor's own choice about what CareSetu
// tells them about, split out of the page's single `DetailsForm`.
//
// The toggles are plain checkboxes on purpose. The adopted `Switch` and
// `ToggleGroup` primitives (#600) exist, but the section-content ticket owns the
// toggle group's contents and the design system's decision about which control a
// notification preference gets; swapping the control here would be re-deciding
// that in a ticket scoped to the page's shell, and a checkbox that later becomes
// a switch is one class change rather than a rewrite. What this section owns is
// the KEY VOCABULARY the backend accepts, which is why it renders
// `NOTIFICATION_KEYS` rather than whatever the stored dict happens to hold.
//
// Touch target: the existing `min-h-11` row is 44px, which is the accessibility
// floor's minimum and not a preference (blueprint §9.4).

import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { PROFILE_ANCHORS } from "./ProfileSectionIndex";
import { NOTIFICATION_KEYS, type ProfileForm } from "./profileForm";

export interface NotificationFieldsProps {
  form: ProfileForm;
  onToggle: (key: (typeof NOTIFICATION_KEYS)[number], value: boolean) => void;
}

export function NotificationFields({
  form,
  onToggle,
}: NotificationFieldsProps) {
  const { lang } = useLang();
  const t = STRINGS[lang].doctorProfile;

  return (
    <div id={PROFILE_ANCHORS.notifications}>
      <ul className="space-y-2">
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
    </div>
  );
}
