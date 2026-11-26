"use client";

// PHASE-7 T15 (#359): intake-start mode chooser (blueprint §5.4, finalized
// PROTO-PHASE-7/8 intake-start.html is the binding copy spec). Two oversized
// first-class inputs - voice is default-highlighted (recommended, never forced)
// and text is equally first-class (REQ-007 Rule 2). ADR-0001 honesty: the
// chooser never markets an AI diagnosis; the transcribe -> structure ->
// pre-summary pipeline is always a draft a doctor verifies.

import Link from "next/link";
import { Keyboard, Mic, ChevronRight } from "lucide-react";

import { PageHeader } from "@/components/layout/PageHeader";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { cn } from "@/lib/utils";

const MODE_CARD_BASE =
  "flex items-center gap-4 w-full min-h-[104px] p-5 px-6 rounded-lg border-2 border-hairline bg-surface shadow-card transition-[box-shadow,transform,border-color] duration-150 hover:border-accent-border hover:shadow-pop hover:-translate-y-0.5 active:scale-[0.985] cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent no-underline text-inherit";

const MODE_ICON_BASE =
  "w-14 h-14 shrink-0 rounded-full inline-flex items-center justify-center";

export default function IntakeStartPage() {
  const { lang } = useLang();
  const t = STRINGS[lang].intake;
  const nav = STRINGS[lang].nav;

  return (
    <>
      <PageHeader
        title={t.title}
        description={t.reassure}
        breadcrumbs={[
          { label: nav.home, href: "/patient" },
          { label: t.breadcrumb },
        ]}
      />

      <div className="space-y-4" data-testid="intake-mode-chooser">
        {/* Voice - default-highlighted but never forced (REQ-007 Rule 2) */}
        <Link
          href="/patient/intake/voice"
          className={cn(MODE_CARD_BASE, "border-accent bg-accent-soft")}
          data-testid="mode-voice"
        >
          <span
            className={cn(MODE_ICON_BASE, "bg-accent text-on-accent")}
            aria-hidden="true"
          >
            <Mic size={26} strokeWidth={1.8} />
          </span>
          <span className="flex min-w-0 flex-1 flex-col gap-0.5">
            <span className="text-lg font-semibold leading-snug">
              {t.modeVoice}
            </span>
            <span className="text-sm text-txt-muted">{t.modeVoiceSub}</span>
          </span>
          <ChevronRight
            size={24}
            className="shrink-0 text-txt-muted"
            aria-hidden="true"
          />
        </Link>

        {/* Text - equally first-class (REQ-007 Rule 2) */}
        <Link
          href="/patient/intake/text"
          className={cn(MODE_CARD_BASE)}
          data-testid="mode-text"
        >
          <span
            className={cn(MODE_ICON_BASE, "bg-hairline-soft text-txt-sub")}
            aria-hidden="true"
          >
            <Keyboard size={26} strokeWidth={1.8} />
          </span>
          <span className="flex min-w-0 flex-1 flex-col gap-0.5">
            <span className="text-lg font-semibold leading-snug">
              {t.modeText}
            </span>
            <span className="text-sm text-txt-muted">{t.modeTextSub}</span>
          </span>
          <ChevronRight
            size={24}
            className="shrink-0 text-txt-muted"
            aria-hidden="true"
          />
        </Link>
      </div>
    </>
  );
}
