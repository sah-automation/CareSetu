// #605: the per-section edit buffer behind the doctor profile page's editable
// sections. It lifts the discipline the page used to hold inline (seededFrom,
// bufferDirty, changeForm) into a hook any section can own, so the page can
// become one buffer per independently saving section without four copies of the
// same reasoning.
//
// Three rules, and the whole file exists to keep them:
//
//   1. The buffer is seeded once per *distinct* server answer, keyed on the
//      answer object's identity. Identity alone cannot decide when a new answer
//      arrives: a re-render must not reseed, and a genuinely new answer should.
//   2. A dirty buffer is never reseeded by any answer, however late it lands.
//      While the doctor is mid-edit their intent outranks a server fact they
//      have already been told, and a retry can land at any moment.
//   3. A save's own reply is just another answer, so rule 2 covers it: the
//      buffer never clears its dirty flag on save, and therefore a reply that
//      lands after the doctor has carried on typing cannot discard those
//      keystrokes.
//
// The seed key is the *whole* answer, never the section's own slice. Two
// sections that keyed on their slices would each reseed the moment the source
// emitted a new object, which is the drift four independent buffers have to
// avoid. The mapper is what makes a buffer per section: it is the one function
// that turns the shared answer into this section's editable shape.

import { useCallback, useEffect, useRef, useState } from "react";

export interface SectionEditBuffer<T> {
  /** The section's slice, or null until the first answer has seeded it. */
  value: T | null;
  /** True once the doctor has typed here; from then on no answer reseeds it. */
  dirty: boolean;
  /** How many edits this buffer has taken, so a shell can outdate itself. */
  edits: number;
  /** Fold a keystroke (or a toggle, or a chip pick) into the slice. */
  change: (patch: Partial<T>) => void;
}

export function useSectionEditBuffer<S, T>(
  answer: S | null,
  toSlice: (answer: S) => T,
): SectionEditBuffer<T> {
  const [value, setValue] = useState<T | null>(null);
  const [dirty, setDirty] = useState(false);
  const [edits, setEdits] = useState(0);
  // The dirty flag is a ref as well as state: the guard below reads it
  // synchronously inside an effect, where the state update from the same commit
  // has not landed yet. A per-field map would be finer-grained and would be a
  // different design - this one is deliberately coarse, so that one untouched
  // field cannot be reseeded underneath the doctor either.
  const dirtyRef = useRef(false);
  const seededFrom = useRef<S | null>(null);

  // The mapper is mirrored into a ref so the seeding effect stays keyed on the
  // answer alone. Depending on the mapper would re-run the effect on every
  // render for any caller passing an inline arrow - which the guards would
  // absorb, but only by accident, and at the cost of a re-read of the guard
  // ordering that is the whole contract.
  const toSliceRef = useRef(toSlice);
  useEffect(() => {
    toSliceRef.current = toSlice;
  }, [toSlice]);

  useEffect(() => {
    // The three guards, in this order. Identity first: it is what makes a plain
    // re-render a no-op, which is the common case. Dirty second: it is the rule
    // that outranks every answer, including the retry that lands mid-sentence.
    if (answer == null) return;
    if (seededFrom.current === answer) return;
    if (dirtyRef.current) return;
    seededFrom.current = answer;
    setValue(toSliceRef.current(answer));
  }, [answer]);

  const change = useCallback((patch: Partial<T>) => {
    dirtyRef.current = true;
    setDirty(true);
    setEdits((count) => count + 1);
    setValue((current) =>
      current == null ? current : { ...current, ...patch },
    );
  }, []);

  return { value, dirty, edits, change };
}
