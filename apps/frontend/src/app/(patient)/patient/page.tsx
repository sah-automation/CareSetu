"use client";

// PHASE-2.5 T6 (#152): Patient channel page placeholder.
// After successful login, users land here. The actual dashboard layout
// will be built in T8. For now, this is a simple authenticated view.

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { readSession, clearSession } from "@/lib/auth/session";

export default function PatientChannelPage() {
  const router = useRouter();
  const [session, setSession] = useState<ReturnType<typeof readSession>>(null);

  useEffect(() => {
    const stored = readSession();
    if (!stored) {
      router.replace("/login");
      return;
    }
    setSession(stored);
  }, [router]);

  function handleSignOut() {
    clearSession();
    router.replace("/login");
  }

  if (!session) {
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
          backgroundColor: "#ffffff",
          borderRadius: "0.75rem",
          boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
          maxWidth: "400px",
        }}
      >
        <h1
          style={{
            fontSize: "1.5rem",
            fontWeight: "bold",
            marginBottom: "0.5rem",
          }}
        >
          CareSetu Patient
        </h1>
        <p style={{ color: "#64748b", marginBottom: "1.5rem" }}>
          Signed in as {session.phone}
        </p>
        <button
          type="button"
          onClick={handleSignOut}
          style={{
            padding: "0.5rem 1.5rem",
            backgroundColor: "#f1f5f9",
            color: "#475569",
            border: "1px solid #e2e8f0",
            borderRadius: "0.375rem",
            cursor: "pointer",
            fontWeight: "500",
          }}
        >
          Sign out
        </button>
      </div>
    </div>
  );
}
