// #961: shared eyebrow + headline block for the homepage sections. The
// prototype repeats `.eyebrow-line` + `section-head h2` (+ optional sub) in
// five sections; one component keeps the markup and token classes in a single
// place. Children render under the heading (the sub-lines). The providers band
// passes a warm eyebrow tone per the prototype (`color: var(--warm)`).

import type { ReactNode } from "react";

interface SectionHeadingProps {
  eyebrow: string;
  title: string;
  /** Eyebrow colour utility; defaults to the teal accent. */
  eyebrowClassName?: string;
  children?: ReactNode;
}

export function SectionHeading({
  eyebrow,
  title,
  eyebrowClassName = "text-accent",
  children,
}: SectionHeadingProps) {
  return (
    <div className="flex flex-col gap-1">
      <div
        className={`text-xs font-bold uppercase tracking-[0.08em] ${eyebrowClassName}`}
      >
        {eyebrow}
      </div>
      <h2 className="home-h2 text-txt">{title}</h2>
      {children}
    </div>
  );
}
