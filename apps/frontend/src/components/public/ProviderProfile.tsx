// PHASE-6 T06 (#312): the public provider profile at /providers/:id
// (blueprint §3.1 row 5, PROTO-PHASE-6 doctor-profile.html / partner-profile
// .html as the visual binding - `.profile-hero` mobile left-aligned, binding).
//
// #618: this is the FETCHING half, and it is now only the fetching half. The
// renderer it used to hold - every band, every copy string - moved to
// `ProviderProfileBody`, which takes a projection and owns no transport. The
// public page feeds it the API response and the doctor's profile page feeds it
// local form state, so the two surfaces cannot drift.
//
// What stays here is exactly what is about the REQUEST, and each piece is here for
// a reason that would not survive the move:
//
//   - the `<main>` and the page width, because the console's own `<main>` must not
//     become a second one;
//   - the load-status machine (skeleton / not-found / error), because a projection
//     that does not exist yet has nothing to render;
//   - the retry affordance, because its nonce IS the request's state;
//   - the mount-once `partner.selected` emission, because opening a public profile
//     is a patient picking a provider. The doctor's live preview must NOT emit it,
//     and a renderer that a patient-picking page and an editor both mount is exactly
//     the place that mistake would be made.
//
// Truthfulness rules (FEAT-005/ADR-0011): the verified badge and per-credential
// state render only from the backend-derived fields the profile API returns. A 404
// from the API (partner not `[Active]`, no index entry, or an invalid credential)
// renders the clear not-found state; any other failure renders the retryable error.

"use client";

import Link from "next/link";

import { useEffect, useState } from "react";

import { ProviderProfileBody } from "./ProviderProfileBody";
import { emitPartnerSelected } from "@/lib/directory/emit";
import {
  fetchProviderProfile,
  type ProviderProfile,
} from "@/lib/directory/profile";
import { DIRECTORY_ROUTE } from "@/lib/directory/links";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

type LoadStatus = "loading" | "error" | "not-found" | "ready";

interface ProviderProfileProps {
  partnerId: number;
}

export function ProviderProfile({ partnerId }: ProviderProfileProps) {
  const { lang } = useLang();
  const t = STRINGS[lang].providerProfile;
  const [status, setStatus] = useState<LoadStatus>("loading");
  const [profile, setProfile] = useState<ProviderProfile | null>(null);
  const [retryNonce, setRetryNonce] = useState(0);

  useEffect(() => {
    // T6 (#328): opening a provider profile is one interaction - fire the
    // anonymous `partner.selected` pick exactly once on mount (mount-only
    // effect; never re-fires on re-render or retry). Fire-and-forget.
    emitPartnerSelected({
      partner_id: partnerId,
      partner_type: null,
      source: "provider_profile",
    });
  }, [partnerId]);

  useEffect(() => {
    let active = true;
    setStatus("loading");
    fetchProviderProfile(partnerId)
      .then((result) => {
        if (!active) return;
        if (result.status === "found") {
          setProfile(result.profile);
          setStatus("ready");
        } else {
          setProfile(null);
          setStatus("not-found");
        }
      })
      .catch((err: unknown) => {
        // Operational failure (error-handling-observability §2): logged and
        // surfaced as the retryable error state, distinct from not-found.
        console.error("[provider-profile] load failed:", err);
        if (active) {
          setProfile(null);
          setStatus("error");
        }
      });
    return () => {
      active = false;
    };
  }, [partnerId, retryNonce]);

  if (status === "loading") {
    return (
      <main
        className="mx-auto w-full max-w-[760px] px-4 pb-12 pt-6"
        data-testid="profile-loading"
        role="status"
      >
        <p className="sr-only">{t.loadingProfile}</p>
        <div className="h-24 animate-pulse rounded-lg border border-hairline bg-hairline-soft/60" />
        <div className="mt-3 h-20 animate-pulse rounded-lg border border-hairline bg-hairline-soft/60" />
      </main>
    );
  }

  if (status === "not-found") {
    return (
      <main className="mx-auto w-full max-w-[760px] px-4 pb-12 pt-6">
        <nav aria-label="Breadcrumb" className="text-sm text-txt-muted">
          <Link href={DIRECTORY_ROUTE} className="hover:underline">
            {t.breadcrumbDirectory}
          </Link>
        </nav>
        <div
          data-testid="profile-not-found"
          className="mt-6 rounded-lg border border-hairline bg-surface p-6 text-center"
        >
          <p className="font-medium text-txt">{t.notFoundTitle}</p>
          <p className="mx-auto mt-1 max-w-md text-sm text-txt-muted">
            {t.notFoundBody}
          </p>
          <Link
            href={DIRECTORY_ROUTE}
            className="mt-4 inline-block rounded-lg bg-accent px-4 py-2 text-sm font-medium text-on-accent hover:bg-accent/90"
          >
            {t.notFoundCta}
          </Link>
        </div>
      </main>
    );
  }

  if (status === "error" || !profile) {
    return (
      <main className="mx-auto w-full max-w-[760px] px-4 pb-12 pt-6">
        <div
          data-testid="profile-error"
          className="mt-6 rounded-lg border border-hairline bg-surface p-6 text-center"
        >
          <p className="font-medium text-txt">{t.loadError}</p>
          <button
            type="button"
            onClick={() => setRetryNonce((n) => n + 1)}
            className="mt-4 rounded-lg border border-hairline bg-surface px-4 py-2 text-sm font-medium text-txt hover:bg-hairline-soft"
          >
            {t.retry}
          </button>
        </div>
      </main>
    );
  }

  return (
    <main className="mx-auto w-full max-w-[760px] px-4 pb-12 pt-6">
      <ProviderProfileBody profile={profile} headingLevel={1} />
    </main>
  );
}
