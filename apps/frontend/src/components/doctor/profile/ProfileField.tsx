"use client";

// #615: the one labelled-field helper the profile page's section components
// compose, lifted out of the page body when the page became a shell.
//
// It exists because every section needs the same three things - a real label
// bound to its control, a muted label style, and one input surface - and
// hand-rolling them per section is how a profile page ends up with three shades
// of the same text box.
//
// The label WRAPS its control rather than pointing at it from a distance. That is
// the pre-split `Field` helper's shape, kept deliberately: clicking the label
// focuses the field either way, but a wrapped control keeps the association when
// the control moves inside a grid cell, which is what every section here does.
// `htmlFor` is still declared, so the association is a real one and not a
// positional coincidence - it is what a reader tool follows.
//
// A consequence worth stating, because the existing suite depends on it: the
// help text sits INSIDE the label, so it joins the control's accessible name
// ("Languages Separate with commas"). One binding that carries the label and its
// hint beats a placeholder-only field, and it is why the tests match the language
// field by prefix. The help text therefore must never be a full sentence that
// reads oddly appended to the label.
//
// Deliberately NOT the adopted `Input` / `Textarea` primitives (#600): #615 splits
// the page, it does not re-skin its fields, and the four sections' own contents
// belong to the section-content tickets. This is the markup those tickets will
// replace, and `fieldClassName` is the one place that decides what a field looks
// like, so that replacement touches one file.

import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export const inputClassName =
  "h-9 w-full rounded-md border border-hairline bg-surface px-3 text-sm text-txt placeholder:text-txt-muted focus:border-accent-border focus:outline-none";
export const labelClassName = "text-xs font-medium text-txt-muted";

/** The field surface, with the invalid state named in tokens rather than colour. */
export function fieldClassName(invalid: boolean): string {
  return cn(inputClassName, invalid && "border-danger");
}

export interface ProfileFieldProps {
  id: string;
  label: string;
  help?: string;
  children: ReactNode;
}

export function ProfileField({ id, label, help, children }: ProfileFieldProps) {
  return (
    <label className="flex flex-col gap-1" htmlFor={id}>
      <span className={labelClassName}>{label}</span>
      {children}
      {help && <span className="text-xs text-txt-muted">{help}</span>}
    </label>
  );
}
