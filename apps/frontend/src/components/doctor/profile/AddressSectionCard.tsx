"use client";

// #616: the Address section card. An address, declared rather than pinned:
// building and street, an optional landmark, a locality, a city and a six-digit
// PIN code, with district and state shown back read-only.
//
// Four decisions in here are this ticket's, and each is a decision about what the
// client is NOT allowed to do:
//
//   1. **No coordinate input, and no coordinate field in the body.** The backend
//      derives the one practice position every reader sees from the declared PIN
//      code (#609, ADR-0022), and its model refuses a body carrying a coordinate.
//      A field here would put the question back in front of the doctor, and the
//      422 that answers it is the failure mode this card exists to remove.
//
//   2. **The field-level error belongs under the PIN input, and only there.** An
//      unresolvable PIN is an expected 4xx (error taxonomy), not an operational
//      failure: calm, specific, actionable copy, no page banner, no spinner and no
//      auto-retry (ui-blueprint §9.1 - a 4xx is never retried). It reaches this
//      card because #609's handler puts the PIN field's wire name in
//      `details.errors[].path`, and that path survives the throw only because
//      `ApiError` now keeps `details`.
//
//   3. **A rejected write adopts nothing.** Not the answer seam, not the dirty
//      flag, not the shared source. "The rest of the page's unsaved edits survive
//      it" is guaranteed by the buffer's own guards, and the failure path is
//      exactly where that is easiest to break by tidying up.
//
//   4. **The belt notice is a notice.** An outside-the-belt PIN saves, and only
//      this doctor's own listing surfaces as an outside-your-area result (the
//      wider-area fallback, ADR-0021), so the copy says that instead of calling
//      the address invalid. It renders from the last write answer that carried the
//      warning, because the client cannot compute it: the belt boundary is a
//      parameter of the server's pure decision over a table the browser does not
//      hold. Before the first save there is nothing to warn with, and that is an
//      absent notice rather than a spinner over an input the doctor is typing in.
//
// The unsaved-changes guard is the platform `beforeunload` event, registered and
// removed with this card's dirty flag - the first navigation guard in the tree.
// The prompt string is browser-owned on every mainstream browser, so this
// registers the event and sets no translated text it cannot control.

import { useEffect, useRef, useState } from "react";

import {
  ADDRESS_LIMITS,
  addressFromProfile,
  addressUpdateFromFields,
  invalidAddressFields,
  type AddressFieldName,
  type AddressFields,
} from "./addressCardFields";
import { inputClassName, ProfileField, fieldClassName } from "./ProfileField";
import { usePublicProfileDraft } from "./PublicProfileDraftContext";
import { addressDraftFromFields } from "./publicProfileProjection";
import { PROFILE_ANCHORS } from "./ProfileSectionIndex";
import {
  ProfileSectionShell,
  type SectionSaveResult,
} from "./ProfileSectionShell";
import { useRefusedFieldErrors } from "./useRefusedFieldErrors";
import { useSectionEditBuffer } from "./useSectionEditBuffer";
import { useSectionValidation } from "./useSectionValidation";
import { ApiError } from "@/lib/api-errors";
import { useDoctorProfile } from "@/lib/doctor/DoctorProfileContext";
import { updateDoctorProfileAddress } from "@/lib/doctor/api";
import { idempotencyKey } from "@/lib/idempotency";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

/**
 * The wire name this card maps a server's `details.errors[].path` onto. A
 * constant rather than a lookup over the field list, so the mapping is one
 * readable line and an unmappable path cannot be added by accident.
 */
const PIN_PATH = "pin_code";

/** The id of the one field-level message, which the PIN input points at. */
const PIN_ERROR_ID = "profile-address-pin-error";

/**
 * What the last answer said about the belt. Held here rather than in the buffer
 * because it is the WRITE's answer, not the doctor's draft: a doctor who types a
 * new PIN has not moved their listing yet, and a notice that followed the
 * keystrokes would claim a consequence that has not happened.
 */
interface BeltNotice {
  outside: boolean;
  distanceKm: number;
}

export function AddressSectionCard() {
  const { lang } = useLang();
  const t = STRINGS[lang].doctorProfile;
  // The same shared answer object every other surface reads, which is what makes
  // the buffer's identity guard correct: a card seeded from its own slice would
  // reseed whenever any other section's answer landed.
  const { profile, adoptProfile } = useDoctorProfile();
  // #618: the live preview reads this card's typed locality, so this card is the
  // only writer of that one slice of the draft.
  const { publish } = usePublicProfileDraft();

  const buffer = useSectionEditBuffer(profile, addressFromProfile);
  const fields = buffer.value;

  // Per-field refusals, client-side and server-side. Both are cleared by the next
  // edit so a stale line never outlives the state it described, and they are
  // mutually exclusive by construction: a validation failure never reaches the
  // API, and the attempt that would clear one starts by clearing the other.
  //
  // #617: the server side is now the shared `useRefusedFieldErrors` hook rather
  // than this card's own two booleans. Three sibling cards read the same 422 the
  // same way, so the reading - which paths are mine, which are not - lives in one
  // place and this card declares only the one path it can map.
  //
  // #623: the CLIENT side moved onto the shared `useSectionValidation` too. It was
  // the last card still holding its own `clientInvalid` state, which meant it
  // validated on submit and never on blur - so a doctor who typed an unresolvable
  // PIN, tabbed away and came back got nothing until they pressed Save, while the
  // three sibling cards had already told them at the blur. Blueprint A9.5 asks for
  // both, and "the fourth card is the exception" is how four cards drift apart.
  const validation = useSectionValidation<AddressFieldName, AddressFields>(
    fields,
    invalidAddressFields,
  );
  const refused = useRefusedFieldErrors([PIN_PATH]);
  const [belt, setBelt] = useState<BeltNotice | null>(null);

  // One idempotency key per user attempt (api-standards §5): a retry of the same
  // attempt re-enters this handler through the shell's retry action and therefore
  // reuses the key, so a lost response cannot write the address twice. An edit
  // starts a new attempt and mints a new one.
  const attemptKey = useRef<string | null>(null);
  const pinRef = useRef<HTMLInputElement | null>(null);
  const firstPartRef = useRef<HTMLInputElement | null>(null);

  const pinInvalid = validation.showsError(PIN_PATH);
  const serverPinError = refused.refused.has(PIN_PATH);
  // A server `path` this card cannot map to an input lands in the form summary
  // instead (ui-blueprint §9.5): dropping it would hide a real failure, and
  // guessing it onto the nearest input would blame a field the server never named.
  const unmappedServerError = refused.unmapped;
  // A submit answer, not a blur answer: one refused PIN belongs beside the PIN,
  // and the count-and-walk summary is for the moment more than one thing is wrong.
  const showSummary =
    (validation.submitted && validation.invalid.length > 0) ||
    unmappedServerError;

  function change(patch: Parameters<typeof buffer.change>[0]) {
    buffer.change(patch);
    // #618: publish the values the card NOW holds, so the preview and the input
    // are never a keystroke apart. Only the locality is published - the PIN, the
    // line and the city are not on the public projection (#619 widens that set),
    // and publishing a field nothing renders would be publishing to nowhere.
    if (fields != null) {
      publish("address", addressDraftFromFields({ ...fields, ...patch }));
    }
    // The pass re-runs on the merged value, which is what clears the message the
    // moment the PIN becomes usable rather than at the next submit.
    validation.changed(patch);
    refused.clear();
    attemptKey.current = null;
  }

  // §9.4: a failed submit takes focus to the offending field. The PIN is the only
  // field client validation can name, so that is the target; a refusal that names
  // no mappable field takes the first input rather than a guess at a nearer one.
  // A server PIN refusal focuses the PIN itself, which is what makes its
  // `aria-describedby` message the first thing announced rather than something
  // the doctor has to find. The client half is gated on `submitted` so a blur can
  // never yank focus back to the field the doctor just left.
  useEffect(() => {
    if (!validation.submitted) return;
    if (pinInvalid || unmappedServerError) {
      (pinInvalid ? pinRef.current : firstPartRef.current)?.focus();
    } else if (serverPinError) {
      pinRef.current?.focus();
    }
  }, [validation.submitted, pinInvalid, unmappedServerError, serverPinError]);

  // The first navigation guard in this app. Registered with the dirty flag and
  // removed with it, so a clean card adds no listener and a saved card stops
  // prompting: `addEventListener` returns this exact function, so the removal
  // cannot drift from the registration.
  useEffect(() => {
    if (!buffer.dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      // The legacy assignment is still what makes Chrome show its own prompt; the
      // modern `returnValue` is a no-op there, so setting it is harmless.
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [buffer.dirty]);

  async function saveAddress(): Promise<SectionSaveResult> {
    if (fields == null) return { status: "declined" };

    const problems = validation.submit();
    refused.clear();
    if (problems.length > 0) return { status: "declined" };

    const attempt = attemptKey.current ?? idempotencyKey();
    attemptKey.current = attempt;
    try {
      const answer = await updateDoctorProfileAddress(
        addressUpdateFromFields(fields),
        attempt,
      );
      // Cleared, not stale: the next edit is a new attempt, and this one has
      // landed, so there is no attempt left to retry.
      attemptKey.current = null;
      // The failed-submit context is over, so the next submit is a first submit
      // again rather than inheriting a summary and a focus walk from a save that
      // has since worked.
      validation.settled();
      setBelt({
        outside: answer.outside_peri_urban_belt,
        distanceKm: answer.distance_from_belt_centre_km,
      });
      // The shared source takes the whole answer, so the assembled display string
      // and the moved position reach the account menu and the chrome at once,
      // which is what a write that moves the directory listing is for (ADR-0021).
      //
      // It does NOT clear this card's dirty flag, and that is the buffer's own
      // rule rather than this card's choice: the reply is just another answer, so
      // a doctor who kept typing across the save must not lose those keystrokes.
      adoptProfile(answer);
      return { status: "saved" };
    } catch (err) {
      // The failure path adopts NOTHING and clears NOTHING. Not the answer seam,
      // not the dirty flag, not the attempt key: the retry is the same attempt
      // and must reuse its key. Every other section's unsaved buffer therefore
      // keeps its own edits, and so does this one (AC 3).
      if (err instanceof ApiError) {
        refused.record(err);
        return { status: "failed", failure: { traceId: err.traceId } };
      }
      // Not an envelope: a shape-guard failure or a transport bug, so there are no
      // validated details to place, and the shell's inline retry link is the whole
      // presentation. Auto-retry stays off either way (§9.1).
      return { status: "failed", failure: {} };
    }
  }

  if (fields == null) return null;

  const pinFlag = pinInvalid || serverPinError;

  return (
    <ProfileSectionShell
      title={t.addressSectionTitle}
      help={t.addressSectionHelp}
      anchorId={PROFILE_ANCHORS.address}
      testId="profile-address-card"
      save={{
        onSave: saveAddress,
        dirty: buffer.dirty,
        edits: buffer.edits,
        label: t.save,
        savedLabel: t.addressSaved,
        unsavedLabel: t.unsavedChanges,
        failureMessage: t.addressSaveFailed,
        buttonTestId: "profile-address-save",
        savedTestId: "profile-address-saved",
        unsavedTestId: "profile-address-unsaved",
      }}
    >
      {showSummary && (
        <div
          className="mb-3 rounded-md border border-danger-border bg-danger-soft px-3 py-2 text-sm text-danger"
          // Assertive, because this is the announcement of a failed submit and it
          // states the count (§9.4). The per-field line under the PIN input is the
          // quieter statement about one field, wired by `aria-describedby`.
          role="alert"
          aria-live="assertive"
          data-testid="profile-address-summary"
        >
          {validation.submitted && validation.invalid.length > 0 && (
            <p data-testid="profile-address-summary-count">
              {t.invalidSummary(validation.invalid.length)}
            </p>
          )}
          {unmappedServerError && (
            <p data-testid="profile-address-unmapped">{t.unmappedField}</p>
          )}
        </div>
      )}

      <div className="space-y-4">
        <ProfileField
          id="profile-address-line"
          label={t.addressLineLabel}
          help={t.addressLineHelp}
        >
          <input
            id="profile-address-line"
            ref={firstPartRef}
            type="text"
            maxLength={ADDRESS_LIMITS.addressLine}
            value={fields.address_line}
            onChange={(event) => change({ address_line: event.target.value })}
            className={fieldClassName(false)}
            data-testid="profile-address-line"
          />
        </ProfileField>

        <ProfileField
          id="profile-address-landmark"
          label={t.addressLandmarkLabel}
        >
          <input
            id="profile-address-landmark"
            type="text"
            maxLength={ADDRESS_LIMITS.landmark}
            value={fields.landmark}
            onChange={(event) => change({ landmark: event.target.value })}
            className={fieldClassName(false)}
            data-testid="profile-address-landmark"
          />
        </ProfileField>

        <div className="flex flex-wrap gap-4">
          <div className="min-w-40 flex-1">
            <ProfileField
              id="profile-address-locality"
              label={t.addressLocalityLabel}
            >
              <input
                id="profile-address-locality"
                type="text"
                maxLength={ADDRESS_LIMITS.locality}
                value={fields.locality}
                onChange={(event) => change({ locality: event.target.value })}
                className={fieldClassName(false)}
                data-testid="profile-address-locality"
              />
            </ProfileField>
          </div>
          <div className="min-w-40 flex-1">
            <ProfileField id="profile-address-city" label={t.addressCityLabel}>
              <input
                id="profile-address-city"
                type="text"
                maxLength={ADDRESS_LIMITS.city}
                value={fields.city}
                onChange={(event) => change({ city: event.target.value })}
                className={fieldClassName(false)}
                data-testid="profile-address-city"
              />
            </ProfileField>
          </div>
        </div>

        <div className="w-40">
          <ProfileField
            id="profile-address-pin"
            label={t.addressPinLabel}
            help={t.addressPinHelp}
          >
            <input
              id="profile-address-pin"
              ref={pinRef}
              type="text"
              inputMode="numeric"
              maxLength={6}
              value={fields.pin_code}
              onChange={(event) => change({ pin_code: event.target.value })}
              // #623: the blur check the three sibling cards already had. Marking
              // the field touched here is what makes the message appear when the
              // doctor leaves the PIN - while the answer is still in their head -
              // rather than only after they press Save and are told about it.
              onBlur={() => validation.blur(PIN_PATH)}
              aria-invalid={pinFlag}
              aria-describedby={pinFlag ? PIN_ERROR_ID : undefined}
              className={fieldClassName(pinFlag)}
              data-testid="profile-address-pin"
            />
          </ProfileField>
        </div>

        {/* The two derived rows (AC 2). Read-only because they are not the doctor's
            to declare: they follow from the PIN code. Empty today, because the
            profile projection and the address write's answer both stop at the PIN
            (see addressFields.ts) - shown with their labels and a plain "not
            available" value rather than as a promise, a spinner over an input the
            doctor is typing into, or a call to a resolve endpoint this API does
            not have. */}
        <div className="flex flex-wrap gap-4 border-t border-hairline pt-4">
          <div className="min-w-40 flex-1">
            <ProfileField
              id="profile-address-district"
              label={t.addressDistrictLabel}
              help={t.addressDerivedHelp}
            >
              <input
                id="profile-address-district"
                type="text"
                readOnly
                value={fields.district}
                className={`${inputClassName} bg-accent-soft text-txt-muted`}
                data-testid="profile-address-district"
              />
            </ProfileField>
          </div>
          <div className="min-w-40 flex-1">
            <ProfileField
              id="profile-address-state"
              label={t.addressStateLabel}
              help={t.addressDerivedHelp}
            >
              <input
                id="profile-address-state"
                type="text"
                readOnly
                value={fields.state}
                className={`${inputClassName} bg-accent-soft text-txt-muted`}
                data-testid="profile-address-state"
              />
            </ProfileField>
          </div>
          {(fields.district === "" || fields.state === "") && (
            <p
              className="w-full text-xs text-txt-muted"
              data-testid="profile-address-derived-empty"
            >
              {t.addressDerivedEmpty}
            </p>
          )}
        </div>
      </div>

      {/* The one field-level message on the page, under the one input that can
          carry one. Client-side and server-side refusals share the position but
          not the copy: the client's states the shape it can state, the server's is
          the expected-4xx message for a code it cannot place. */}
      {pinFlag && (
        <p
          id={PIN_ERROR_ID}
          className="mt-1 text-sm text-danger"
          // `alert` for the client-side refusal, which is the invalid-field line
          // the accessibility floor asks for. A server refusal takes no role: it
          // arrived after an attempt the doctor just made, it is wired to the input
          // by `aria-describedby`, and focus is on the input to read it - so a
          // second interrupting announcement would only compete with the first.
          role={serverPinError ? undefined : "alert"}
          data-testid="profile-address-pin-error"
        >
          {serverPinError ? t.addressPinUnresolved : t.addressPinInvalid}
        </p>
      )}

      {belt?.outside && (
        // A notice, never an invalid-field line and never a banner: the save
        // succeeded, and what the position changes is where this doctor's own
        // listing surfaces to patients searching nearby.
        <p
          className="mt-3 rounded-md border border-hairline bg-accent-soft px-3 py-2 text-sm text-txt"
          data-testid="profile-address-belt-warning"
        >
          {t.addressOutsideBelt(String(Math.round(belt.distanceKm)))}
        </p>
      )}
    </ProfileSectionShell>
  );
}
