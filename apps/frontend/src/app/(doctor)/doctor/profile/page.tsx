// PHASE-8.1 (#543): doctor console Profile page - the live destination behind
// the Profile nav entry that #541 left coming-soon. Renders and edits the private
// profile projection from #542: photo upload/preview/remove through the
// profile-media-backed private endpoints, practice details, experience,
// languages, about, the verified/credential status, and the notification toggles.
// Desktop and mobile, all copy bilingual en/hi (REQ-006).

// #583: the page keeps no local copy of the projection. It reads the shared
// doctor profile source the (doctor) route-group layout mounts above it and the
// console chrome, and hands that source the backend's answer after every edit -
// which is what makes an upload, a removal or a rename land in the account menu
// at once instead of after a reload.

// #605: the page's editable fields are one `useSectionEditBuffer` per section
// and the saving section renders through the reusable `ProfileSectionShell`, so
// the in-flight-edit discipline that used to be written out inline here is stated
// once, in the buffer, and a future section inherits it instead of restating it.

// #615: the page is now a SHELL. The identity band heads it, the sticky
// anchor-chip index sits under the chrome, and every section is a component in
// `@/components/doctor/profile` rather than markup inlined here. What stays on
// this page is exactly what the brief scopes to it: the whole-form request
// builder, its validation pass, the partial-field `adoptRef` seam, the per-attempt
// idempotency keys, and the photo seam's transport.
//
// The declared band's ONE save is the whole-form write, which #611 RETIRED - so
// that save currently 405s and the declared band is not yet savable. The
// section-write client calls that replace it are out of scope here (#616/#617
// own them), which is why the practice, address, about and notification sections
// render inside the declared band and share one save for now. That is a
// transition, not the destination: when the section writes land, the band drops
// its save and each section carries its own, which is why each one is already a
// separate component with no shared markup. See the note above `saveProfile`.
//
// The page heading is the identity band's, not `PageHeader`'s: the band renders
// the doctor's own name as the h1, which is what a profile page is for. The
// `PageHeader` therefore survives for the two states with no name to show -
// loading and a failed read.
//
// CLOSING NOTES, per the brief's ask to record what a reviewer cannot see:
//
// 1. Changed a landed sibling's contract: `ProfileSectionShell` gained an
//    optional `anchorId`, because the index needs a target per section and
//    wrapping every section in a second element for its id would give each one
//    two headings and two landmarks. Optional, so no existing caller changed.
// 2. The declared band's save calls a route #611 removed, so it 405s today. Left
//    in place deliberately - see the note above `saveProfile` - because fixing it
//    means the section-write clients, which are #616/#617's.
// 3. Four chips address field groups with no heading of their own, because those
//    headings are section CONTENT and belong to #616/#617. Asserted as the known
//    state in the page suite rather than left implied.
// 4. Vocabulary that does not resolve yet: `locality` and `clinic name` are
//    glossary entries #622 introduces, and #615 was their first consumer on the
//    doctor surface. No glossary entry is added here. The one place the wording
//    felt wrong: the identity band prints the clinic name with NO label of its
//    own, directly beneath the doctor's name, so this ticket needed no label for
//    it at all - if #616's address card ends up labelling it "Clinic name", that
//    string is #622's to fix, not this ticket's.
// 5. `PracticeFields`, `AddressFields` and `AboutFields` render exactly the fields
//    they rendered before the split. `consulting_days`, `consulting_hours`,
//    `address_line` and `pin_code` arrive on the projection and are deliberately
//    NOT shown: printing raw wire values ("mon, tue") is not doctor-facing copy,
//    and the translation belongs to the section that will own them.

import { useEffect, useRef, useState } from "react";

import { AddressFields } from "@/components/doctor/profile/AddressFields";
import { AboutFields } from "@/components/doctor/profile/AboutFields";
import { ConsultationFeeCard } from "@/components/doctor/profile/ConsultationFeeCard";
import { NotificationFields } from "@/components/doctor/profile/NotificationFields";
import { PracticeFields } from "@/components/doctor/profile/PracticeFields";
import { ProfileCredentialList } from "@/components/doctor/profile/ProfileCredentialList";
import { ProfileIdentityBand } from "@/components/doctor/profile/ProfileIdentityBand";
import {
  PROFILE_ANCHORS,
  ProfileSectionIndex,
} from "@/components/doctor/profile/ProfileSectionIndex";
import {
  ProfileSectionShell,
  type SectionFailure,
  type SectionSaveResult,
} from "@/components/doctor/profile/ProfileSectionShell";
import {
  LIMITS,
  MAX_NOTIFICATION_ENTRIES,
  MAX_NOTIFICATION_KEY_LENGTH,
  NOTIFICATION_KEYS,
  type NotificationKey,
  type ProfileFieldName,
  type ProfileForm,
} from "@/components/doctor/profile/profileForm";
import { useSectionEditBuffer } from "@/components/doctor/profile/useSectionEditBuffer";
import { ErrorBanner } from "@/components/layout/ErrorBanner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api-errors";
import {
  deleteDoctorProfilePhoto,
  fetchDoctorProfilePhoto,
  updateDoctorProfile,
  uploadDoctorProfilePhoto,
  type DoctorProfileUpdate,
  type DoctorProfileView,
} from "@/lib/doctor/api";
import { useDoctorProfile } from "@/lib/doctor/DoctorProfileContext";
import { idempotencyKey } from "@/lib/idempotency";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { useProfilePhotoSource } from "@/lib/profile/useProfilePhotoSource";

function optionalText(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

/** Parse the comma-separated languages editor into the backend list shape. */
function splitLanguages(value: string): string[] {
  const seen = new Set<string>();
  const languages: string[] = [];
  for (const part of value.split(",")) {
    const language = part.trim();
    if (language === "") continue;
    // The backend rejects duplicate language names (case-insensitive), so fold
    // them here rather than failing the doctor's save over their typing.
    const key = language.toLocaleLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    languages.push(language);
  }
  return languages;
}

function seedNotifications(
  stored: Record<string, boolean>,
): Record<string, boolean> {
  const seeded: Record<string, boolean> = {};
  for (const [key, value] of Object.entries(stored)) {
    // A key the validator would refuse to accept back is dropped: keeping it
    // would make every later save 422. Nothing else is ever dropped.
    if (key.length <= MAX_NOTIFICATION_KEY_LENGTH) seeded[key] = value;
  }
  for (const key of NOTIFICATION_KEYS) {
    if (key in seeded) continue;
    // A stored dict already at the cap keeps its entries; the toggle still
    // renders and a flip adds the key once there is room on a later save.
    if (Object.keys(seeded).length >= MAX_NOTIFICATION_ENTRIES) continue;
    // An absent key means the doctor never chose, so the toggle starts off.
    seeded[key] = false;
  }
  return seeded;
}

function formFromProfile(profile: DoctorProfileView): ProfileForm {
  return {
    practice_name: profile.practice_name ?? "",
    practice_address: profile.practice_address,
    // Carried, never edited. #615 removed the coordinate inputs, and the backend
    // writes these two itself from the declared PIN code (#609), so the doctor is
    // never asked the question. The two strings stay in the form because the
    // transitional request builder still declares them - see the note above
    // `saveProfile` for what that builder currently is worth.
    practice_latitude: String(profile.practice_latitude),
    practice_longitude: String(profile.practice_longitude),
    experience_years:
      profile.experience_years == null ? "" : String(profile.experience_years),
    languages: profile.languages.join(", "),
    about: profile.about ?? "",
    notifications: seedNotifications(profile.notification_preferences),
  };
}

function invalidFields(form: ProfileForm): ProfileFieldName[] {
  const invalid: ProfileFieldName[] = [];

  if (form.practice_name.trim().length > LIMITS.practiceName) {
    invalid.push("practice_name");
  }

  const address = form.practice_address.trim();
  if (address === "" || address.length > LIMITS.practiceAddress) {
    invalid.push("practice_address");
  }

  if (form.experience_years.trim() !== "") {
    const years = Number(form.experience_years);
    if (
      !Number.isInteger(years) ||
      years < LIMITS.experienceYears.min ||
      years > LIMITS.experienceYears.max
    ) {
      invalid.push("experience_years");
    }
  }

  // The validator bounds the list length and each name inside it.
  const languages = splitLanguages(form.languages);
  if (
    languages.length > LIMITS.languages ||
    languages.some((language) => language.length > LIMITS.languageNameLength)
  ) {
    invalid.push("languages");
  }

  if (form.about.trim().length > LIMITS.about) {
    invalid.push("about");
  }

  return invalid;
}

function updateFromForm(form: ProfileForm): DoctorProfileUpdate {
  return {
    practice_name: optionalText(form.practice_name),
    practice_address: form.practice_address.trim(),
    practice_latitude: Number(form.practice_latitude),
    practice_longitude: Number(form.practice_longitude),
    experience_years:
      form.experience_years.trim() === ""
        ? null
        : Number(form.experience_years),
    languages: splitLanguages(form.languages),
    about: optionalText(form.about),
    notification_preferences: form.notifications,
  };
}

function LoadingSkeleton() {
  return (
    <div className="space-y-3" data-testid="profile-skeleton">
      <div className="flex items-center gap-4 rounded-lg border border-hairline bg-surface p-4">
        <Skeleton className="h-20 w-20 rounded-full" />
        <div className="space-y-2">
          <Skeleton className="h-4 w-40" />
          <Skeleton className="h-3 w-24" />
        </div>
      </div>
      <div className="space-y-2 rounded-lg border border-hairline bg-surface p-4">
        <Skeleton className="h-4 w-32" />
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-9 w-full" />
      </div>
    </div>
  );
}

export default function DoctorProfilePage() {
  const { lang } = useLang();
  const t = STRINGS[lang].doctorProfile;

  // #583: the shared source, not a page-private read. It answers before any
  // console page renders its contents, and the account menu above this page
  // reads the same projection - so the two can never drift.
  const { profile, status, errorTraceId, reload, adoptProfile } =
    useDoctorProfile();
  const [bannerOpen, setBannerOpen] = useState(false);

  const [photoBusy, setPhotoBusy] = useState(false);
  const [photoFailure, setPhotoFailure] = useState<SectionFailure | null>(null);

  const [invalid, setInvalid] = useState<ProfileFieldName[]>([]);
  // One idempotency key per user attempt: a retry of the same attempt reuses it
  // (so a lost response cannot write twice), and an edit starts a new attempt.
  // The key stays with the request builder rather than moving into the section
  // shell, because the shell owns no transport - it owns only the button.
  const saveAttemptKey = useRef<string | null>(null);
  const removeAttemptKey = useRef<string | null>(null);

  // #605: the editable fields are one in-flight edit buffer, seeded from the
  // shared projection and holding nothing else. The buffer owns the discipline
  // that made an in-flight edit safe - seeded once per distinct server answer by
  // object identity, never reseeded while the doctor is typing, and never
  // reseeded by a save's own reply - so the reasoning lives with the rule rather
  // than in this page's render (REQ story 16: typing survives a profile that is
  // still loading or reloading).
  const formBuffer = useSectionEditBuffer(profile, formFromProfile);
  const { value: form } = formBuffer;

  // The newest projection, mirrored out of the render so the partial edits below
  // merge onto it rather than onto whatever this render happened to close over.
  // Each of them awaits a request, and a practice-details save that lands in that
  // window carries a moved `practice_name` and a moved fee - merging the older
  // render's copy would put them straight back.
  const newestProfile = useRef<DoctorProfileView | null>(null);
  useEffect(() => {
    newestProfile.current = profile;
  }, [profile]);

  // The one partial edit the source cannot answer on its own: the backend's
  // upload and remove endpoints hand back a ref (or its absence) and nothing
  // else, so the page folds that one field into the projection it already holds
  // and hands the whole view back through the single adopt seam.
  function adoptRef<K extends keyof DoctorProfileView>(
    field: K,
    value: DoctorProfileView[K],
  ) {
    const current = newestProfile.current;
    if (current === null) return;
    adoptProfile({ ...current, [field]: value });
  }

  // The photo is a private profile-media key, never a public URL, so the shared
  // seam resolves it: the bytes come over the authed transport and this page
  // names the transport, not the resolution. Its ref came with the profile, so
  // nothing extra is fetched to resolve it.
  const { src: photoUrl, absent: mediaAbsent } = useProfilePhotoSource(
    profile?.photo_ref ?? null,
    fetchDoctorProfilePhoto,
  );

  function retryLoad() {
    setBannerOpen(false);
    reload();
  }

  // The read now lives in the shared source, so the page is told the read
  // failed rather than catching it. Dismissing sticks until the status changes
  // again, which is what makes a retry that fails twice show the banner twice.
  useEffect(() => {
    if (status === "error") setBannerOpen(true);
  }, [status]);

  // One edit seam for the whole section, so the idempotency key is cleared in
  // exactly one place: a fresh edit is a fresh attempt, and nothing else is.
  function changeForm(patch: Partial<ProfileForm>) {
    formBuffer.change(patch);
    saveAttemptKey.current = null;
  }

  function toggleNotification(key: NotificationKey, value: boolean) {
    if (form == null) return;
    changeForm({
      notifications: { ...form.notifications, [key]: value },
    });
  }

  async function saveProfile(): Promise<SectionSaveResult> {
    if (form == null) return { status: "declined" };
    const problems = invalidFields(form);
    setInvalid(problems);
    if (problems.length > 0) return { status: "declined" };
    const attemptKey = saveAttemptKey.current ?? idempotencyKey();
    saveAttemptKey.current = attemptKey;
    try {
      // STILL CALLING A RETIRED ROUTE, and known to be so. #611 removed the
      // whole-form `PUT /v1/doctor/profile`; the backend now serves four
      // per-section writes (`/profile/practice`, `/profile/address`,
      // `/profile/about`, `/profile/notifications`) and no whole-form body at
      // all. So this call currently 405s, and the declared band's Save button
      // cannot succeed until the section-write clients land (#616/#617).
      //
      // It is left in place deliberately. #615's brief scopes the page's SPLIT
      // and forbids touching `updateDoctorProfile`, and the four section
      // components are already independent - so #616/#617 is a change of which
      // client each section calls, not a rewrite. Removing the save instead would
      // take away the one affordance the existing suite proves works (the
      // per-attempt idempotency-key discipline, which the section writes inherit
      // through the same shell) and would hide the gap rather than record it.
      //
      // What this means for a reader: the declared band's fields are rendered
      // editable and are NOT yet savable, and that is a known transitional state
      // rather than a working feature. `updateDoctorProfile` writes no photo ref
      // (its model declares none), so nothing here can detach a stored photo.
      adoptProfile(await updateDoctorProfile(updateFromForm(form), attemptKey));
      saveAttemptKey.current = null;
      // The reply does not clear the buffer's dirty flag, and the buffer is what
      // decides whether a late answer may reseed: it is the same answer the
      // buffer already holds, so there is nothing to reseed from, and a doctor
      // who kept typing across the save must not lose those keystrokes to it.
      return { status: "saved" };
    } catch (err) {
      return {
        status: "failed",
        failure: {
          traceId: err instanceof ApiError ? err.traceId : undefined,
        },
      };
    }
  }

  async function uploadPhoto(file: File) {
    setPhotoBusy(true);
    setPhotoFailure(null);
    try {
      // A pick is its own attempt: there is no stored file to retry with, so
      // the key is minted per upload rather than reused.
      const { photo_ref } = await uploadDoctorProfilePhoto(
        file,
        idempotencyKey(),
      );
      // The new key re-runs the resolution, which revokes the old object URL and
      // streams the stored photo back - in the identity band's avatar and in the
      // console chrome at the same time, because they are one source now.
      adoptRef("photo_ref", photo_ref);
    } catch (err) {
      setPhotoFailure({
        traceId: err instanceof ApiError ? err.traceId : undefined,
      });
    } finally {
      setPhotoBusy(false);
    }
  }

  async function removePhoto() {
    setPhotoBusy(true);
    setPhotoFailure(null);
    try {
      await deleteDoctorProfilePhoto(
        removeAttemptKey.current ?? idempotencyKey(),
      );
      removeAttemptKey.current = null;
      // Cleared, not stale: the chrome stops showing a photo the doctor has just
      // declared should not be there.
      adoptRef("photo_ref", null);
    } catch (err) {
      setPhotoFailure({
        traceId: err instanceof ApiError ? err.traceId : undefined,
      });
    } finally {
      setPhotoBusy(false);
    }
  }

  function onFeeSaved(feePaise: number | null) {
    adoptRef("consultation_fee", feePaise);
  }

  const ready = status === "ready" && profile != null && form != null;
  // The chip labels are the target sections' own dictionary headings, so a chip
  // never names a section differently from the way the section names itself.
  //
  // The two bands keep separate chips rather than sharing one "details" target:
  // two bands, two anchors, two ids, and no chip pointing at both.
  //
  // KNOWN GAP, owned by #616/#617: four of these chips - practice, address,
  // about, notifications - address a field group inside the declared band, and
  // those groups carry no heading yet, because the section headings belong to the
  // section-content tickets. A reader who jumps to one of those four lands
  // correctly but hears no heading announced. Adding headings here would be
  // pre-empting #616/#617's presentation; this note records the gap so the next
  // ticket inherits it knowingly rather than discovering it.
  const anchors = [
    { id: PROFILE_ANCHORS.verified, label: t.verifiedBandTitle },
    { id: PROFILE_ANCHORS.declared, label: t.declaredBandTitle },
    { id: PROFILE_ANCHORS.practice, label: t.practiceSectionTitle },
    { id: PROFILE_ANCHORS.address, label: t.addressSectionTitle },
    { id: PROFILE_ANCHORS.about, label: t.aboutSectionTitle },
    { id: PROFILE_ANCHORS.notifications, label: t.notificationsHeading },
    { id: PROFILE_ANCHORS.fee, label: t.feeHeading },
  ];

  return (
    <>
      {/* Only the two states with no doctor name to show get a header of their
          own: the ready state below renders its own h1 in the identity band. */}
      {status === "loading" && (
        <PageHeader title={t.title} description={t.description} />
      )}

      {status === "error" && bannerOpen && (
        <>
          <PageHeader title={t.title} description={t.description} />
          <ErrorBanner
            message={t.loadFailed}
            traceId={errorTraceId}
            onRetry={retryLoad}
            onDismiss={() => setBannerOpen(false)}
          />
        </>
      )}

      {status === "loading" && <LoadingSkeleton />}

      {ready && (
        <div className="space-y-4">
          <ProfileIdentityBand
            profile={profile}
            photoUrl={photoUrl}
            mediaAbsent={mediaAbsent}
            busy={photoBusy}
            failure={photoFailure}
            onPick={(file) => void uploadPhoto(file)}
            onRemove={() => void removePhoto()}
            onDismissFailure={() => setPhotoFailure(null)}
          />

          <ProfileSectionIndex anchors={anchors} />

          {/* The verified band: what the platform derived and checked. Read-only,
              and its tick is the identity band's tick - one flag, read twice -
              so the two bands cannot disagree about the same doctor. A false flag
              renders no tick here at all, never a tick beside a stale list. */}
          <ProfileSectionShell
            title={t.verifiedBandTitle}
            help={t.verifiedBandHelp}
            anchorId={PROFILE_ANCHORS.verified}
            testId="profile-verified-band"
          >
            <ProfileCredentialList profile={profile} />
          </ProfileSectionShell>

          {/* The declared band: everything the doctor typed, and it says so in
              words. Its one save is the transitional whole-form write, because
              the section-write clients belong to #616/#617 - the sections below
              are already separate components, so giving each its own save is a
              wiring change and not a rewrite. */}
          <ProfileSectionShell
            title={t.declaredBandTitle}
            help={t.declaredBandHelp}
            anchorId={PROFILE_ANCHORS.declared}
            testId="profile-declared-band"
            save={{
              onSave: saveProfile,
              dirty: formBuffer.dirty,
              edits: formBuffer.edits,
              label: t.save,
              savedLabel: t.saved,
              unsavedLabel: t.unsavedChanges,
              failureMessage: t.saveFailed,
              buttonTestId: "profile-save",
              savedTestId: "profile-saved",
              unsavedTestId: "profile-unsaved",
            }}
          >
            <div className="space-y-5">
              <PracticeFields
                form={form}
                invalid={invalid}
                onChange={changeForm}
              />
              <AddressFields
                form={form}
                invalid={invalid}
                onChange={changeForm}
              />
              <AboutFields
                form={form}
                invalid={invalid}
                onChange={changeForm}
              />
              <NotificationFields form={form} onToggle={toggleNotification} />
            </div>

            {invalid.length > 0 && (
              <p
                className="mt-2 text-sm text-danger"
                role="alert"
                data-testid="profile-invalid"
              >
                {t.invalidFields}
              </p>
            )}
          </ProfileSectionShell>

          <ConsultationFeeCard
            feePaise={profile.consultation_fee}
            onFeeSaved={onFeeSaved}
          />
        </div>
      )}
    </>
  );
}
