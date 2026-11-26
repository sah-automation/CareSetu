"use client";

// #583: the doctor console's shared source for the calling doctor's own private
// profile projection, and deliberately the same shape as the patient
// `ProfileProvider` (lib/profile/ProfileContext.tsx) that already solves this
// for the patient side. It is mounted once in the (doctor) route-group layout,
// so it sits above both the console chrome and every page beneath it - that
// structural position is the whole reason the two surfaces cannot drift, which
// is the defect this ticket fixes: the shell read the projection once into its
// own state and the Profile page kept a second copy in its own, so an edit on
// either side never reached the other until a full reload.
//
// It owns the read the shell used to own (#569). The shell, the top bar and the
// account menu now hold no identity data at all, so chrome issues no request of
// its own and a non-doctor staff shell - which mounts no provider and reaches
// this through the optional accessor as null - cannot start a doctor read at
// all. The scope is structural rather than a runtime role check.
//
// The state is identity-scoped, exactly as the patient provider's is: the
// stateful subtree is keyed by the signed-in identity, so signing in as another
// doctor on the same browser remounts the projection atomically and no render
// can show the previous one's profile.
//
// The whole projection is kept, not the photo ref alone. The account menu's
// identity header renders `practice_name` as well as the avatar, and a second
// read to fetch the second field is exactly the request this read removes. That
// is also why the one adopt seam takes a whole view: a practice-details save can
// move the name, so a ref-only seam would fix the avatar and leave the name
// stale. None of the doctor's own profile writes declares a photo ref at all
// (the four section bodies - #608's practice, #609's address, #617's about,
// #617's notifications - have no `photo_ref` field, and the facade writes only
// declared fields), so the ref-only seam would guard an impossible hazard while
// leaving a real one unfixed.
//
// The degrade discipline is the shell feed's, unchanged: one read per visit, a
// `cancelled` guard against a stale answer landing after unmount, and a silent
// degrade with a single console warning. Chrome identity is a bonus, never a
// blocker - and the page renders the same failed read as a retryable banner,
// which is the one place a doctor is named, so the failure is never silent to
// the page. The warning prefix follows the module that now owns the read.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { useAuth } from "@/lib/auth/AuthContext";
import { ApiError } from "@/lib/api-errors";

import { fetchDoctorProfile, type DoctorProfileView } from "./api";

export type DoctorProfileLoadStatus = "loading" | "ready" | "error";

export interface DoctorProfileContextValue {
  /**
   * The stored private projection once the read has answered, or null while it
   * is loading and after a failed one. The photo ref and the practice name
   * travel together: the account menu's identity header needs both and a second
   * read for the second field is the request this source removes.
   */
  profile: DoctorProfileView | null;
  /** Where the read is, so a surface can hold its skeleton and its retry. */
  status: DoctorProfileLoadStatus;
  /** The API trace id from a failed read, for the surface's error banner. */
  errorTraceId: string | undefined;
  /** Re-run the read. A retry that succeeds renders the profile with no reload. */
  reload: () => void;
  /**
   * Adopt a complete newer answer. Three edits route through it: an upload's
   * returned ref, a removal's cleared ref, and a save's returned view. The
   * whole projection, because a save moves `practice_name` and the chrome reads
   * it - a ref-only seam would leave the only place the doctor is named stale.
   */
  adoptProfile: (view: DoctorProfileView) => void;
}

const DoctorProfileContext = createContext<DoctorProfileContextValue | null>(
  null,
);

export function useDoctorProfile(): DoctorProfileContextValue {
  const ctx = useContext(DoctorProfileContext);
  if (!ctx) {
    throw new Error(
      "useDoctorProfile must be used within a DoctorProfileProvider",
    );
  }
  return ctx;
}

/**
 * Like `useDoctorProfile`, but returns null instead of throwing when no provider
 * is mounted. The account menu is shared across roles and is rendered by shells
 * that have no doctor profile - the partner and operator staff shells mount no
 * provider at all - so it reads through this and degrades to its own fallbacks.
 * The same optional-accessor shape the patient chrome already uses for the
 * patient profile context.
 */
export function useOptionalDoctorProfile(): DoctorProfileContextValue | null {
  return useContext(DoctorProfileContext);
}

export function DoctorProfileProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  // Keying the stateful subtree by identity makes an identity switch remount
  // the state atomically: the next commit already holds the pristine state of
  // the new doctor, so nothing transient ever shows the previous one's profile.
  return (
    <DoctorProfileProviderInner key={user?.id ?? "anon"} identityId={user?.id}>
      {children}
    </DoctorProfileProviderInner>
  );
}

function DoctorProfileProviderInner({
  identityId,
  children,
}: {
  identityId: number | undefined;
  children: ReactNode;
}) {
  const [profile, setProfile] = useState<DoctorProfileView | null>(null);
  const [status, setStatus] = useState<DoctorProfileLoadStatus>("loading");
  const [errorTraceId, setErrorTraceId] = useState<string | undefined>();
  // The reload seam is a counter rather than a refetch function so a consumer
  // cannot hold a stale closure of the read, and so the effect stays keyed on
  // the identity alone: one read per visit, one more per explicit retry.
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    // No signed-in identity: the doctor surfaces are unreachable under the shell
    // and this freshly-keyed subtree already holds pristine state, so there is
    // nothing to hydrate. (The key guarantees identityId cannot change for the
    // lifetime of this instance.)
    if (identityId === undefined) return;
    let cancelled = false;
    setStatus("loading");
    setErrorTraceId(undefined);

    fetchDoctorProfile()
      .then((view) => {
        if (cancelled) return;
        setProfile(view);
        setStatus("ready");
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        // Degrade silently for the chrome - the account avatar falls back to its
        // person icon - while the status and the trace id let the Profile page
        // say so and offer the retry. Still surfaced so a silent feed failure
        // stays visible in the console.
        console.warn("[doctor-profile] failed to load:", err);
        setErrorTraceId(err instanceof ApiError ? err.traceId : undefined);
        setProfile(null);
        setStatus("error");
      });

    return () => {
      cancelled = true;
    };
  }, [identityId, attempt]);

  const reload = useCallback(() => {
    setAttempt((current) => current + 1);
  }, []);

  const adoptProfile = useCallback((view: DoctorProfileView) => {
    setProfile(view);
    setErrorTraceId(undefined);
    setStatus("ready");
  }, []);

  const value = useMemo(
    () => ({ profile, status, errorTraceId, reload, adoptProfile }),
    [profile, status, errorTraceId, reload, adoptProfile],
  );

  return (
    <DoctorProfileContext.Provider value={value}>
      {children}
    </DoctorProfileContext.Provider>
  );
}
