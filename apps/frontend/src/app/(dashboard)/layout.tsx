"use client";

import type { ReactNode } from "react";
import { useState, useEffect } from "react";
import { AuthProvider, useAuth } from "@/lib/auth/AuthContext";
import { Sidebar } from "@/components/dashboard/Sidebar";
import { Topbar } from "@/components/dashboard/Topbar";
import type { Role } from "@/components/dashboard/types";
import {
  SIDEBAR_MARGIN_COLLAPSED,
  SIDEBAR_MARGIN_EXPANDED,
} from "@/components/dashboard/types";

function DashboardShell({ children }: { children: ReactNode }) {
  const { selectedRole, isLoading } = useAuth();
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 1023px)");
    setCollapsed(mq.matches);
    function handleChange(e: MediaQueryListEvent) {
      setCollapsed(e.matches);
    }
    mq.addEventListener("change", handleChange);
    return () => mq.removeEventListener("change", handleChange);
  }, []);

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-page-bg">
        <div className="text-sm text-txt-muted">Loading...</div>
      </div>
    );
  }

  const role: Role = (selectedRole as Role) ?? "patient";

  return (
    <div className="min-h-screen bg-page-bg">
      <Sidebar
        role={role}
        collapsed={collapsed}
        onToggle={() => setCollapsed(!collapsed)}
      />
      <Topbar />
      <main
        className={`pt-14 transition-all duration-200 ${
          collapsed ? SIDEBAR_MARGIN_COLLAPSED : SIDEBAR_MARGIN_EXPANDED
        }`}
      >
        <div className="p-6">{children}</div>
      </main>
    </div>
  );
}

export default function DashboardLayout({ children }: { children: ReactNode }) {
  return (
    <AuthProvider>
      <DashboardShell>{children}</DashboardShell>
    </AuthProvider>
  );
}
