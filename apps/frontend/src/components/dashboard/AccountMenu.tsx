"use client";

// PHASE-2.6 T06 (#197): the single top-right account cluster (blueprint §2.6)
// - phone, role badge, switch-role, and logout consolidated into one dropdown
// behind an avatar-icon trigger, matching the finalized PROTO-PHASE-2.6
// views. Extracted from the pre-T06 Topbar.
// #521: role-aware trigger - the patient branch renders the shared Avatar
// (photo_ref -> name initial -> person icon) with no name label beside it;
// staff roles keep the phone-digit trigger and dropdown verbatim because
// their names/photos are not in the session payload. The full phone stays
// hidden until the menu opens. data-session-resolved carries only a
// resolved/pending flag for e2e settle guards (avatar text is no longer a
// digit signal) - never the phone itself, so the closed trigger leaks
// nothing.
// #538: the doctor branch gains an account avatar entry point - the same
// Avatar primitive. Partner/operator keep the phone-digit trigger unchanged.
// #569: and that disc is now hydrated: the shell reads the doctor's own
// profile projection once and threads it down, the shared photo resolver turns
// its `photo_ref` into an object URL over the doctor's private byte reader, and
// anything that does not resolve - a blip, or media the backend reports absent -
// degrades to the same person icon. One read feeds the trigger and the dropdown
// header, so the menu itself never fetches.
// #567: doctor-ness is an INPUT now, not an inference. The identity layer
// grants exactly three roles (patient|partner|operator), so a doctor is a
// *partner whose partner type is doctor* and the session can never answer
// "doctor" - every affordance gated on asking it was unreachable in
// production. The route group already pins the shell role, so the shell
// threads its own role down (AppShell -> Topbar -> AccountMenu) and that
// answer is authoritative. The session role still governs the patient branch
// and the non-doctor staff branch, unchanged.
// #525: on phones the patient trigger is hidden below `lg` (account lives in
// the More sheet); staff visibility is unchanged.
// #526: the patient dropdown becomes a real account menu - an identity header
// (avatar, name or masked phone, full E.164 phone), a live Profile & Settings
// link, a "Complete your profile" CTA gated on missing basics, role switching
// for multi-role accounts, and a red dictionary-driven "Log out". Stale
// sessions still degrade to "Subject #id" and can still log out. The staff
// branch stays as close to today's dropdown as the #520 vocabulary and the
// i18n rules allow: same phone-digit trigger, same phone/badge layout, same
// menu width and a non-accented Log out row - only the literal row copy moves
// onto the shared nav.logOut string ("Log out", which the mobile More sheet
// already used) instead of the old hardcoded English "Logout". Everything is
// dictionary-driven (nav.* and accountMenu.*, both locales); the identity
// degrade is the shared accountIdentity (which owns the mask format).

import Link from "next/link";

import { useAuth } from "@/lib/auth/AuthContext";
import { useOptionalProfile } from "@/lib/profile/ProfileContext";
import { useProfilePhotoSource } from "@/lib/profile/useProfilePhotoSource";
import type { ProfilePhotoReader } from "@/lib/profile/useProfilePhotoSource";
import { fetchPatientPhoto } from "@/lib/profile/api";
import { fetchDoctorProfilePhoto } from "@/lib/doctor/api";
import type { StoredPatientProfile } from "@/lib/profile/api";
import type { DoctorProfileView } from "@/lib/doctor/api";
import {
  basicsComplete,
  serverProfileToDraft,
} from "@/lib/profile/profileState";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Avatar } from "@/components/ui/avatar";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { cn } from "@/lib/utils";

import { isAppRole, resolveRole, roleLabel } from "./types";
import type { Role } from "./types";
// #525/#526 share the stale-session identity resolve (name -> masked phone ->
// "Subject #id"); the helper lives with the mobile account card and is the
// single source of it.
import { accountIdentity } from "./BottomTabs";

// Stale sessions can carry a user whose JSON predates the T05 additive
// phone field (absent or empty at runtime despite the non-optional type);
// the staff label row degrades to the subject id rather than crashing
// (#199 handoff). Only the mask-free full-phone branch differs from the
// patient convention - the "Subject #id" format itself is single-sourced in
// accountIdentity, so the fallback never forks it.
function identityLine(user: { phone?: string; id: number } | null): string {
  if (!user) {
    return "";
  }
  return user.phone || accountIdentity(null, user);
}

// #527: every patient dropdown row is a >=44px tap target (spec #520 story
// 30). Shared so a future patient row cannot silently drop the contract; the
// staff branch deliberately never uses it (staff stays verbatim).
const patientMenuItemClass = "min-h-11";

// The "Complete your profile" CTA shows only while the saved profile is absent
// or fails the care-action basics gate (name + age + gender, spec #520). The
// single source of that gate is the wizard's basicsComplete; the saved profile
// is mapped into the draft shape it expects, so an invalid stored age or an
// unset gender counts as incomplete the same way the profile page judges it.
function savedBasicsComplete(saved: StoredPatientProfile | null | undefined) {
  return saved ? basicsComplete(serverProfileToDraft(saved)) : false;
}

// #567: `shellRole` is the role of the shell this menu renders inside, threaded
// down from the route group's AppShell. It is deliberately not a boolean
// "amIADoctor" (that would push the branch decision back down to this leaf) and
// not a bare `role` (two roles are in play here, and calling them both `role` is
// how the session's role ended up answering for doctor-ness in the first place).
export function AccountMenu({
  shellRole,
  doctorProfile,
}: {
  shellRole: Role;
  /**
   * #569: the doctor shell's own private profile projection. The shell read it
   * once, beside its open-case count, so the menu issues no request of its own;
   * `photo_ref` hydrates the avatar and `practice_name` is the only human
   * readable name a doctor has anywhere in the frontend. Undefined for every
   * non-doctor shell, which never fetches it.
   */
  doctorProfile?: DoctorProfileView;
}) {
  const { user, selectedRole, switchRole, logout } = useAuth();
  const profile = useOptionalProfile();
  const { lang } = useLang();
  const strings = STRINGS[lang].nav;
  const menuStrings = STRINGS[lang].accountMenu;
  // #538: the patient and doctor branches share the 36px disc styling; only
  // the doctor entry drops the name/photo so it falls back to the person icon.
  const avatarClassName =
    "h-9 w-9 bg-accent-soft text-sm font-semibold text-accent-strong hover:bg-accent-border";
  // The session's role still decides the patient and non-doctor-staff branches
  // and the role badge, exactly as before.
  const currentRole = resolveRole(selectedRole);
  const isPatient = currentRole === "patient";
  // #567: and only the shell decides doctor-ness.
  const isDoctor = shellRole === "doctor";
  const saved = profile?.savedProfile;
  // #557: the stored photo ref is an opaque object key (ADR-0020 D1), so it is
  // the shared resolver - not the primitive - that makes it renderable. One
  // resolved source covers every avatar on a ref, so the trigger and the
  // dropdown header cost a single read between them.
  // #569: ONE branch, because the ref and the transport that can read it must
  // come from the same account. Two independent selections would pair a
  // patient's ref with the doctor's byte endpoint on a dual-role session in the
  // doctor shell, and the two endpoints serve disjoint actor-namespaced
  // namespaces. Non-doctor staff resolve nothing at all - a lab or an operator
  // keeps the phone-digit trigger and must not read a photo nothing shows. The
  // seam holds the reader in a ref rather than a dependency, so selecting it
  // costs no extra read.
  const [photoRef, photoReader]: [string | null, ProfilePhotoReader] = isPatient
    ? [saved?.photo_ref ?? null, fetchPatientPhoto]
    : isDoctor
      ? [doctorProfile?.photo_ref ?? null, fetchDoctorProfilePhoto]
      : [null, fetchPatientPhoto];
  const { src: photoSrc } = useProfilePhotoSource(photoRef, photoReader);
  const otherRoles = (user?.roles ?? [])
    .filter(isAppRole)
    .filter((role) => role !== currentRole);

  const roleSwitchItems = otherRoles.map((role) => (
    <DropdownMenuItem
      key={role}
      onSelect={() => switchRole(role)}
      data-testid={`switch-to-${role}`}
      className={isPatient ? patientMenuItemClass : undefined}
    >
      {menuStrings.switchRole(roleLabel(role))}
    </DropdownMenuItem>
  ));

  // #526: patient only - the red, accented Log out row; the staff branch keeps
  // today's neutral row so only the patient account menu surfaces the red
  // sign-out treatment.
  const redLogoutItem = (
    <DropdownMenuItem
      onSelect={() => logout()}
      data-testid="logout-button"
      className={cn(
        patientMenuItemClass,
        "text-danger focus:bg-danger-soft focus:text-danger",
      )}
    >
      {strings.logOut}
    </DropdownMenuItem>
  );

  // Shared by both branches: the role chip in the header's right slot.
  const roleBadge = (
    <span
      className="shrink-0 rounded bg-accent-soft px-1.5 py-0.5 text-xs font-medium text-accent"
      data-testid="account-menu-role-badge"
    >
      {roleLabel(currentRole)}
    </span>
  );

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label={menuStrings.trigger}
          data-testid="account-menu"
          data-session-resolved={user ? "true" : "false"}
          // #525 mobile placement: the patient account lives in exactly one
          // place on phones - the More sheet - so the top-right circle is
          // hidden below `lg` (the pure-CSS bottom-tab breakpoint). Staff
          // roles keep the phone-digit trigger at every width.
          // #527: the patient branch grows the pointer target to 44px (spec
          // #520 story 30) while the avatar disc itself stays 36px - the disc
          // styling lives on the Avatar so the visible circle is unchanged and
          // staff keeps its verbatim 36px disc.
          className={cn(
            "items-center justify-center rounded-full",
            isPatient
              ? "hidden h-11 w-11 lg:inline-flex"
              : "flex h-9 w-9 bg-accent-soft text-sm font-semibold text-accent-strong hover:bg-accent-border",
          )}
        >
          {isPatient ? (
            <Avatar
              photoRef={photoSrc}
              name={saved?.name}
              className={avatarClassName}
            />
          ) : isDoctor ? (
            // #538: the doctor account avatar entry point. #569: fed from the
            // shell-held profile projection through the shared resolver, so a
            // stored photo shows as the bytes the backend streams and never as
            // the stored key, and every failure - a blip, or media the backend
            // says is not there - degrades to the person icon. No `name`, so a
            // doctor with no photo keeps the icon rather than an initial.
            <Avatar photoRef={photoSrc} className={avatarClassName} />
          ) : (
            (user?.phone || "?").slice(-2)
          )}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className={isPatient ? "w-60" : "w-52"}>
        {isPatient ? (
          <>
            <DropdownMenuLabel className="flex items-center gap-3 font-normal">
              <Avatar
                photoRef={photoSrc}
                name={saved?.name}
                className="h-10 w-10 shrink-0 bg-accent-soft text-base font-semibold text-accent-strong"
              />
              <span className="min-w-0 flex-1">
                <span
                  data-testid="account-menu-identity"
                  className="block truncate text-sm font-semibold text-txt"
                >
                  {accountIdentity(saved?.name, user)}
                </span>
                {user?.phone && (
                  <span className="block truncate text-xs leading-5 text-txt-muted">
                    {user.phone}
                  </span>
                )}
              </span>
              {roleBadge}
            </DropdownMenuLabel>
            <DropdownMenuItem
              asChild
              data-testid="account-menu-profile-settings"
              className={patientMenuItemClass}
            >
              <Link href="/patient/profile">{strings.profileSettings}</Link>
            </DropdownMenuItem>
            {!savedBasicsComplete(saved) && (
              <DropdownMenuItem
                asChild
                data-testid="account-menu-complete-profile"
                className={patientMenuItemClass}
              >
                <Link href="/patient/profile">
                  {menuStrings.completeProfile}
                </Link>
              </DropdownMenuItem>
            )}
            {roleSwitchItems}
            <DropdownMenuSeparator />
            {redLogoutItem}
          </>
        ) : (
          <>
            <DropdownMenuLabel
              className={cn(
                "flex items-center font-normal",
                // A doctor's row is a three-part flex (avatar, identity, badge);
                // every other menu keeps the two-part spread verbatim. #570 owns
                // this header's identity layout.
                isDoctor ? "gap-3" : "justify-between gap-2",
              )}
            >
              {/* #569: the doctor's dropdown header reads the same resolved
                  source the trigger is already showing, so two avatars on one
                  ref still cost one read. Gated on doctor-ness, so the avatar
                  treatment does not leak onto a lab or an operator menu. */}
              {isDoctor && (
                <Avatar
                  photoRef={photoSrc}
                  className="h-10 w-10 shrink-0 bg-accent-soft text-base font-semibold text-accent-strong"
                />
              )}
              <span className="text-sm text-txt">{identityLine(user)}</span>
              {roleBadge}
            </DropdownMenuLabel>
            {/* #543: the doctor's own Profile page is the entry point this
                avatar opens into; the label reuses the nav dictionary word. */}
            {isDoctor && (
              <DropdownMenuItem
                asChild
                data-testid="account-menu-doctor-profile"
              >
                <Link href="/doctor/profile">{strings.profile}</Link>
              </DropdownMenuItem>
            )}
            {roleSwitchItems}
            {otherRoles.length > 0 && <DropdownMenuSeparator />}
            <DropdownMenuItem
              onSelect={() => logout()}
              data-testid="logout-button"
            >
              {strings.logOut}
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
