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

// #570: and the doctor's branch reaches the patient's treatment - the same
// shared identity header, the same wider content, full-size rows, an
// unconditional divider and the danger-accented sign-out - supplied with the
// practice name and the photo the shell already read. Only the doctor's branch
// changes: the non-doctor staff branch keeps its two-part phone/badge header,
// its narrow content and its verbatim rows, and the patient branch renders
// exactly as before.

import Link from "next/link";
import type { ReactNode } from "react";

import { useAuth } from "@/lib/auth/AuthContext";
import type { User } from "@/lib/auth/AuthContext";
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

// #527: every row of a real account menu (patient or doctor) is a >=44px tap
// target (spec #520 story 30). Shared so a future row cannot silently drop the
// contract. The non-doctor staff branch deliberately never uses it - that menu
// stays verbatim.
const menuRowClass = "min-h-11";

// The "Complete your profile" CTA shows only while the saved profile is absent
// or fails the care-action basics gate (name + age + gender, spec #520). The
// single source of that gate is the wizard's basicsComplete; the saved profile
// is mapped into the draft shape it expects, so an invalid stored age or an
// unset gender counts as incomplete the same way the profile page judges it.
function savedBasicsComplete(saved: StoredPatientProfile | null | undefined) {
  return saved ? basicsComplete(serverProfileToDraft(saved)) : false;
}

// #570: the identity header, ONE component with two suppliers. The patient
// supplies its saved profile's name and the ref that name's account resolved;
// the doctor supplies the shell-held practice name and the ref the doctor
// transport resolved (#569). They differ in exactly those values, so the header
// is parameterised rather than copied - and the patient's rendering is
// unchanged by the doctor's arrival.
type IdentityHeaderProps = {
  // The human-readable identity on the first line, resolved through the shared
  // name -> masked phone -> "Subject #id" chain.
  name: string | null | undefined;
  // The session, for that resolve and for the full E.164 on the second line. The
  // full number is dropped rather than faked when the session has none.
  user: User | null;
  // The already-resolved avatar source (an object URL) or null. Never the stored
  // ref, which is opaque and not browser-reachable (ADR-0020 D1).
  photoSrc: string | null;
  // What the avatar falls back to when no photo resolves. The patient passes the
  // name so the disc shows an initial; a doctor passes nothing and keeps the
  // person icon (#538) - a practice name has no person to take an initial from.
  // The one thing the two suppliers do not agree on, so it is an explicit input
  // rather than a silent difference.
  avatarName?: string | null;
  // The shared role chip, rendered in the right slot.
  badge: ReactNode;
};

function IdentityHeader({
  name,
  user,
  photoSrc,
  avatarName,
  badge,
}: IdentityHeaderProps) {
  return (
    <DropdownMenuLabel className="flex items-center gap-3 font-normal">
      <Avatar
        photoRef={photoSrc}
        name={avatarName}
        className="h-10 w-10 shrink-0 bg-accent-soft text-base font-semibold text-accent-strong"
      />
      <span className="min-w-0 flex-1">
        <span
          data-testid="account-menu-identity"
          className="block truncate text-sm font-semibold text-txt"
        >
          {accountIdentity(name, user)}
        </span>
        {user?.phone && (
          <span className="block truncate text-xs leading-5 text-txt-muted">
            {user.phone}
          </span>
        )}
      </span>
      {badge}
    </DropdownMenuLabel>
  );
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
  // and the non-doctor badges, exactly as before. #570: inside the doctor shell
  // the badge follows the shell instead - see roleBadge below.
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
  // #570: the patient and the doctor are the two real account menus - each
  // opens onto an identity header - so both get the wider content that header
  // needs and the full-size rows. The non-doctor staff branch keeps the narrower
  // content and its verbatim rows.
  const isRealAccountMenu = isPatient || isDoctor;

  const roleSwitchItems = otherRoles.map((role) => (
    <DropdownMenuItem
      key={role}
      onSelect={() => switchRole(role)}
      data-testid={`switch-to-${role}`}
      className={isRealAccountMenu ? menuRowClass : undefined}
    >
      {menuStrings.switchRole(roleLabel(role))}
    </DropdownMenuItem>
  ));

  // #526: the red, accented Log out row, for whichever account menu is a real
  // one - the patient's, and since #570 the doctor's. The non-doctor staff branch
  // keeps today's neutral row. The test id is an input because the doctor's row
  // is a third element of this shape and an id is what tells the three apart in
  // a test; the patient keeps the historic one.
  const redLogoutItem = (testId: string) => (
    <DropdownMenuItem
      onSelect={() => logout()}
      data-testid={testId}
      className={cn(
        menuRowClass,
        "text-danger focus:bg-danger-soft focus:text-danger",
      )}
    >
      {strings.logOut}
    </DropdownMenuItem>
  );

  // The role chip in a header's right slot, from the same ROLE_LABELS vocabulary
  // every role label in the app reads - one factory so the chip is one element
  // with one test id wherever it appears, and so each branch states the role it
  // is labelling. #570: a doctor is a `partner` by grant and a doctor by partner
  // *type*, so the session's role alone would label the doctor's chip "Partner";
  // the shell knows which partner this is, and the doctor's branch asks it.
  const roleBadgeFor = (role: Role) => (
    <span
      className="shrink-0 rounded bg-accent-soft px-1.5 py-0.5 text-xs font-medium text-accent"
      data-testid="account-menu-role-badge"
    >
      {roleLabel(role)}
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
      <DropdownMenuContent
        align="end"
        className={isRealAccountMenu ? "w-60" : "w-52"}
      >
        {isPatient ? (
          <>
            <IdentityHeader
              name={saved?.name}
              avatarName={saved?.name}
              user={user}
              photoSrc={photoSrc}
              badge={roleBadgeFor(currentRole)}
            />
            <DropdownMenuItem
              asChild
              data-testid="account-menu-profile-settings"
              className={menuRowClass}
            >
              <Link href="/patient/profile">{strings.profileSettings}</Link>
            </DropdownMenuItem>
            {!savedBasicsComplete(saved) && (
              <DropdownMenuItem
                asChild
                data-testid="account-menu-complete-profile"
                className={menuRowClass}
              >
                <Link href="/patient/profile">
                  {menuStrings.completeProfile}
                </Link>
              </DropdownMenuItem>
            )}
            {roleSwitchItems}
            <DropdownMenuSeparator />
            {redLogoutItem("logout-button")}
          </>
        ) : isDoctor ? (
          // #570: the doctor's menu is the patient's, minus the one row a doctor
          // cannot have - Complete your profile, gated on a patient profile this
          // shell never holds. The Profile row, role switching, the
          // unconditional divider and the accented sign-out are the patient's
          // own components, and the name and photo arrive from the shell (#569):
          // the menu still fetches nothing.
          <>
            <IdentityHeader
              name={doctorProfile?.practice_name}
              avatarName={null}
              user={user}
              photoSrc={photoSrc}
              badge={roleBadgeFor(shellRole)}
            />
            {/* #543: the doctor's own Profile page, one click from the avatar
                dropdown, now a full-size row like every other one here. */}
            <DropdownMenuItem
              asChild
              data-testid="account-menu-doctor-profile"
              className={menuRowClass}
            >
              <Link href="/doctor/profile">{strings.profile}</Link>
            </DropdownMenuItem>
            {roleSwitchItems}
            <DropdownMenuSeparator />
            {redLogoutItem("account-menu-doctor-logout")}
          </>
        ) : (
          <>
            <DropdownMenuLabel className="flex items-center justify-between gap-2 font-normal">
              <span className="text-sm text-txt">{identityLine(user)}</span>
              {roleBadgeFor(currentRole)}
            </DropdownMenuLabel>
            {roleSwitchItems}
            {otherRoles.length > 0 && <DropdownMenuSeparator />}
            <DropdownMenuItem
              onSelect={() => logout()}
              // The historic id, kept deliberately: it labels the neutral
              // sign-out row of the staff branch, which only ever renders when
              // the accented row above is not. See redLogoutItem.
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
