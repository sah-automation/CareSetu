"use client";

// AuthContext - session validation, role management, and logout for the
// dashboard routes. Reads the stored session on mount, validates against
// GET /v1/me, auto-refreshes expired JWTs, and redirects to /login when
// the session is invalid. (PHASE-2.5 T3, #151)

import { createContext, useContext, useEffect, useState } from "react";
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
  identity_id: number;
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
    id: me.identity_id,
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
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}
