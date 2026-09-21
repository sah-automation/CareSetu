"use client";

// PHASE-8.1 T2 (#488): the patient profile source of truth inside the
// (patient) route group. Mounted once at the group layout, it hydrates
// gate/nudges/dashboard from GET /v1/me/profile on login before any
// local-draft fallback, keeps the identity-scoped local draft as the
// in-flight edit buffer, and persists on wizard Finish through
// PUT /v1/me/profile (backend #482). A saved profile short-circuits the
// completion gate everywhere a consumer reads it (#488 AC 2). Hydration is
// per identity: the stateful subtree is keyed by the signed-in identity, so
// switching identities on one browser remounts the provider state atomically
// and no render can ever show a previous identity's profile or draft
// (#488 AC 5).
// #496: Finish is never silent. Identity-absent and incomplete-basics paths
// write `saveStatus` before resolving false, so the host's bilingual
// save-error notice always surfaces a blocked or failed save.

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
import {
  getProfile,
  saveProfile,
  type ProfileReadResult,
  type StoredPatientProfile,
} from "@/lib/profile/api";
import {
  basicsComplete,
  draftToProfilePayload,
  initialDraft,
  loadDraft,
  saveDraft,
  seedDraftFromServer,
  type ProfileDraft,
} from "@/lib/profile/profileState";

export type ProfileSaveStatus = "idle" | "saving" | "saved" | "error";

export interface ProfileContextValue {
  /** True once the initial server hydration has settled for this identity. */
  hydrated: boolean;
  /** The saved server profile when the backend answers set=true; null otherwise. */
  savedProfile: StoredPatientProfile | null;
  /** The in-flight edit buffer (identity-scoped local draft). */
  draft: ProfileDraft;
  /** Persist state for Finish surfaces; surfaces render bilingual copy from it. */
  saveStatus: ProfileSaveStatus;
  /** Replace the buffer and write it through to the identity-scoped draft. */
  updateDraft: (next: ProfileDraft) => void;
  /**
   * Persist the buffer through PUT /v1/me/profile and adopt the saved profile.
   * The never-silent-save invariant (#496): this resolves true on success
   * (consumers may then route/close) and false on every other path - identity
   * not yet resolved, incomplete basics, or a failed write - with `saveStatus`
   * written first so the host's bilingual save-error notice is always shown.
   */
  finishProfile: () => Promise<boolean>;
}

const ProfileContext = createContext<ProfileContextValue | null>(null);

export function useProfile(): ProfileContextValue {
  const ctx = useContext(ProfileContext);
  if (!ctx) {
    throw new Error("useProfile must be used within a ProfileProvider");
  }
  return ctx;
}

/**
 * Like `useProfile`, but returns null instead of throwing when there is no
 * provider. Used by chrome shared across roles (the light top bar's location
 * chip) so it can render its beachhead fallback even where the patient profile
 * context is not mounted (full density, component tests).
 */
export function useOptionalProfile(): ProfileContextValue | null {
  return useContext(ProfileContext);
}

export function ProfileProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  // Keying the stateful subtree by identity makes an identity switch remount
  // the provider state atomically: the next commit already holds the pristine
  // state of the new identity, so nothing transient ever shows the previous
  // one's saved profile or draft (#488 AC 5).
  return (
    <ProfileProviderInner key={user?.id ?? "anon"} identityId={user?.id}>
      {children}
    </ProfileProviderInner>
  );
}

function ProfileProviderInner({
  identityId,
  children,
}: {
  identityId: number | undefined;
  children: ReactNode;
}) {
  const [hydrated, setHydrated] = useState(false);
  const [savedProfile, setSavedProfile] = useState<StoredPatientProfile | null>(
    null,
  );
  const [draft, setDraft] = useState<ProfileDraft>(initialDraft);
  const [saveStatus, setSaveStatus] = useState<ProfileSaveStatus>("idle");

  useEffect(() => {
    // No signed-in identity: the patient surfaces are unreachable under the
    // shell and this freshly-keyed subtree already holds pristine state, so
    // there is nothing to hydrate. (The key guarantees identityId cannot
    // change for the lifetime of this instance.)
    if (identityId === undefined) return;
    let cancelled = false;

    // Hydration loads the identity-scoped buffer first (the PWA's offline
    // fallback), then the server answer wins for the fields it models once it
    // settles (#488 AC 2). If the patient edits during the round-trip, the
    // buffer reference changes and the server seed is skipped, so in-progress
    // input is never clobbered by a slower GET.
    async function hydrate() {
      const buffer = loadDraft(identityId);
      setDraft(buffer);
      let read: ProfileReadResult | null = null;
      try {
        read = await getProfile();
      } catch (err) {
        // Best-effort: surface the buffer and re-attempt on the next identity
        // hydration rather than blocking patient flows.
        console.warn("[profile] hydration failed, using local draft:", err);
      }
      if (cancelled) return;
      if (read?.set && read.profile) {
        const stored = read.profile;
        setSavedProfile(stored);
        setDraft((current) =>
          current === buffer ? seedDraftFromServer(stored, buffer) : current,
        );
      }
      setHydrated(true);
    }

    void hydrate();
    return () => {
      cancelled = true;
    };
  }, [identityId]);

  const updateDraft = useCallback(
    (next: ProfileDraft) => {
      setDraft(next);
      if (saveStatus !== "idle") setSaveStatus("idle");
      saveDraft(next, identityId);
    },
    [identityId, saveStatus],
  );

  const finishProfile = useCallback(async (): Promise<boolean> => {
    // Never-silent-save invariant (#496): every blocked path writes the save
    // status before resolving false so Finish can never be a silent no-op.
    if (identityId === undefined) {
      setSaveStatus("error");
      return false;
    }
    // The draft this render agreed on; surfaces block Finish until basics
    // validate, but guard anyway so a stray call cannot emit a 422 against
    // the profile surface. (Regressions on this branch were the dead click.)
    if (!basicsComplete(draft)) {
      setSaveStatus("error");
      return false;
    }
    setSaveStatus("saving");
    try {
      const saved = await saveProfile(draftToProfilePayload(draft));
      setSavedProfile(saved);
      setSaveStatus("saved");
      return true;
    } catch (err) {
      console.warn("[profile] save failed:", err);
      setSaveStatus("error");
      return false;
    }
  }, [identityId, draft]);

  const value = useMemo(
    () => ({
      hydrated,
      savedProfile,
      draft,
      saveStatus,
      updateDraft,
      finishProfile,
    }),
    [hydrated, savedProfile, draft, saveStatus, updateDraft, finishProfile],
  );

  return (
    <ProfileContext.Provider value={value}>{children}</ProfileContext.Provider>
  );
}
