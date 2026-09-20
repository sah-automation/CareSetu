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
  useState,
} from "react";
import { useRouter } from "next/navigation";
import {
  readSession,
  clearSession,
  readSelectedRole,
  saveSelectedRole,
  clearSelectedRole,
  type StoredSession,
} from "./session";

const API_BASE_URL: string =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export interface User {
  id: number;
  phone: string;
  roles: string[];
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

interface MeResponse {
  /** The principal identity the token is scoped to (a numeric string, #196). */
  subject_id: string;
  phone: string;
  roles: string[];
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
  });
  if (me.roles.length > 0) {
    const saved = readSelectedRole();
    const role = saved && me.roles.includes(saved) ? saved : me.roles[0];
    setSelectedRole(role);
  }
}

async function fetchMe(jwt: string): Promise<MeResponse> {
  const res = await fetch(`${API_BASE_URL}/v1/me`, {
    headers: { Authorization: `Bearer ${jwt}` },
  });
  if (!res.ok) {
    throw new Error(`GET /v1/me returned ${res.status}`);
  }
  return (await res.json()) as MeResponse;
}

async function fetchRefresh(refreshToken: string): Promise<RefreshResponse> {
  const res = await fetch(`${API_BASE_URL}/v1/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
    credentials: "include",
  });
  if (!res.ok) {
    throw new Error(`POST /v1/auth/refresh returned ${res.status}`);
  }
  return (await res.json()) as RefreshResponse;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [selectedRole, setSelectedRole] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

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
        const me = await fetchMe(session.jwt);
        if (cancelled) return;

        applyMe(me, setUser, setSelectedRole);
      } catch (err) {
        if (cancelled) return;
        console.error("[AuthContext] /v1/me failed, attempting refresh:", err);

        // GET /v1/me failed - try refresh if the error suggests an expired JWT
        try {
          const refreshed = await fetchRefresh(session.refresh_token);
          if (cancelled) return;

          // Update localStorage with new tokens
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

          // Retry /v1/me with the new JWT
          const me = await fetchMe(refreshed.jwt);
          if (cancelled) return;

          applyMe(me, setUser, setSelectedRole);
        } catch (refreshErr) {
          if (cancelled) return;
          console.error(
            "[AuthContext] refresh failed, clearing session:",
            refreshErr,
          );

          // Refresh also failed - clear everything and redirect
          clearSession();
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
  }, [router]);

  function switchRole(role: string) {
    setSelectedRole(role);
    saveSelectedRole(role);
  }

  // Session-resume seam (#496): resolves identity in-flow after the OTP flow
  // persists a fresh login session. Deliberately reuses the same /v1/me (+
  // refresh retry) resolution path as mount validation instead of decoding the
  // stored JWT client-side, so identity and roles are sourced the same way
  // across reloads and fresh logins. Best-effort: a resolution failure leaves
  // state untouched and never force-logs-out a session the user just minted -
  // the patient profile Finish invariant surfaces the unresolved window.
  const resumeSession = useCallback(async (): Promise<void> => {
    const session: StoredSession | null = readSession();
    if (!session) return;

    try {
      const me = await fetchMe(session.jwt);
      applyMe(me, setUser, setSelectedRole);
    } catch (err) {
      console.error(
        "[AuthContext] resume /v1/me failed, attempting refresh:",
        err,
      );

      try {
        const refreshed = await fetchRefresh(session.refresh_token);

        // Update localStorage with the rotated tokens, matching the mount
        // validation path exactly.
        const updated: StoredSession = {
          ...session,
          jwt: refreshed.jwt,
          refresh_token: refreshed.refresh_token,
        };
        localStorage.setItem("caresetu.session", JSON.stringify(updated));
        localStorage.setItem("caresetu.access_jwt", refreshed.jwt);
        localStorage.setItem("caresetu.refresh_token", refreshed.refresh_token);

        const me = await fetchMe(refreshed.jwt);
        applyMe(me, setUser, setSelectedRole);
      } catch (refreshErr) {
        console.error(
          "[AuthContext] resume resolution failed; identity stays unresolved:",
          refreshErr,
        );
      }
    }
  }, []);

  function logout() {
    clearSession();
    clearSelectedRole();
    clearCookie("caresetu.access_jwt");
    setUser(null);
    setSelectedRole(null);
    router.replace("/");
  }

  return (
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
  );
}
