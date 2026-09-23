"use client";

// PHASE-2.6 T06 (#197): the single top-right account cluster (blueprint §2.6)
// - phone, role badge, switch-role, and logout consolidated into one dropdown
// behind an avatar-icon trigger, matching the finalized PROTO-PHASE-2.6
// views. Extracted from the pre-T06 Topbar.
// #521: role-aware trigger - the patient branch renders the shared Avatar
// (photo_ref -> name initial -> person icon) with no name label beside it;
// staff roles (doctor/partner/operator) keep the phone-digit trigger and
// dropdown verbatim because their names/photos are not in the session
// payload. The full phone stays hidden until the menu opens. data-session-
// resolved carries only a resolved/pending flag for e2e settle guards (avatar
// text is no longer a digit signal) - never the phone itself, so the closed
// trigger leaks nothing.
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
import type { StoredPatientProfile } from "@/lib/profile/api";
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
// #525/#526 share the stale-session identity resolve (name -> masked phone ->
// "Subject #id"); the helper lives with the mobile account card and is the
// single source of it.
import { accountIdentity } from "./BottomTabs";

// Stale sessions can carry a user whose JSON predates the T05 additive
// phone field (absent or empty at runtime despite the non-optional type);
// the staff label row degrades to the subject id rather than crashing
// (#199 handoff). Same convention accountIdentity applies for the patient.
function identityLine(user: { phone?: string; id: number } | null): string {
  if (!user) {
    return "";
  }
  return user.phone || `Subject #${user.id}`;
}

// The "Complete your profile" CTA shows only while the saved profile is absent
// or fails the care-action basics gate (name + age + gender, spec #520). The
// single source of that gate is the wizard's basicsComplete; the saved profile
// is mapped into the draft shape it expects, so an invalid stored age or an
// unset gender counts as incomplete the same way the profile page judges it.
function savedBasicsComplete(saved: StoredPatientProfile | null | undefined) {
  return saved ? basicsComplete(serverProfileToDraft(saved)) : false;
}

export function AccountMenu() {
  const { user, selectedRole, switchRole, logout } = useAuth();
  const profile = useOptionalProfile();
  const { lang } = useLang();
  const strings = STRINGS[lang].nav;
  const menuStrings = STRINGS[lang].accountMenu;
  const currentRole = resolveRole(selectedRole);
  const isPatient = currentRole === "patient";
  const saved = profile?.savedProfile;
  const otherRoles = (user?.roles ?? [])
    .filter(isAppRole)
    .filter((role) => role !== currentRole);

  const roleSwitchItems = otherRoles.map((role) => (
    <DropdownMenuItem
      key={role}
      onSelect={() => switchRole(role)}
      data-testid={`switch-to-${role}`}
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
      className="text-danger focus:bg-danger-soft focus:text-danger"
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
          className={cn(
            "h-9 w-9 items-center justify-center rounded-full bg-accent-soft text-sm font-semibold text-accent-strong hover:bg-accent-border",
            isPatient ? "hidden lg:inline-flex" : "flex",
          )}
        >
          {isPatient ? (
            <Avatar
              photoRef={saved?.photo_ref}
              name={saved?.name}
              className="h-full w-full text-inherit"
            />
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
                photoRef={saved?.photo_ref}
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
            >
              <Link href="/patient/profile">{strings.profileSettings}</Link>
            </DropdownMenuItem>
            {!savedBasicsComplete(saved) && (
              <DropdownMenuItem
                asChild
                data-testid="account-menu-complete-profile"
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
            <DropdownMenuLabel className="flex items-center justify-between gap-2 font-normal">
              <span className="text-sm text-txt">{identityLine(user)}</span>
              {roleBadge}
            </DropdownMenuLabel>
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
