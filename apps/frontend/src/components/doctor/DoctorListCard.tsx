// MOD-012 / FEAT-008 (#645/#651 "Shared doctor card"): the one card both
// doctor lists render (the patients list adopts it here; the cases list follows
// in #652). Composed from the token-bridged Card, Badge, and Avatar primitives
// so elevation, radius, and surface stay token-owned rather than hand-rolled.
// Anatomy: avatar (initials branch - a photo reference never crosses the wire,
// US-71/decision), name, age, chip row, stage chip, meta line, and a single
// whole-card link.
//
// The whole card is one focus stop: the link is an overlay stretched across
// the card, carrying an accessible name that includes the patient (US-66), so
// tabbing through a list is one stop per card (US-67). The avatar is
// decorative (aria-hidden inside the primitive) and must not carry the name -
// that would double-announce.

import type { ReactNode } from "react";

import Link from "next/link";

import { Avatar } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";

/** One chip in the card's chip row (granted scopes, verify flags, ...). */
export interface DoctorCardChip {
  key: string;
  label: string;
  /** Tailwind tone classes; defaults to the accent chip tone. */
  tone?: string;
  testId?: string;
}

export interface DoctorListCardProps {
  href: string;
  /** Display name; already resolved against the caller's fallback. */
  name: string;
  /** Pre-formatted age line (caller-localised), e.g. "45 yrs". */
  ageText?: string | null;
  chips?: DoctorCardChip[];
  /** The stage chip - a worded label, so an absent stage reads as words. */
  stage: { label: string; tone: string };
  stageTestId?: string;
  meta?: ReactNode;
  /** The link's accessible name; must include the patient. */
  accessibleName: string;
  nameTestId?: string;
  linkTestId?: string;
}

const DEFAULT_CHIP_TONE = "bg-accent-soft text-accent-strong";

export function DoctorListCard({
  href,
  name,
  ageText,
  chips = [],
  stage,
  stageTestId,
  meta,
  accessibleName,
  nameTestId,
  linkTestId,
}: DoctorListCardProps) {
  return (
    <Card className="relative flex h-full min-w-0 flex-col p-4 transition-colors hover:border-accent-border">
      <div className="flex items-start gap-3">
        {/* Initials branch only: has_photo stays on the row, never a ref. */}
        <Avatar
          name={name}
          className="h-9 w-9 shrink-0 bg-accent-soft text-sm font-medium text-accent-strong"
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
            <span
              className="text-sm font-medium break-words text-txt"
              data-testid={nameTestId}
            >
              {name}
            </span>
            {ageText != null && (
              <span className="text-xs text-txt-muted">{ageText}</span>
            )}
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            {chips.map((chip) => (
              <Badge
                key={chip.key}
                data-testid={chip.testId}
                className={chip.tone ?? DEFAULT_CHIP_TONE}
              >
                {chip.label}
              </Badge>
            ))}
            <Badge data-testid={stageTestId} className={stage.tone}>
              {stage.label}
            </Badge>
          </div>
          {meta != null && (
            <div className="mt-2 text-xs text-txt-muted">{meta}</div>
          )}
        </div>
      </div>
      {/* The single whole-card link: stretched over the card, one focus stop. */}
      <Link
        href={href}
        aria-label={accessibleName}
        data-testid={linkTestId}
        className="absolute inset-0 rounded-lg focus-visible:ring-1 focus-visible:ring-ring focus-visible:outline-none"
      />
    </Card>
  );
}
