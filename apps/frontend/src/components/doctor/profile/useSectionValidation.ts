"use client";

// #617: the client-side validation STATE that all three saving section cards
// share, as distinct from the passes themselves, which live beside each slice in
// `practiceCardFields`, `aboutCardFields` and `notificationCardFields`.
//
// Blueprint §9.5 asks for validation on blur AND on submit, and those are two
// different questions about one pass. The pass is a pure function of the fields -
// "is this value usable?" - and this hook is the only thing that knows WHEN to ask
// it and what to do with the answer:
//
//   - **A field is checked when it loses focus.** A doctor who tabs out of a field
//     wants to know it is wrong while the answer is still in their head, not after
//     they have pressed Save and been told about three fields.
//   - **A field is checked on every keystroke once it has been checked.** The
//     message clears the moment the value becomes usable, rather than lingering
//     until the next blur - a red field that stays red while it is being fixed
//     reads as "still broken" and trains people to ignore the colour.
//   - **The summary is a SUBMIT answer, not a blur answer.** One red field after a
//     blur belongs beside that field, where the doctor's eyes already are. The
//     count-and-focus-walk summary appears when a submit found something, because
//     that is the moment a doctor needs to know there is more than one problem.
//   - **Focus only ever moves on a submit.** The flag `submitted` is what gates
//     the focus walk. Without that gate, checking a field on blur would yank focus
//     straight back to the field the doctor just left, which is the opposite of
//     letting them move on.

import { useState } from "react";

export interface SectionValidation<Field extends string, Fields> {
  /**
   * What the pass refuses right now, whether or not anyone has looked yet. The
   * summary counts this list; the focus walk reads it.
   */
  readonly invalid: readonly Field[];
  /** True once a submit has found something. The focus walk's precondition. */
  readonly submitted: boolean;
  /**
   * Render this field's message: the pass refuses it AND the doctor has blurred it
   * or tried to save. A value nobody has finished editing is not announced.
   */
  showsError(field: Field): boolean;
  /** What the pass says about this field right now, touched or not. */
  refuses(field: Field): boolean;
  /** The field lost focus: mark it touched and re-run the pass. */
  blur(field: Field): void;
  /** The fields changed: merge the patch onto the live value and re-run the pass. */
  changed(patch: Partial<Fields>): void;
  /** The doctor pressed save: mark every field touched and answer with the pass. */
  submit(): readonly Field[];
  /** The write landed: the failed-submit context is over. */
  settled(): void;
}

export function useSectionValidation<Field extends string, Fields>(
  fields: Fields | null,
  validate: (fields: Fields) => Field[],
): SectionValidation<Field, Fields> {
  const [invalid, setInvalid] = useState<readonly Field[]>([]);
  const [touched, setTouched] = useState<ReadonlySet<Field>>(
    () => new Set<Field>(),
  );
  const [submitted, setSubmitted] = useState(false);

  function answer(next: Fields | null): readonly Field[] {
    return next == null ? [] : validate(next);
  }

  function blur(field: Field) {
    setTouched((seen) => {
      if (seen.has(field)) return seen;
      return new Set(seen).add(field);
    });
    setInvalid(answer(fields));
  }

  function changed(patch: Partial<Fields>) {
    if (fields == null) return;
    setInvalid(validate({ ...fields, ...patch }));
  }

  function submit(): readonly Field[] {
    const problems = answer(fields);
    setInvalid(problems);
    setSubmitted(true);
    if (problems.length > 0) {
      setTouched(new Set(problems));
    }
    return problems;
  }

  function settled() {
    setSubmitted(false);
  }

  return {
    invalid,
    submitted,
    showsError: (field) =>
      invalid.includes(field) && (touched.has(field) || submitted),
    refuses: (field) => invalid.includes(field),
    blur,
    changed,
    submit,
    settled,
  };
}
