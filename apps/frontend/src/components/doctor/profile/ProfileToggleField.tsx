"use client";

// #617: the one multi-select control the three closed vocabularies render with.
//
// It is a field and not a bare `ToggleGroup` because a toggle group is a set of
// buttons with no label of its own, and a set of unlabelled buttons on a profile
// page is announced as "Hindi, toggle button, not pressed" twenty-three times
// over with nothing to say what the set is FOR. Three decisions are in here:
//
//   1. **`aria-labelledby`, not a wrapping `<label>`.** `ProfileField` wraps its
//      control in a `<label>`, which is right for one input and wrong here: a
//      label that wraps a GROUP of controls names all of them with the same
//      text, so every one of the twenty-three chips would be announced as
//      "Languages". The heading text is its own element and the group points at
//      it, which is the relationship a `role="group"` is for.
//   2. **The help text sits outside the labelled span**, so it is a description
//      rather than part of every chip's accessible name. `ProfileField` now does
//      the same thing - #623 moved its help out of the wrapping label and onto the
//      control's `aria-describedby`, closing the same hole for single inputs - so
//      the two helpers now agree on the rule and differ only in how they bind it
//      (one clones its control, this one names a group).
//   3. **The chips are a wrapped flex row**, not the primitive's centered single
//      line. Twenty-three languages cannot fit on a phone's width, and a control
//      that scrolls its own options out of reach is a control half the list has
//      lost. `aria-pressed` (Radix's own state for a multi-select item) is what
//      carries "selected" to assistive tech - there is no checkbox role here on
//      purpose, because these are toggle buttons and saying so falsely is worse
//      than the verbosity.
//
// The values arrive already narrowed to members of the vocabulary
// (`knownMembers`), so `onChange` cannot be handed something this list has no
// chip for.

import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";

import { labelClassName } from "./ProfileField";
import { vocabularySlug } from "./profileVocabularies";

export interface ProfileToggleFieldProps<V extends string> {
  /** Names the group's test hooks, and prefixes every chip's own. */
  id: string;
  label: string;
  help?: string;
  /** The closed vocabulary, in the order the domain declares it. */
  vocabulary: readonly V[];
  selected: readonly V[];
  /**
   * The bilingual label for one member - copy, so it lives in the dictionary.
   */
  labelFor: (value: V) => string;
  onChange: (values: V[]) => void;
  /**
   * The element id of a refusal message rendered by the CALLER as this group's
   * sibling, added to the group's `aria-describedby` alongside the help.
   *
   * #623: the refusal used to be a `<p role="alert">` sitting next to the group
   * with nothing connecting the two. A live region is announced when it appears,
   * but it is not *associated*: pressing Tab into the group and reading it gave
   * no hint that twenty-three languages had just been refused, and an
   * accessibility checker reports the group as having no description of its
   * refusal. The caller owns the message's markup (it is also rendered when there
   * is no group, and its `role` depends on whether the refusal came from the
   * client), so this takes the id rather than the element.
   */
  describedById?: string;
}

export function ProfileToggleField<V extends string>({
  id,
  label,
  help,
  vocabulary,
  selected,
  labelFor,
  onChange,
  describedById,
}: ProfileToggleFieldProps<V>) {
  const labelId = `${id}-label`;
  const helpId = `${id}-help`;
  // Whichever descriptions exist, in the order a reader should hear them: what
  // the group is, then how to use it, then what the server said about the last
  // attempt. `undefined` rather than "" when there is nothing to point at, since
  // an empty `aria-describedby` is a reference to nothing.
  const describedBy =
    [help ? helpId : null, describedById ?? null]
      .filter((value): value is string => value != null)
      .join(" ") || undefined;

  return (
    <div className="flex flex-col gap-1">
      <span id={labelId} className={labelClassName}>
        {label}
      </span>
      <ToggleGroup
        type="multiple"
        variant="outline"
        // `lg` is `h-11` - 44px, the accessibility floor's minimum rather than its
        // preference (blueprint A9.4). `sm` would be 36px and `default` 40px, so
        // both of the smaller sizes put every chip on this page below the floor.
        // Twenty-three chips at 44px wrap onto several rows on a phone, which is
        // the right trade: every member stays reachable instead of half of them
        // scrolling out of sight.
        size="lg"
        // A copy, because Radix's `value` is the source of truth for the pressed
        // state and an array it can mutate is a selection the buffer never saw.
        value={[...selected]}
        onValueChange={(next) => onChange(next as V[])}
        aria-labelledby={labelId}
        aria-describedby={describedBy}
        className="flex flex-wrap items-start justify-start gap-2"
        data-testid={id}
      >
        {vocabulary.map((value) => (
          <ToggleGroupItem
            key={value}
            value={value}
            data-testid={`${id}-${vocabularySlug(value)}`}
          >
            {labelFor(value)}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
      {help && (
        <span id={helpId} className="text-xs text-txt-muted">
          {help}
        </span>
      )}
    </div>
  );
}
