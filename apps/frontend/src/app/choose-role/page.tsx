"use client";

// PHASE-2.5 T7 (#153): Choose-role page for multi-role users.
// Displays available roles as selectable cards. On selection, stores the
// chosen role in localStorage and redirects to the role dashboard. If the
// user has only one role, redirects directly without showing the picker.
// Session state comes from the shared AuthProvider at the root layout;
// this page performs no session storage reads or /v1/me calls of its own.
// (PHASE-2.6 T01, #192)

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/lib/auth/AuthContext";
import { saveSelectedRole, readSelectedRole } from "@/lib/auth/session";

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
  const { user, isLoading, isAuthenticated } = useAuth();

  // Stable reference from context state (undefined while signed out) so the
  // redirect effect below does not churn on every render.
  const roles = user?.roles;

  useEffect(() => {
    if (isLoading) {
      return;
    }

    if (!isAuthenticated || !roles || roles.length === 0) {
      router.replace("/login");
      return;
    }

    if (roles.length === 1) {
      saveSelectedRole(roles[0]);
      router.replace(`/${roles[0]}`);
      return;
    }

    const saved = readSelectedRole();
    if (saved && roles.includes(saved)) {
      router.replace(`/${saved}`);
    }
  }, [isLoading, isAuthenticated, router, roles]);

  function handleSelectRole(role: string) {
    saveSelectedRole(role);
    router.replace(`/${role}`);
  }

  if (isLoading) {
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
          {(roles ?? []).map((role) => {
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
