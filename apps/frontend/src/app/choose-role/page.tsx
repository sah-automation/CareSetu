"use client";

// PHASE-2.5 T7 (#153): Choose-role page for multi-role users.
// Displays available roles as selectable cards. On selection, stores the
// chosen role in localStorage and redirects to the role dashboard. If the
// user has only one role, redirects directly without showing the picker.

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import {
  readSession,
  saveSelectedRole,
  readSelectedRole,
} from "@/lib/auth/session";

const API_BASE_URL: string =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

interface MeResponse {
  identity_id: number;
  phone: string;
  roles: string[];
}

const ROLE_META: Record<string, { label: string; description: string }> = {
  patient: {
    label: "Patient",
    description: "Access your health records and consultations",
  },
  partner: {
    label: "Partner",
    description: "Manage partner clinic operations",
  },
  operator: {
    label: "Operator",
    description: "Oversee platform administration",
  },
};

function getRoleMeta(role: string) {
  return (
    ROLE_META[role] ?? {
      label: role.charAt(0).toUpperCase() + role.slice(1),
      description: `Access the ${role} dashboard`,
    }
  );
}

export default function ChooseRolePage() {
  const router = useRouter();
  const [roles, setRoles] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      const session = readSession();
      if (!session) {
        router.replace("/login");
        return;
      }

      try {
        const res = await fetch(`${API_BASE_URL}/v1/me`, {
          headers: { Authorization: `Bearer ${session.jwt}` },
        });

        if (!res.ok) {
          router.replace("/login");
          return;
        }

        const me: MeResponse = await res.json();

        if (cancelled) return;

        if (me.roles.length === 0) {
          router.replace("/login");
          return;
        }

        if (me.roles.length === 1) {
          saveSelectedRole(me.roles[0]);
          router.replace(`/${me.roles[0]}`);
          return;
        }

        const saved = readSelectedRole();
        if (saved && me.roles.includes(saved)) {
          router.replace(`/${saved}`);
          return;
        }

        setRoles(me.roles);
      } catch {
        if (!cancelled) {
          router.replace("/login");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    load();

    return () => {
      cancelled = true;
    };
  }, [router]);

  function handleSelectRole(role: string) {
    saveSelectedRole(role);
    router.replace(`/${role}`);
  }

  if (loading) {
    return null;
  }

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontFamily:
          '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
        backgroundColor: "#f8fafc",
        color: "#1e293b",
      }}
    >
      <div
        style={{
          textAlign: "center",
          padding: "2rem",
          maxWidth: "480px",
          width: "100%",
        }}
      >
        <h1
          style={{
            fontSize: "1.5rem",
            fontWeight: "bold",
            marginBottom: "0.5rem",
          }}
        >
          Choose your role
        </h1>
        <p style={{ color: "#64748b", marginBottom: "2rem" }}>
          Select how you want to use CareSetu
        </p>

        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: "1rem",
          }}
        >
          {roles.map((role) => {
            const meta = getRoleMeta(role);
            return (
              <button
                key={role}
                type="button"
                onClick={() => handleSelectRole(role)}
                style={{
                  display: "block",
                  width: "100%",
                  padding: "1.25rem",
                  backgroundColor: "#ffffff",
                  border: "1px solid #e2e8f0",
                  borderRadius: "0.75rem",
                  cursor: "pointer",
                  textAlign: "left",
                  boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
                  transition: "border-color 0.15s, box-shadow 0.15s",
                }}
              >
                <div
                  style={{
                    fontSize: "1.125rem",
                    fontWeight: "600",
                    marginBottom: "0.25rem",
                  }}
                >
                  {meta.label}
                </div>
                <div style={{ fontSize: "0.875rem", color: "#64748b" }}>
                  {meta.description}
                </div>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
