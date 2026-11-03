"use client";

// PHASE-8.1 T2 (#488): the patient profile source of truth inside the
// (patient) route group. Mounted once at the group layout, it hydrates
// gate/nudges/dashboard from GET /v1/me/profile on login before any
// local-draft fallback, keeps the identity-scoped local draft as the
// in-flight edit buffer, and persists on wizard Finish through
// PUT /v1/me/profile (backend #482). A saved profile short-circuits the
// completion gate everywhere a consumer reads it (#488 AC 2). Hydration is
// per identity: the stateful subtree is keyed by the signed-in identity.
// #496: Finish is never silent.
// ARCH-P2 #834: the read now goes through useQuery (5 min stale time).

import {
  createContext,
  useCallback,
  useContext,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import {
  useQuery,
  useQueryClient,
  QueryClientContext,
  QueryClientProvider,
} from "@tanstack/react-query";

import { makeQueryClient } from "@/lib/queryClient";
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
  hydrated: boolean;
  savedProfile: StoredPatientProfile | null;
  draft: ProfileDraft;
  saveStatus: ProfileSaveStatus;
  updateDraft: (next: ProfileDraft) => void;
  finishProfile: () => Promise<boolean>;
  syncPhotoRef: (ref: string | null) => void;
}

const ProfileContext = createContext<ProfileContextValue | null>(null);

export function useProfile(): ProfileContextValue {
  const ctx = useContext(ProfileContext);
  if (!ctx) {
    throw new Error("useProfile must be used within a ProfileProvider");
  }
  return ctx;
}

export function useOptionalProfile(): ProfileContextValue | null {
  return useContext(ProfileContext);
}

export function ProfileProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const outerClient = useContext(QueryClientContext);
  const [client] = useState(() => makeQueryClient());
  const queryClient = outerClient ?? client;
  return (
    <QueryClientProvider client={queryClient}>
      <ProfileProviderInner key={user?.id ?? "anon"} identityId={user?.id}>
        {children}
      </ProfileProviderInner>
    </QueryClientProvider>
  );
}

export function patientProfileQueryKey(identityId?: number) {
  return ["patient", "profile", identityId] as const;
}

const FIVE_MINUTES = 5 * 60 * 1000;

function ProfileProviderInner({
  identityId,
  children,
}: {
  identityId: number | undefined;
  children: ReactNode;
}) {
  const queryClient = useQueryClient();
  const [savedProfile, setSavedProfile] = useState<StoredPatientProfile | null>(
    null,
  );
  const [draft, setDraft] = useState<ProfileDraft>(initialDraft());
  const [saveStatus, setSaveStatus] = useState<ProfileSaveStatus>("idle");
  const bufferRef = useRef<ProfileDraft>(initialDraft());

  const profileQuery = useQuery({
    queryKey: patientProfileQueryKey(identityId),
    queryFn: async () => {
      try {
        return await getProfile();
      } catch (err) {
        console.warn("[profile] hydration failed, using local draft:", err);
        throw err;
      }
    },
    enabled: identityId !== undefined,
    staleTime: FIVE_MINUTES,
  });

  useLayoutEffect(() => {
    if (identityId === undefined) return;
    const buffer = loadDraft(identityId);
    bufferRef.current = buffer;
    setDraft(buffer);
  }, [identityId]);

  useLayoutEffect(() => {
    const read = profileQuery.data;
    if (!read?.set || !read.profile) return;
    setSavedProfile(read.profile);
    setDraft((current) =>
      current === bufferRef.current
        ? seedDraftFromServer(read.profile as StoredPatientProfile, current)
        : current,
    );
  }, [profileQuery.data]);

  const hydrated = identityId === undefined ? false : !profileQuery.isLoading;

  const updateDraft = useCallback(
    (next: ProfileDraft) => {
      setDraft(next);
      if (saveStatus !== "idle") setSaveStatus("idle");
      saveDraft(next, identityId);
    },
    [identityId, saveStatus],
  );

  const finishProfile = useCallback(async (): Promise<boolean> => {
    if (identityId === undefined) {
      setSaveStatus("error");
      return false;
    }
    if (!basicsComplete(draft)) {
      setSaveStatus("error");
      return false;
    }
    setSaveStatus("saving");
    try {
      const saved = await saveProfile(draftToProfilePayload(draft));
      setSavedProfile(saved);
      queryClient.setQueryData(patientProfileQueryKey(identityId), {
        set: true,
        profile: saved,
      } as ProfileReadResult);
      void queryClient.invalidateQueries({
        queryKey: patientProfileQueryKey(identityId),
      });
      setSaveStatus("saved");
      return true;
    } catch (err) {
      console.warn("[profile] save failed:", err);
      setSaveStatus("error");
      return false;
    }
  }, [identityId, draft, queryClient]);

  const syncPhotoRef = useCallback(
    (ref: string | null) => {
      setSavedProfile((current) =>
        current === null ? current : { ...current, photo_ref: ref },
      );
      const next = { ...draft, photoFileName: ref ?? "" };
      setDraft(next);
      saveDraft(next, identityId);
      queryClient.setQueryData(
        patientProfileQueryKey(identityId),
        (old: unknown) => {
          const result = old as ProfileReadResult | undefined;
          if (!result?.set || !result.profile) return old;
          return {
            ...result,
            profile: { ...result.profile, photo_ref: ref },
          };
        },
      );
    },
    [draft, identityId, queryClient],
  );

  const value = useMemo(
    () => ({
      hydrated,
      savedProfile,
      draft,
      saveStatus,
      updateDraft,
      finishProfile,
      syncPhotoRef,
    }),
    [
      hydrated,
      savedProfile,
      draft,
      saveStatus,
      updateDraft,
      finishProfile,
      syncPhotoRef,
    ],
  );

  return (
    <ProfileContext.Provider value={value}>{children}</ProfileContext.Provider>
  );
}
