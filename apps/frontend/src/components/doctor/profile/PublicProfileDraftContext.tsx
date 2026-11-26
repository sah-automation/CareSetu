// #618: the one seam between the doctor's typed edits and the live preview.
//
// The four saving cards each own a private edit buffer, and none of them knew a
// preview existed. Rather than lift the buffers (which would put four independent
// writes back into one form that can save none of them - the mistake #611/#616/#617
// each undid) or re-type a field to mirror them, this provider collects what the
// cards have TYPED and hands it to the preview.
//
// Three rules, and they are `useSectionEditBuffer`'s three rules again - deliberately
// the same rules, because a preview that seeded differently from its own editor
// would show a doctor one answer while their input said another:
//
//   1. Seeded once per DISTINCT server answer, keyed on the answer's identity.
//      A re-render is a no-op; a genuinely new answer reseeds.
//   2. A section with uncommitted edits is never reseeded, however late the answer
//      arrives. While a doctor is mid-edit their intent outranks a server fact they
//      have already been told, and a save's own reply can land mid-sentence.
//   3. Therefore a save never clears the dirty flag here either: a reply that lands
//      after the doctor carried on typing cannot discard those keystrokes.
//
// The dirty flag is a ref as well as state for the reason the buffer keeps it in
// one: the reseed guard runs inside an effect, where the state update from the same
// commit has not landed yet.
//
// This provider owns no fetching and no writing. It is a map from "what has been
// typed" to "what the preview shows", and the projection it feeds is what refuses
// to let a typed value reach a derived field.

"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import type { DoctorProfileView } from "@/lib/doctor/api";

import {
  draftFromProfile,
  type PublicProfileDraft,
  type PublicProfileSection,
} from "./publicProfileProjection";

export interface PublicProfileDraftValue {
  /**
   * The saved projection the draft was seeded from. The preview reads its derived
   * fields - the verified flag, every credential status - from HERE and from
   * nowhere else (ADR-0011).
   */
  profile: DoctorProfileView;
  draft: PublicProfileDraft;
  /**
   * Fold one section's edits into the draft. Called from the section card's own
   * change handler, so a keystroke reaches the preview on the keystroke.
   */
  publish: <S extends PublicProfileSection>(
    section: S,
    patch: Partial<PublicProfileDraft[S]>,
  ) => void;
}

const PublicProfileDraftContext = createContext<PublicProfileDraftValue | null>(
  null,
);

export function usePublicProfileDraft(): PublicProfileDraftValue {
  const value = useContext(PublicProfileDraftContext);
  if (value === null) {
    throw new Error(
      "usePublicProfileDraft must be used within a PublicProfileDraftProvider",
    );
  }
  return value;
}

/**
 * One section's slice folded over its own. A named function rather than an inline
 * spread so the generic merge is written once, and so the "a section's edits
 * never touch another's" rule is visible at the point it is applied.
 */
function mergeSection<S extends PublicProfileSection>(
  draft: PublicProfileDraft,
  section: S,
  patch: Partial<PublicProfileDraft[S]>,
): PublicProfileDraft {
  return {
    ...draft,
    [section]: { ...draft[section], ...patch },
  } as PublicProfileDraft;
}

export function PublicProfileDraftProvider({
  profile,
  children,
}: {
  profile: DoctorProfileView;
  children: ReactNode;
}) {
  const [draft, setDraft] = useState<PublicProfileDraft>(() =>
    draftFromProfile(profile),
  );
  const uncommitted = useRef<Set<PublicProfileSection>>(new Set());
  const seededFrom = useRef(profile);

  useEffect(() => {
    // The three guards, in the buffer's order. Identity first: it is what makes a
    // plain re-render a no-op, which is the common case. Uncommitted second: it
    // is the rule that outranks every answer, including the retry that lands
    // mid-sentence.
    if (seededFrom.current === profile) return;
    seededFrom.current = profile;
    setDraft((current) => {
      const seeded = draftFromProfile(profile);
      // Written as a whole object rather than a loop over the sections, so that
      // adding a third section to `PublicProfileDraft` is a COMPILE error here
      // instead of a section that silently never gets reseeded.
      return {
        practice: uncommitted.current.has("practice")
          ? current.practice
          : seeded.practice,
        address: uncommitted.current.has("address")
          ? current.address
          : seeded.address,
      };
    });
  }, [profile]);

  const publish = useCallback(
    <S extends PublicProfileSection>(
      section: S,
      patch: Partial<PublicProfileDraft[S]>,
    ) => {
      uncommitted.current.add(section);
      setDraft((current) => mergeSection(current, section, patch));
    },
    [],
  );

  const value = useMemo(
    () => ({ profile, draft, publish }),
    [profile, draft, publish],
  );

  return (
    <PublicProfileDraftContext.Provider value={value}>
      {children}
    </PublicProfileDraftContext.Provider>
  );
}
