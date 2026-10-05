"use client";

// #617: how one section card reads a server's field-level refusals.
//
// #610's handler puts the refused field's wire name in `details.errors[].path`, and
// that path is the only thing that maps a 422 onto an input (api-standards §2,
// blueprint §9.5). Three cards need to read it, and each of them needs the same
// three answers from it, so the reading is a hook rather than the same twenty
// lines copied into each card.
//
// The three answers:
//
//   1. **Was one of MY fields refused?** A path this card can map gets its own
//      field-level line under the control the doctor tapped. The card declares
//      its own mappable set, so a path that belongs to a sibling section cannot
//      land here and be blamed on the wrong control.
//   2. **Was a path refused that this card cannot map?** That lands in the form
//      summary instead. Dropping it would hide a real failure from a doctor, and
//      guessing it onto the nearest control would blame a field the server never
//      named - which is the same reason the address card does this (#616).
//   3. **Is it really a server refusal?** Only an `ApiError` carries validated
//      details. A shape-guard failure or a transport bug has none, so nothing is
//      claimed and the shell's inline retry link is the whole presentation.
//
// The set is cleared by the next edit and by the start of the next attempt, so a
// stale line never outlives the state it described. Clearing on attempt start is
// what makes the two kinds of refusal mutually exclusive by construction: a
// client-side refusal never reaches the API, and the attempt that would clear one
// clears the server's own first.

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api-errors";

export interface RefusedFieldErrors {
  /** True when the server named one of the paths this card can map. */
  refused: ReadonlySet<string>;
  /** True when the server named a path this card cannot map onto a control. */
  unmapped: boolean;
  /** Read one failure into the two answers above. */
  record: (error: unknown) => void;
  /** Forget the last failure - called by every edit and by every attempt. */
  clear: () => void;
}

export function useRefusedFieldErrors(
  mappablePaths: readonly string[],
): RefusedFieldErrors {
  const [refused, setRefused] = useState<ReadonlySet<string>>(new Set());
  const [unmapped, setUnmapped] = useState(false);

  // Mirrored into a ref so `record` and `clear` stay referentially stable
  // without the caller having to memoise the path list it passes - the same
  // reason `useSectionEditBuffer` mirrors its mapper.
  const mappable = useRefSet(mappablePaths);

  const clear = useCallback(() => {
    setRefused(new Set());
    setUnmapped(false);
  }, []);

  const record = useCallback(
    (error: unknown) => {
      if (!(error instanceof ApiError)) {
        setRefused(new Set());
        setUnmapped(false);
        return;
      }
      const named = error.fieldErrors;
      const mine = new Set<string>();
      let other = false;
      for (const field of named) {
        if (mappable.current.has(field.path)) mine.add(field.path);
        else other = true;
      }
      setRefused(mine);
      setUnmapped(other);
    },
    [mappable],
  );

  return { refused, unmapped, record, clear };
}

/** The path set as a ref, refreshed whenever the caller's list changes. */
function useRefSet(paths: readonly string[]): React.RefObject<Set<string>> {
  const ref = useRef<Set<string>>(new Set(paths));
  useEffect(() => {
    ref.current = new Set(paths);
  }, [paths]);
  return ref;
}
