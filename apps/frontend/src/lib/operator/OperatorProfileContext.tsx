"use client";

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

import { fetchOperatorProfile, type OperatorProfileView } from "./api";

export type OperatorProfileLoadStatus = "loading" | "ready" | "error";

export interface OperatorProfileContextValue {
  profile: OperatorProfileView | null;
  status: OperatorProfileLoadStatus;
  errorTraceId: string | undefined;
  reload: () => void;
  adoptProfile: (view: OperatorProfileView) => void;
}

const OperatorProfileContext =
  createContext<OperatorProfileContextValue | null>(null);

export function useOperatorProfile(): OperatorProfileContextValue {
  const ctx = useContext(OperatorProfileContext);
  if (!ctx) {
    throw new Error(
      "useOperatorProfile must be used within an OperatorProfileProvider",
    );
  }
  return ctx;
}

export function useOptionalOperatorProfile(): OperatorProfileContextValue | null {
  return useContext(OperatorProfileContext);
}

export function OperatorProfileProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  return (
    <OperatorProfileProviderInner
      key={user?.id ?? "anon"}
      identityId={user?.id}
    >
      {children}
    </OperatorProfileProviderInner>
  );
}

function OperatorProfileProviderInner({
  identityId,
  children,
}: {
  identityId: number | undefined;
  children: ReactNode;
}) {
  const [profile, setProfile] = useState<OperatorProfileView | null>(null);
  const [status, setStatus] = useState<OperatorProfileLoadStatus>("loading");
  const [errorTraceId, setErrorTraceId] = useState<string | undefined>();
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (identityId === undefined) return;
    let cancelled = false;
    setStatus("loading");
    setErrorTraceId(undefined);

    fetchOperatorProfile()
      .then((view) => {
        if (cancelled) return;
        setProfile(view);
        setStatus("ready");
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        console.warn("[operator-profile] failed to load:", err);
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

  const adoptProfile = useCallback((view: OperatorProfileView) => {
    setProfile(view);
    setErrorTraceId(undefined);
    setStatus("ready");
  }, []);

  const value = useMemo(
    () => ({ profile, status, errorTraceId, reload, adoptProfile }),
    [profile, status, errorTraceId, reload, adoptProfile],
  );

  return (
    <OperatorProfileContext.Provider value={value}>
      {children}
    </OperatorProfileContext.Provider>
  );
}
