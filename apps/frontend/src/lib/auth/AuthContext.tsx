"use client";

// AuthContext - session validation, role management, and logout for the
// whole app. Mounted once at the root layout so public and dashboard
// surfaces share one session source: reads the stored session on mount,
// validates against GET /v1/me, auto-refreshes expired JWTs, and redirects
// to /login when the session is invalid. (PHASE-2.5 T3 #151; hoisted to
// root in PHASE-2.6 T01, #192)
//
// #496: mount-only validation left a fresh OTP login with no identity until a
// reload. The resumeSession seam below re-resolves the stored session's
// identity in-flow right after the OTP wizard persists it, so the post-login
// patient surface hydrates without a reload.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { useRouter } from "next/navigation";
import { QueryClientContext, type QueryClient } from "@tanstack/react-query";
import { makeQueryClient } from "@/lib/queryClient";
import {
  readSession,
  clearSession,
  readSelectedRole,
  saveSelectedRole,
  clearSelectedRole,
  type StoredSession,
} from "./session";
import {
  fetchSessionMe,
  clearCachedSessionMe,
  type MeResponse,
} from "./sessionQuery";

import {
  ACCESS_TOKEN_TTL_SECONDS,
  PROACTIVE_REFRESH_RATIO,
} from "@/lib/config";

const API_BASE_URL: string =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export interface User {
  id: number;
  phone: string;
  roles: string[];
  tier: string | null;
}

export interface AuthContextValue {
  user: User | null;
  selectedRole: string | null;
  switchRole: (role: string) => void;
  logout: () => void;
  isAuthenticated: boolean;
  isLoading: boolean;
  /**
   * Session-resume seam (#496): re-run /v1/me with the stored session and
   * apply the resolved identity/roles to state in-flow. The patient OTP
   * wizard calls this immediately after persisting a freshly-minted session
   * so the post-login surface hydrates without the reload the mount-only
   * validate() used to require.
   */
  resumeSession: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}

interface RefreshResponse {
  jwt: string;
  refresh_token: string;
}

function clearCookie(name: string): void {
  document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/`;
}

function applyMe(
  me: MeResponse,
  setUser: (u: User) => void,
  setSelectedRole: (r: string) => void,
) {
  setUser({
    id: Number(me.subject_id),
    phone: me.phone,
    roles: me.roles,
    tier: me.tier ?? null,
  });
  if (me.roles.length > 0) {
    const saved = readSelectedRole();
    const role = saved && me.roles.includes(saved) ? saved : me.roles[0];
    setSelectedRole(role);
  }
}

class RefreshError extends Error {
  readonly status: number;

  constructor(status: number) {
    super(`POST /v1/auth/refresh returned ${status}`);
    this.name = "RefreshError";
    this.status = status;
  }
}

async function fetchRefresh(refreshToken: string): Promise<RefreshResponse> {
  const res = await fetch(`${API_BASE_URL}/v1/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
    credentials: "include",
  });
  if (!res.ok) {
    throw new RefreshError(res.status);
  }
  return (await res.json()) as RefreshResponse;
}

const REFRESH_DELAYS_MS = [1000, 2000];

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isRetryableRefreshError(err: unknown): boolean {
  return !(err instanceof RefreshError && err.status < 500);
}

/**
 * Attempt a token refresh with bounded retries. The refresh token is rotated on
 * success and returned to the caller for persistence; on exhaustion the last
 * error is rethrown so callers can decide how to handle the failed session.
 *
 * api-standards §5: retry only on network failures and 5xx, never on 4xx.
 */
export async function attemptRefresh(
  refreshToken: string,
): Promise<RefreshResponse> {
  let lastError: unknown;
  for (let attempt = 1; attempt <= 3; attempt++) {
    try {
      return await fetchRefresh(refreshToken);
    } catch (err) {
      lastError = err;
      if (!isRetryableRefreshError(err) || attempt === 3) {
        break;
      }
      await delay(REFRESH_DELAYS_MS[attempt - 1]);
    }
  }
  if (lastError instanceof Error) {
    throw lastError;
  }
  throw new Error("token refresh exhausted");
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  // #904: /v1/me runs through the shared query client (the root QueryProvider
  // supplies it; a bare mount, as in tests, falls back to a private client).
  const outerClient = useContext(QueryClientContext);
  const [fallbackClient] = useState(() => makeQueryClient());
  const queryClient: QueryClient = outerClient ?? fallbackClient;
  const [user, setUser] = useState<User | null>(null);
  const [selectedRole, setSelectedRole] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function validate() {
      const session: StoredSession | null = readSession();

      if (!session) {
        if (!cancelled) {
          setIsLoading(false);
        }
        return;
      }

      try {
        const me = await fetchSessionMe(queryClient, session.jwt);
        if (cancelled) return;

        applyMe(me, setUser, setSelectedRole);
      } catch (err) {
        if (cancelled) return;

        try {
          const refreshed = await attemptRefresh(session.refresh_token);
          if (cancelled) return;

          const updated: StoredSession = {
            ...session,
            jwt: refreshed.jwt,
            refresh_token: refreshed.refresh_token,
          };
          localStorage.setItem("caresetu.session", JSON.stringify(updated));
          localStorage.setItem("caresetu.access_jwt", refreshed.jwt);
          localStorage.setItem(
            "caresetu.refresh_token",
            refreshed.refresh_token,
          );

          const me = await fetchSessionMe(queryClient, refreshed.jwt);
          if (cancelled) return;

          applyMe(me, setUser, setSelectedRole);
        } catch (refreshErr) {
          if (cancelled) return;

          console.warn("[auth] session validation refresh failed", refreshErr);
          clearSession();
          clearCachedSessionMe(queryClient);
          clearCookie("caresetu.access_jwt");
          router.replace("/login");
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    validate();

    return () => {
      cancelled = true;
    };
  }, [router, queryClient]);

  useEffect(() => {
    if (!user) {
      if (refreshTimerRef.current) {
        clearTimeout(refreshTimerRef.current);
        refreshTimerRef.current = null;
      }
      return;
    }

    let cancelled = false;

    const clearTimer = (): void => {
      if (refreshTimerRef.current) {
        clearTimeout(refreshTimerRef.current);
        refreshTimerRef.current = null;
      }
    };

    const schedule = (): void => {
      clearTimer();
      const delayMs = ACCESS_TOKEN_TTL_SECONDS * 1000 * PROACTIVE_REFRESH_RATIO;
      refreshTimerRef.current = setTimeout(() => {
        void tick();
      }, delayMs);
    };

    const tick = async (): Promise<void> => {
      if (cancelled) return;
      const session = readSession();
      if (!session) {
        clearTimer();
        return;
      }
      try {
        const refreshed = await attemptRefresh(session.refresh_token);
        if (cancelled) return;
        const updated: StoredSession = {
          ...session,
          jwt: refreshed.jwt,
          refresh_token: refreshed.refresh_token,
        };
        localStorage.setItem("caresetu.session", JSON.stringify(updated));
        localStorage.setItem("caresetu.access_jwt", refreshed.jwt);
        localStorage.setItem("caresetu.refresh_token", refreshed.refresh_token);
        if (cancelled) return;
        schedule();
      } catch (err) {
        if (cancelled) return;

        console.warn("[auth] proactive refresh failed, scheduling retry", err);
        // Retry once with backoff before force logout
        clearTimer();
        refreshTimerRef.current = setTimeout(() => {
          void tickRetry();
        }, 5_000);
      }
    };

    const tickRetry = async (): Promise<void> => {
      if (cancelled) return;
      const session = readSession();
      if (!session) {
        clearTimer();
        return;
      }
      try {
        const refreshed = await attemptRefresh(session.refresh_token);
        if (cancelled) return;
        const updated: StoredSession = {
          ...session,
          jwt: refreshed.jwt,
          refresh_token: refreshed.refresh_token,
        };
        localStorage.setItem("caresetu.session", JSON.stringify(updated));
        localStorage.setItem("caresetu.access_jwt", refreshed.jwt);
        localStorage.setItem("caresetu.refresh_token", refreshed.refresh_token);
        if (cancelled) return;
        schedule();
      } catch (err) {
        if (cancelled) return;

        console.warn(
          "[auth] proactive refresh retry failed, forcing logout",
          err,
        );
        clearTimer();
        clearSession();
        clearCookie("caresetu.access_jwt");
        setUser(null);
        setSelectedRole(null);
        router.replace("/login");
      }
    };

    schedule();

    return () => {
      cancelled = true;
      clearTimer();
    };
  }, [user, router]);

  function switchRole(role: string) {
    setSelectedRole(role);
    saveSelectedRole(role);
  }

  // Session-resume seam (#496): resolves identity in-flow after the OTP flow
  // persists a fresh login session. Deliberately reuses the same /v1/me (+
  // refresh retry) resolution path as mount validation instead of decoding the
  // stored JWT client-side, so identity and roles are sourced the same way
  // across reloads and fresh logins. On refresh exhaustion the session is
  // cleared and the user is sent to /login (#837): a token that cannot be
  // refreshed must not leave the app half-authenticated.
  const resumeSession = useCallback(async (): Promise<void> => {
    const session: StoredSession | null = readSession();
    if (!session) return;

    try {
      const me = await fetchSessionMe(queryClient, session.jwt);
      applyMe(me, setUser, setSelectedRole);
    } catch (err) {
      try {
        const refreshed = await attemptRefresh(session.refresh_token);

        const updated: StoredSession = {
          ...session,
          jwt: refreshed.jwt,
          refresh_token: refreshed.refresh_token,
        };
        localStorage.setItem("caresetu.session", JSON.stringify(updated));
        localStorage.setItem("caresetu.access_jwt", refreshed.jwt);
        localStorage.setItem("caresetu.refresh_token", refreshed.refresh_token);

        const me = await fetchSessionMe(queryClient, refreshed.jwt);
        applyMe(me, setUser, setSelectedRole);
      } catch (refreshErr) {
        console.warn("[auth] session resume refresh failed", refreshErr);
        clearSession();
        clearCachedSessionMe(queryClient);
        clearCookie("caresetu.access_jwt");
        setUser(null);
        setSelectedRole(null);
        router.replace("/login");
      }
    }
  }, [router, queryClient]);

  function logout() {
    clearSession();
    clearSelectedRole();
    clearCachedSessionMe(queryClient);
    clearCookie("caresetu.access_jwt");
    if (refreshTimerRef.current) {
      clearTimeout(refreshTimerRef.current);
      refreshTimerRef.current = null;
    }
    setUser(null);
    setSelectedRole(null);
    router.replace("/");
  }

  return (
    <QueryClientContext.Provider value={queryClient}>
      <AuthContext.Provider
        value={{
          user,
          selectedRole,
          switchRole,
          logout,
          isAuthenticated: user !== null,
          isLoading,
          resumeSession,
        }}
      >
        {children}
      </AuthContext.Provider>
    </QueryClientContext.Provider>
  );
}
