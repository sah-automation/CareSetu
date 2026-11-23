"use client";

// PHASE-2.6 T06 (#197): compact EN/Hindi switch for shell chrome, wired to
// the T03 language store (blueprint §9.2). Rendered in the light top bar per
// the finalized PROTO-PHASE-2.6 view; surfaces from later tickets reuse it.
//
// #961: restyled to the homepage-v2 segmented pill (prototype
// homepage-resolved-v2 .lang-toggle) - soft track, raised white active
// segment instead of the solid teal fill. Component API, role/group and
// aria-pressed contract unchanged.

import { type Lang } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { cn } from "@/lib/utils";

const CHOICES: Lang[] = ["en", "hi"];

const LABELS: Record<Lang, string> = {
  en: "EN",
  hi: "हिं",
};

export function LangToggle() {
  const { lang, setLang } = useLang();

  return (
    <div
      role="group"
      aria-label="Language"
      className="inline-flex items-center gap-0.5 rounded-full border border-hairline bg-hairline-soft p-[3px]"
      data-testid="lang-toggle"
    >
      {CHOICES.map((choice) => (
        <button
          key={choice}
          type="button"
          onClick={() => setLang(choice)}
          aria-pressed={lang === choice}
          className={cn(
            "rounded-full px-2.5 py-1 text-xs font-semibold leading-tight transition-colors focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
            lang === choice
              ? "bg-surface text-accent-strong shadow-card"
              : "text-txt-sub hover:text-txt",
          )}
        >
          {LABELS[choice]}
        </button>
      ))}
    </div>
  );
}
