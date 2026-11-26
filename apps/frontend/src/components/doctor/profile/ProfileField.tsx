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
// #623 moved the help text OUT of the wrapping label and onto the control's
// `aria-describedby`. Inside a `<label>` the help joins the control's ACCESSIBLE
// NAME, so the languages field announced itself as "Languages Separate with
// commas" - a screen reader user heard the hint as part of the field's name, and
// any future full-sentence hint read as a broken field name. A name is what the
// thing IS; a description is extra guidance about it, and `aria-describedby` is
// the attribute that says "extra guidance". The binding is made by cloning the
// control rather than by asking all thirteen call sites to thread an id, so the
// fix is in one file; `mergeDescribedBy` keeps a caller's own `aria-describedby`
// (the address card's error message, for one) instead of overwriting it.
//
// Deliberately NOT the adopted `Input` / `Textarea` primitives (#600): #615 splits
// the page, it does not re-skin its fields, and the four sections' own contents
// belong to the section-content tickets. This is the markup those tickets will
// replace, and `fieldClassName` is the one place that decides what a field looks
// like, so that replacement touches one file.

import {
  Children,
  cloneElement,
  Fragment,
  isValidElement,
  type ReactNode,
} from "react";

import { cn } from "@/lib/utils";

export const inputClassName =
  "h-9 w-full rounded-md border border-hairline bg-surface px-3 text-sm text-txt placeholder:text-txt-muted focus:border-accent-border focus:outline-none";
export const labelClassName = "text-xs font-medium text-txt-muted";

/** The field surface, with the invalid state named in tokens rather than colour. */
export function fieldClassName(invalid: boolean): string {
  return cn(inputClassName, invalid && "border-danger");
}

/** The help text's element id, derived from the control's own so it needs no prop. */
function helpId(id: string): string {
  return `${id}-help`;
}

/** Add the help to whatever descriptions the control already carries, not over them. */
function mergeDescribedBy(existing: unknown, added: string): string {
  if (typeof existing !== "string" || existing.length === 0) return added;
  return existing.split(/\s+/).includes(added)
    ? existing
    : `${existing} ${added}`;
}

export interface ProfileFieldProps {
  id: string;
  label: string;
  help?: string;
  children: ReactNode;
}

export function ProfileField({ id, label, help, children }: ProfileFieldProps) {
  // #623: this used to be `Children.only(children)`, which THROWS when handed
  // several nodes or a fragment - so the degradation branch below it was
  // unreachable for the two cases its own comment named. A caller who passed a
  // fragment got a React crash rather than unassociated help, which is the worse
  // of the two outcomes the comment was arguing against. Resolving the single
  // control by hand makes the policy true instead of aspirational.
  const [first, ...rest] = Children.toArray(children);
  const single = rest.length === 0 ? first : null;

  // A Fragment is a valid element but not a control, and `aria-describedby` on
  // one is dropped by every consumer - so it takes the same path as "no control".
  const control =
    isValidElement<{ "aria-describedby"?: unknown }>(single) &&
    single.type !== Fragment
      ? single
      : null;

  // A caller that passes a fragment, several nodes, or bare text gets the help
  // rendered as plain adjacent text, unassociated rather than wrongly associated:
  // there is no single control to describe, and guessing which one was meant is
  // worse than the hint simply not being announced by name.
  if (!control) {
    return (
      <>
        <label className="flex flex-col gap-1" htmlFor={id}>
          <span className={labelClassName}>{label}</span>
          {children}
        </label>
        {help && <p className="text-xs text-txt-muted">{help}</p>}
      </>
    );
  }

  return (
    <div className="flex flex-col gap-1">
      <label className="flex flex-col gap-1" htmlFor={id}>
        <span className={labelClassName}>{label}</span>
        {cloneElement(control, {
          "aria-describedby": help
            ? mergeDescribedBy(control.props["aria-describedby"], helpId(id))
            : control.props["aria-describedby"],
        })}
      </label>
      {help && (
        <p id={helpId(id)} className="text-xs text-txt-muted">
          {help}
        </p>
      )}
    </div>
  );
}
