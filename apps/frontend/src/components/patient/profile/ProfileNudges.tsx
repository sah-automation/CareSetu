"use client";

// PHASE-2.6 T13 (#204): Home-surface nudge cards and completion meter
// (blueprint §5.9). One dismissible card per missing profile group;
// session-scoped dismissal mirrors lib/consent/consentGate. Meter reflects
// draft completeness percentage. Never modal nagging.
//
// INTEGRATION POINT (later phase): server-side profile write replaces the
// localStorage draft; dismissals stay client-only (they die with the page
// session anyway - a later visit resurfaces the gentle reminder).

import { useState } from "react";
import { X } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { ProfileStrings } from "@/lib/i18n/dictionaries";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { MeterBar } from "./MeterBar";
import {
  dismissNudge,
  isNudgeDismissed,
  missingNudgeGroups,
  profileCompleteness,
  type NudgeGroup,
  type ProfileDraft,
} from "@/lib/profile/profileState";
import { cn } from "@/lib/utils";

interface NudgeCopy {
  title: string;
  body: string;
}

function nudgeCopy(group: NudgeGroup, t: ProfileStrings["nudges"]): NudgeCopy {
  switch (group) {
    case "basics":
      return { title: t.basicsTitle, body: t.basicsBody };
    case "tracking":
      return { title: t.trackingTitle, body: t.trackingBody };
    case "photo":
      return { title: t.photoTitle, body: t.photoBody };
    case "area":
      return { title: t.areaTitle, body: t.areaBody };
    case "emergency":
      return { title: t.emergencyTitle, body: t.emergencyBody };
  }
}

export function ProfileCompletionMeter({ draft }: { draft: ProfileDraft }) {
  const { lang } = useLang();
  const t: ProfileStrings = STRINGS[lang].profile;
  const pct = profileCompleteness(draft);

  return (
    <div className="flex items-center gap-3">
      <span className="text-sm font-medium text-txt">{t.meterLabel}</span>
      <MeterBar pct={pct} label={t.meterLabel} />
      <span
        data-testid="pc-meter-label"
        className="shrink-0 text-xs font-medium text-txt-muted"
      >
        {pct}%
      </span>
    </div>
  );
}

interface ProfileNudgeCardsProps {
  draft: ProfileDraft;
  /** Destination of the "Complete profile" CTA on each card. */
  onCompleteHref?: string;
}

export function ProfileNudgeCards({
  draft,
  onCompleteHref = "/patient/profile/complete",
}: ProfileNudgeCardsProps) {
  const { lang } = useLang();
  const t: ProfileStrings = STRINGS[lang].profile;

  const [dismissed, setDismissed] = useState<Set<NudgeGroup>>(
    () => new Set(missingNudgeGroups(draft).filter(isNudgeDismissed)),
  );

  const missing = missingNudgeGroups(draft).filter((g) => !dismissed.has(g));

  if (missing.length === 0) return null;

  return (
    <div data-testid="pc-nudge-stack">
      {missing.map((group) => {
        const copy = nudgeCopy(group, t.nudges);
        return (
          <div
            key={group}
            data-testid="pc-nudge-card"
            className="flex flex-col gap-2 rounded-md border border-hairline bg-surface p-3"
          >
            <div className="flex items-start justify-between gap-2">
              <div>
                {/* T14 #205 axe gate: this follows the page h1 directly, so
                    it must not skip to h4 (heading-order). */}
                <h2 className="text-sm font-medium text-txt">{copy.title}</h2>
                <p className="text-sm text-txt-sub">{copy.body}</p>
              </div>
              <button
                type="button"
                data-testid={`pc-dismiss-${group}`}
                onClick={() => {
                  dismissNudge(group);
                  setDismissed((prev) => new Set(prev).add(group));
                }}
                className="shrink-0 p-1 text-txt-muted hover:text-txt"
                aria-label={t.nudges.dismiss}
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <a
              href={onCompleteHref}
              data-testid="pc-complete-cta"
              className="text-sm font-medium text-accent-strong underline-offset-2 hover:underline self-start"
            >
              {t.nudges.completeCta}
            </a>
          </div>
        );
      })}
    </div>
  );
}
