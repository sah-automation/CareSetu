"use client";

// PHASE-2.6 T06 (#197): compact EN/Hindi switch for shell chrome, wired to
// the T03 language store (blueprint §9.2). Rendered in the light top bar per
// the finalized PROTO-PHASE-2.6 view; surfaces from later tickets reuse it.

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
      className="flex overflow-hidden rounded-full border border-hairline"
      data-testid="lang-toggle"
    >
      {CHOICES.map((choice) => (
        <button
          key={choice}
          type="button"
          onClick={() => setLang(choice)}
          aria-pressed={lang === choice}
          className={cn(
            "px-2.5 py-1 text-xs font-medium",
            lang === choice
              ? "bg-accent text-on-accent"
              : "text-txt-sub hover:bg-accent-soft",
          )}
        >
          {LABELS[choice]}
        </button>
      ))}
    </div>
  );
}
