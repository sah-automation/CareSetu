"use client";

// #615 AC 3: the read-only credential list that is the verified band's content -
// what the platform derived and checked, lifted out of the page's
// `CredentialsCard` along with the `credentialExpiry` helper that decides what is
// still valid.
//
// The band decides where this list sits; this component does not decide whether
// it deserves a tick. Validity is read off each credential for DISPLAY only, and
// the band's tick comes from the projection's single `verified` flag, so the two
// can never tell a doctor two different stories (ADR-0011, blueprint §1.6). The
// activation row below is that flag's second read; the identity band's chip is
// its third.

import Link from "next/link";
import { BadgeCheck } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type {
  DoctorProfileCredential,
  DoctorProfileView,
} from "@/lib/doctor/api";
import { providerProfileHref } from "@/lib/directory/links";
import { STRINGS, type Dictionary } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { cn } from "@/lib/utils";

/**
 * What still counts as valid for display, or null when there is no expiry to
 * show (or no parseable date to show one from). A date the client cannot read
 * drops the claim rather than printing `Invalid Date` at a doctor.
 */
export function credentialExpiry(
  expiresAt: string | null,
  t: Dictionary["doctorProfile"],
  lang: "en" | "hi",
): string | null {
  if (expiresAt == null) return null;
  const date = new Date(expiresAt);
  if (Number.isNaN(date.getTime())) return null;
  return t.credentialExpires(
    date.toLocaleDateString(lang === "hi" ? "hi-IN" : "en-IN", {
      day: "numeric",
      month: "short",
      year: "numeric",
    }),
  );
}

export function ProfileCredentialList({
  profile,
}: {
  profile: Pick<DoctorProfileView, "credentials" | "partner_id" | "verified">;
}) {
  const { lang } = useLang();
  const t = STRINGS[lang].doctorProfile;

  return (
    <>
      {/* AC 3's "activation state", read off the one flag. It sits ABOVE the
          credential list on purpose: it is the verdict, and the list is the
          evidence, so a false flag is stated before the evidence rather than
          after it.

          The tick is rendered only when the flag is true. Per the glossary,
          verified is true iff the partner is active AND every required
          credential is unexpired and unrevoked, and "if the tick is gone, the
          card is gone" - so a tick drawn beside a stale list is the one claim
          this page must never make (ADR-0011, blueprint §1.6).

          The value is `verified ? t.verified : t.notVerified`, never a value
          recomputed from the credentials below: the client reading credential
          dates would be a second derivation site, and the two would eventually
          disagree. The list's own `credentialExpiry` labels are for display. */}
      <div
        className="flex flex-wrap items-center gap-2"
        data-testid="profile-activation-state"
      >
        <span className="text-sm font-medium text-txt">
          {t.activationStateLabel}
        </span>
        <Badge
          variant={profile.verified ? "default" : "secondary"}
          className={cn(
            "inline-flex items-center gap-1",
            profile.verified
              ? "bg-success-soft text-success-text"
              : "bg-accent-soft text-accent-strong",
          )}
        >
          {profile.verified && (
            <BadgeCheck aria-hidden="true" className="h-3.5 w-3.5" />
          )}
          {/* The name goes on the tick, not only on the text beside it: the icon
              is decorative, and the verdict it qualifies is already spelled out
              next to it. */}
          {profile.verified ? t.verified : t.notVerified}
        </Badge>
        {profile.verified && (
          <span className="sr-only">{t.verifiedTickLabel}</span>
        )}
      </div>

      {/* An h3 under the band's h2: the band says what kind of thing this is
          ("Checked by CareSetu") and this says what is in it, which is the
          heading a reader skipping through the page needs to land on. */}
      <h3 className="mt-4 text-sm font-semibold text-txt">
        {t.credentialsHeading}
      </h3>

      {profile.credentials.length === 0 ? (
        <p
          className="text-sm text-txt-muted"
          data-testid="profile-credentials-empty"
        >
          {t.credentialsEmpty}
        </p>
      ) : (
        <ul className="space-y-2">
          {profile.credentials.map(
            (credential: DoctorProfileCredential, index) => {
              const expiry = credentialExpiry(credential.expires_at, t, lang);
              // Two credentials can share a type, so the index keeps the keys
              // unique; the type alone would collide.
              return (
                <li
                  key={`${credential.credential_type}-${index}`}
                  data-testid="profile-credential"
                  className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-hairline px-3 py-2"
                >
                  <span className="text-sm text-txt">
                    {t.credentialType[
                      credential.credential_type as keyof typeof t.credentialType
                    ] ?? credential.credential_type}
                  </span>
                  <span className="flex flex-wrap items-center gap-2">
                    {expiry && (
                      <span
                        className="text-xs text-txt-muted"
                        data-testid="profile-credential-expiry"
                      >
                        {expiry}
                      </span>
                    )}
                    <span
                      data-testid="profile-credential-status"
                      className={cn(
                        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
                        credential.status === "verified"
                          ? "bg-success-soft text-success-text"
                          : "bg-accent-soft text-accent-strong",
                      )}
                    >
                      {t.credentialStatus[credential.status]}
                    </span>
                  </span>
                </li>
              );
            },
          )}
        </ul>
      )}

      {/* The public directory entry stays a read-only PREVIEW, never an editor
          here. It rides in this band because it is the one part of a doctor's
          public face the platform derives rather than the doctor declaring it,
          which is the same distinction the band itself draws. */}
      <div className="mt-4 border-t border-hairline pt-3">
        <h3 className="text-sm font-semibold text-txt">
          {t.publicPreviewHeading}
        </h3>
        <p className="mt-1 text-sm text-txt-muted">{t.publicPreviewHelp}</p>
        <Link
          href={providerProfileHref(profile.partner_id)}
          data-testid="profile-public-preview"
          className="mt-2 inline-flex items-center rounded-md border border-hairline bg-surface px-3 py-1.5 text-xs font-medium text-txt-sub transition-colors hover:border-accent-border hover:bg-accent-soft hover:text-accent-strong"
        >
          {t.publicPreviewAction}
        </Link>
      </div>
    </>
  );
}
