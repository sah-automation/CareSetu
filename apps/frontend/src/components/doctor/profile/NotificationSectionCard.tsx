"use client";

// #617: the Notification section card - the five switches, and nothing else
// (#610). It is the smallest of the four section writes, and deliberately so: one
// field on one column, so a doctor flipping one switch cannot half-save their
// about text and a doctor rewriting their about text cannot flip a switch they
// never saw.
//
// Three decisions are this card's:
//
//   1. **A `Switch`, not a native checkbox.** The adopted Radix switch is a
//      `<button role="switch">` with `aria-checked`, which is the role that says
//      "this changes something that is on or off" - and it is the primitive the
//      rest of the app already uses, so a control this app has a keyboard answer
//      for is not a second one to invent. A native `<input type="checkbox">` is
//      not wrong, but it would be a different-looking, differently-focusable
//      control on the same page as the other three cards.
//   2. **The labels are clickable and the switch is what toggles.** Each row is a
//      `<label>` wrapping both the text and the switch, so tapping the words
//      flips the switch and the control's accessible name is the doctor's own
//      sentence about what they would be told. Nothing here needs an
//      `aria-labelledby` because there is one control per label.
//   3. **The card submits exactly the five, and the merge is the server's.** A
//      stored key outside the five is preserved by
//      `merge_notification_preferences`, so the promise a save never drops a
//      preference has moved from this page to the backend (#610), where every
//      client gets it. The card therefore does NOT hold the stored dict's other
//      keys: echoing one back would be a 422 on every save (#602's
//      `require_notification_preferences` refuses it).

import { useEffect, useRef } from "react";

import { PROFILE_ANCHORS } from "./ProfileSectionIndex";
import {
  ProfileSectionShell,
  type SectionSaveResult,
} from "./ProfileSectionShell";
import { labelClassName } from "./ProfileField";
import {
  invalidNotificationFields,
  NOTIFICATION_KEYS,
  notificationsFromProfile,
  notificationsUpdateFromFields,
  type NotificationFields,
  type NotificationFieldName,
} from "./notificationCardFields";
import { useRefusedFieldErrors } from "./useRefusedFieldErrors";
import { useSectionEditBuffer } from "./useSectionEditBuffer";
import { useSectionValidation } from "./useSectionValidation";
import { Switch } from "@/components/ui/switch";
import { ApiError } from "@/lib/api-errors";
import { updateDoctorProfileNotifications } from "@/lib/doctor/api";
import { useDoctorProfile } from "@/lib/doctor/DoctorProfileContext";
import { idempotencyKey } from "@/lib/idempotency";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

/**
 * The only wire name this card can be refused on. The backend's own path for an
 * unknown key is `notification_preferences` (the dict itself), which is why the
 * copy is one sentence about the choices rather than a message about a key the
 * doctor never saw.
 */
const MAPPABLE_PATHS = ["notification_preferences"] as const;

export function NotificationSectionCard() {
  const { lang } = useLang();
  const t = STRINGS[lang].doctorProfile;
  const { profile, adoptProfile } = useDoctorProfile();

  const buffer = useSectionEditBuffer(profile, notificationsFromProfile);
  const fields = buffer.value;

  const refused = useRefusedFieldErrors(MAPPABLE_PATHS);
  // Wired in even though the pass is empty by construction, so this card's blur and
  // submit behaviour cannot drift from its siblings' and a rule added later has
  // somewhere to fire without this card being rewritten to run it.
  const validation = useSectionValidation<
    NotificationFieldName,
    NotificationFields
  >(fields, invalidNotificationFields);

  const attemptKey = useRef<string | null>(null);
  const firstSwitchRef = useRef<HTMLButtonElement | null>(null);

  const rejected = refused.refused.has("notification_preferences");
  const summaryOpen = refused.unmapped || rejected;

  function change(
    key: keyof NotificationFields["preferences"],
    value: boolean,
  ) {
    if (fields == null) return;
    buffer.change({ preferences: { ...fields.preferences, [key]: value } });
    refused.clear();
    attemptKey.current = null;
  }

  useEffect(() => {
    if (summaryOpen) firstSwitchRef.current?.focus();
  }, [summaryOpen]);

  useEffect(() => {
    if (!buffer.dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [buffer.dirty]);

  async function saveNotifications(): Promise<SectionSaveResult> {
    if (fields == null) return { status: "declined" };

    // The pass exists and is empty by construction - see
    // `invalidNotificationFields` - and is still run so that this card's save
    // path reads the same as its siblings' and a rule added later has somewhere
    // to fire.
    if (validation.submit().length > 0) return { status: "declined" };

    const attempt = attemptKey.current ?? idempotencyKey();
    attemptKey.current = attempt;
    try {
      const answer = await updateDoctorProfileNotifications(
        notificationsUpdateFromFields(fields),
        attempt,
      );
      attemptKey.current = null;
      // The answer's `notification_preferences` is the SERVER'S MERGE, so it may
      // carry a stored key this card does not render. Adopting the whole answer
      // is what keeps that promise visible to the rest of the page; this card
      // itself re-seeds from it through the same narrowing rule as every other
      // section, and never echoes the unknown key back.
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
      title={t.notificationsHeading}
      help={t.notificationsHelp}
      anchorId={PROFILE_ANCHORS.notifications}
      testId="profile-notification-card"
      save={{
        onSave: saveNotifications,
        dirty: buffer.dirty,
        edits: buffer.edits,
        label: t.save,
        savedLabel: t.notificationsSaved,
        unsavedLabel: t.unsavedChanges,
        failureMessage: t.notificationsSaveFailed,
        buttonTestId: "profile-notifications-save",
        savedTestId: "profile-notifications-saved",
        unsavedTestId: "profile-notifications-unsaved",
      }}
    >
      {summaryOpen && (
        <div
          className="mb-3 rounded-md border border-danger-border bg-danger-soft px-3 py-2 text-sm text-danger"
          role="alert"
          aria-live="assertive"
          data-testid="profile-notification-summary"
        >
          <p>
            {rejected ? t.notificationPreferencesRejected : t.unmappedField}
          </p>
        </div>
      )}

      {/* One group, one accessible name, five switches. The group is what makes
          the set skippable and announced as a set rather than as five unrelated
          controls, and it is the one landmark this card adds - see the closing
          note in the suite about the declared band no longer wrapping it. */}
      <div
        role="group"
        aria-label={t.notificationGroupLabel}
        className="space-y-3"
        data-testid="profile-notification-group"
      >
        {NOTIFICATION_KEYS.map((key, index) => (
          <label
            key={key}
            htmlFor={`profile-notification-${key}`}
            // `min-h-11` is 44px, and 44px is the accessibility floor's minimum
            // rather than its preference (blueprint A9.4). The row rather than the
            // `Switch` carries it, because the whole row is the tap target: the
            // switch itself is `h-6` and a doctor aiming at a 24px control with a
            // finger on a phone is a doctor who misses it.
            className="flex min-h-11 items-center justify-between gap-4"
          >
            <span className={labelClassName}>{t.notificationLabels[key]}</span>
            <Switch
              id={`profile-notification-${key}`}
              ref={index === 0 ? firstSwitchRef : undefined}
              checked={fields.preferences[key]}
              onCheckedChange={(value) => change(key, value)}
              data-testid={`profile-notification-${key}`}
            />
          </label>
        ))}
      </div>
    </ProfileSectionShell>
  );
}
